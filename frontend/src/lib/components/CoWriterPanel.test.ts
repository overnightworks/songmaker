import { makeHealthResponse, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoWriterStreamEvent } from '$lib/api/client';
import type { ChatMessageItem } from '$lib/api/types';
import {
	COWRITER_CLAUDE_UNVERIFIED_LABEL,
	COWRITER_CONVERSATION_MENU_LABEL,
	COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT,
	COWRITER_RUNNING_TURN_POLL_MS
} from '$lib/constants';

import { ApiError } from '$lib/api/fetch';

const streamCoWriterTurn = vi.hoisted(() => vi.fn());
const fetchConversations = vi.hoisted(() => vi.fn());
const fetchConversationMessages = vi.hoisted(() => vi.fn());
const fetchCowriterSettings = vi.hoisted(() => vi.fn());
const fetchHealth = vi.hoisted(() => vi.fn());

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchConversations: (...args: Parameters<typeof fetchConversations>) =>
			fetchConversations(...args),
		fetchConversationMessages: (...args: Parameters<typeof fetchConversationMessages>) =>
			fetchConversationMessages(...args),
		startNewConversation: vi.fn(async () => ({
			id: 'c1',
			title: null,
			message_count: 0,
			archived_at: null,
			created_at: '2026-01-01T00:00:00+00:00'
		})),
		deleteConversation: vi.fn(),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchCowriterSettings: (...args: Parameters<typeof fetchCowriterSettings>) =>
			fetchCowriterSettings(...args),
		fetchHealth: (...args: Parameters<typeof fetchHealth>) => fetchHealth(...args),
		streamCoWriterTurn: (...args: Parameters<typeof streamCoWriterTurn>) =>
			streamCoWriterTurn(...args)
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';
import { fetchMemory, startNewConversation } from '$lib/api/client';
import { startHealthPolling, stopHealthPolling } from '$lib/stores/health';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	fetchConversations.mockReset().mockResolvedValue([]);
	fetchConversationMessages.mockReset().mockResolvedValue({ messages: [] });
	fetchCowriterSettings.mockReset().mockResolvedValue({ provider: 'claude', model: 'sonnet' });
	fetchHealth.mockReset().mockResolvedValue(makeHealthResponse());
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	stopHealthPolling();
	streamCoWriterTurn.mockReset();
});

async function* turnEvents(events: CoWriterStreamEvent[]) {
	for (const event of events) yield event;
}

/** Streams that end without the server's own error frame: the turn itself may still run. */
const droppedStreams: Array<[string, () => AsyncGenerator<CoWriterStreamEvent>]> = [
	['a stream that ends before its final event', () => turnEvents([])],
	[
		'a timed out stream',
		async function* () {
			yield* [] as CoWriterStreamEvent[];
			throw Object.assign(new Error('aborted'), { name: 'AbortError' });
		}
	],
	[
		'a stream the network dropped',
		async function* () {
			yield { type: 'assistant_text', text: 'Mach ich' } as CoWriterStreamEvent;
			throw new TypeError('Failed to fetch');
		}
	]
];

/**
 * After a turn's "final" event, the panel reloads conversations to confirm
 * which one is active. The real backend already reflects the just-created
 * conversation at that point; the mock must too, or the reload wipes the
 * turn's own messages back out from under the assertion.
 */
function activeConversation(id: string) {
	return {
		id,
		title: null,
		message_count: 2,
		archived_at: null,
		created_at: '2026-01-01T00:00:00+00:00'
	};
}

function chatMessage(id: string, role: 'user' | 'assistant', content: string): ChatMessageItem {
	return { id, role, content, created_at: '2026-09-26T15:21:00+00:00' };
}

function conversation(turnRunning: boolean, ...messages: ChatMessageItem[]) {
	return {
		conversation_id: 'c1',
		title: null,
		archived_at: null,
		messages,
		turn_running: turnRunning
	};
}

/** Each page answers one read of the conversation, in order. */
function conversationPages(...pages: ReturnType<typeof conversation>[]): void {
	for (const page of pages) fetchConversationMessages.mockResolvedValueOnce(page);
}

/** The chat as the musician reads it: one entry per bubble, including a failure note. */
function chatView(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.message'), (message) =>
		(message.textContent ?? '').replace(/\s+/g, ' ').trim()
	);
}

async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	startHealthPolling();
	await Promise.resolve();
	mounted.push(
		mount(CoWriterPanel, {
			target,
			props: {
				currentSongId: 's1',
				currentAlbumId: 'a1',
				currentAlbumTitle: 'Album',
				allSongs: [song({ slug: 'open-song', title: 'Open Song', generation_count: 0 })],
				...overrides
			}
		})
	);
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

async function sendMessage(target: HTMLElement, message: string): Promise<void> {
	const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
	if (!input) throw new Error('Expected the chat textarea');
	input.value = message;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	target.querySelector<HTMLButtonElement>('.send-btn')?.click();
	await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(2));
	await tick();
	await vi.waitFor(() => expect(target.querySelector('.tool-call')).not.toBeNull());
}

async function sendTurn(target: HTMLElement, message: string): Promise<void> {
	const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
	if (!input) throw new Error('Expected the chat textarea');
	input.value = message;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	target.querySelector<HTMLButtonElement>('.send-btn')?.click();
}

/** The one line above the chat, as the musician reads it. */
function conversationLine(target: HTMLElement): string {
	return (target.querySelector('.convo-line')?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

async function openConversationMenu(target: HTMLElement): Promise<HTMLElement> {
	target
		.querySelector<HTMLButtonElement>(`button[aria-label="${COWRITER_CONVERSATION_MENU_LABEL}"]`)
		?.click();
	await tick();
	const menu = target.querySelector<HTMLElement>('[role="menu"]');
	if (!menu) throw new Error('Expected the conversation menu');
	return menu;
}

function conversationStartedAt(createdAt: string) {
	return { ...activeConversation('c1'), created_at: createdAt };
}

describe('CoWriterPanel', () => {
	it('renders without a Close button (its lifecycle is owned by the Editor header toggle)', async () => {
		const target = await render();
		expect(target.querySelector('.close-btn')).toBeNull();
	});

	it('has no left border now that it fills the Write column instead of a side panel', async () => {
		const target = await render();
		const root = target.querySelector('.cowriter');
		expect(root).not.toBeNull();
		expect(getComputedStyle(root as Element).borderLeftWidth).not.toBe('1px');
	});

	it('renders no back control of its own — on the phone the song app bar stays above the Co-writer tab', async () => {
		const target = await render();
		expect(target.querySelector('.cowriter-back')).toBeNull();
		expect(target.querySelector('.app-bar')).toBeNull();
	});

	it('keeps focus in the composer when Send is pressed, so the bars coming back cannot move Send from under a phone tap', async () => {
		const target = await render();
		const pressSend = new MouseEvent('mousedown', { bubbles: true, cancelable: true });

		target.querySelector<HTMLButtonElement>('.send-btn')?.dispatchEvent(pressSend);

		expect(pressSend.defaultPrevented).toBe(true);
	});
});

describe('CoWriterPanel conversation line (#1063)', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-09-27T12:00:00'));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it.each([
		['no conversation yet', [], 'Claude · new conversation'],
		[
			'one started today',
			[conversationStartedAt('2026-09-27T08:00:00')],
			'Claude · conversation since today'
		],
		[
			'one started this week',
			[conversationStartedAt('2026-09-22T10:00:00')],
			'Claude · conversation since Tue'
		],
		[
			'one started earlier this year',
			[conversationStartedAt('2026-09-12T10:00:00')],
			'Claude · conversation since Sep 12'
		],
		[
			'one started last year',
			[conversationStartedAt('2025-09-12T10:00:00')],
			'Claude · conversation since Sep 12, 2025'
		]
	])('names the provider and %s in one line', async (_case, conversations, line) => {
		fetchConversations.mockResolvedValue(conversations);
		const target = await render();

		await vi.waitFor(() => expect(conversationLine(target)).toBe(line));
	});

	it('names the provider the co-writer is set to', async () => {
		fetchCowriterSettings.mockResolvedValue({ provider: 'grok', model: 'grok-4' });
		const target = await render();

		await vi.waitFor(() => expect(conversationLine(target)).toBe('Grok · new conversation'));
	});

	it('is the only header: no Co-Writer title, and neither the model nor a conversation button on the line', async () => {
		fetchConversations.mockResolvedValue([conversationStartedAt('2026-09-22T10:00:00')]);
		const target = await render();
		const line = target.querySelector<HTMLElement>('.convo');

		expect(target.textContent).not.toContain('Co-Writer');
		expect(line?.textContent).not.toContain('sonnet');
		expect(
			Array.from(line?.querySelectorAll('button') ?? [], (button) =>
				button.getAttribute('aria-label')
			)
		).toEqual([COWRITER_CONVERSATION_MENU_LABEL]);
	});

	it('keeps the model, a new conversation and switching conversations in its ⋯ menu', async () => {
		const older = {
			...activeConversation('c0'),
			created_at: '2026-09-20T10:00:00',
			archived_at: '2026-09-22T10:00:00'
		};
		fetchConversations.mockResolvedValue([conversationStartedAt('2026-09-22T10:00:00'), older]);
		const target = await render();

		const menu = await openConversationMenu(target);
		expect(menu.textContent).toContain('Claude · sonnet');
		const conversationRows = menu.querySelectorAll<HTMLButtonElement>('.conv-pick');
		expect(conversationRows).toHaveLength(2);

		conversationRows[1].click();
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenLastCalledWith('c0'));
		await tick();
		expect(target.querySelector('[role="menu"]')).toBeNull();
		expect(conversationLine(target)).toBe('Claude · archived conversation from Sep 20');

		const reopened = await openConversationMenu(target);
		reopened.querySelector<HTMLButtonElement>('.convo-new')?.click();
		await tick();
		expect(startNewConversation).toHaveBeenCalledTimes(1);
		expect(target.querySelector('[role="menu"]')).toBeNull();
		await vi.waitFor(() => expect(conversationLine(target)).toBe('Claude · new conversation'));
	});

	it('names each conversation in its ⋯ menu with the line’s day form', async () => {
		const older = {
			...activeConversation('c0'),
			created_at: '2026-09-17T10:00:00',
			archived_at: '2026-09-22T10:00:00'
		};
		fetchConversations.mockResolvedValue([conversationStartedAt('2026-09-22T10:00:00'), older]);
		const target = await render();

		const menu = await openConversationMenu(target);

		expect(Array.from(menu.querySelectorAll('.conv-title'), (title) => title.textContent)).toEqual([
			'Conversation since Tue',
			'Conversation from Sep 17'
		]);
	});

	it('reads “conversation since today” once the first message is sent, before the reply arrives', async () => {
		let deliverReply = (): void => {};
		const replyDelivered = new Promise<void>((resolve) => {
			deliverReply = resolve;
		});
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				await replyDelivered;
				yield {
					type: 'final',
					conversation_id: 'c1',
					user_message: chatMessage('m1', 'user', 'write a chorus'),
					assistant_message: chatMessage('m2', 'assistant', 'Here it is.')
				} as CoWriterStreamEvent;
			})()
		);
		const target = await render();
		await vi.waitFor(() => expect(conversationLine(target)).toBe('Claude · new conversation'));

		await sendTurn(target, 'write a chorus');

		await vi.waitFor(() =>
			expect(conversationLine(target)).toBe('Claude · conversation since today')
		);
		fetchConversations.mockResolvedValue([
			conversationStartedAt(new Date('2026-09-27T11:59:00').toISOString())
		]);
		deliverReply();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalledTimes(2));
		expect(conversationLine(target)).toBe('Claude · conversation since today');
	});

	it('shows the current message count in its ⋯ menu after a turn', async () => {
		const sent = chatMessage('m3', 'user', 'now a bridge');
		const reply = chatMessage('m4', 'assistant', 'Four lines.');
		fetchConversations.mockResolvedValue([conversationStartedAt('2026-09-22T10:00:00')]);
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
			])
		);
		const target = await render();
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));
		fetchConversations.mockResolvedValue([
			{ ...conversationStartedAt('2026-09-22T10:00:00'), message_count: 4 }
		]);

		await sendTurn(target, sent.content);
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalledTimes(2));
		const menu = await openConversationMenu(target);

		expect(menu.querySelector('.conv-meta')?.textContent?.trim()).toBe('4 msgs');
	});

	it('closes its ⋯ menu on Escape without leaving the song', async () => {
		const target = await render();
		await openConversationMenu(target);
		const escape = new KeyboardEvent('keydown', {
			key: 'Escape',
			bubbles: true,
			cancelable: true
		});

		document.dispatchEvent(escape);
		await tick();

		expect(target.querySelector('[role="menu"]')).toBeNull();
		expect(escape.defaultPrevented).toBe(true);
	});

	it('keeps Memory in its ⋯ menu rather than a row above the chat, and opens the memory editor from there', async () => {
		vi.mocked(fetchMemory).mockResolvedValueOnce({
			user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' }
		});
		const target = await render();
		const userMemory = () =>
			target.querySelector<HTMLTextAreaElement>('textarea[aria-label="User memory"]');
		expect(
			Array.from(target.querySelectorAll('button'), (button) => button.textContent?.trim())
		).not.toContainEqual(expect.stringMatching(/^Memory/));

		const menu = await openConversationMenu(target);
		const memoryItem = Array.from(
			menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')
		).find((item) => item.textContent?.trim() === 'Memory');
		memoryItem?.click();
		await tick();

		expect(target.querySelector('[role="menu"]')).toBeNull();
		await vi.waitFor(() => expect(userMemory()?.value).toBe('Prefers short lines'));

		target.querySelector<HTMLButtonElement>('button[aria-label="Close memory"]')?.click();
		await tick();
		expect(userMemory()).toBeNull();
	});
});

describe('CoWriterPanel chat scroll across tab switches (#1063)', () => {
	const CHAT_HEIGHT = 300;
	const SCROLLED_UP_TO = 100;
	const earlier = chatMessage('m1', 'user', 'the chorus feels long');
	const earlierReply = chatMessage('m2', 'assistant', 'Drop the third line.');
	const sent = chatMessage('m3', 'user', 'now a bridge');
	const reply = chatMessage('m4', 'assistant', 'Four lines, no chorus rhyme.');

	let resize: () => void = () => {};

	beforeEach(() => {
		const callbacks: ResizeObserverCallback[] = [];
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(callback: ResizeObserverCallback) {
					callbacks.push(callback);
				}
				observe(): void {}
				unobserve(): void {}
				disconnect(): void {}
			}
		);
		resize = () => {
			for (const callback of callbacks) callback([], {} as ResizeObserver);
		};
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/**
	 * jsdom lays nothing out, so the chat's box is played the way a browser
	 * shows it: nothing measured while the pane is hidden, a scroll offset
	 * clamped to what the content allows, and lost once the box is gone.
	 */
	function chatBox(list: HTMLElement) {
		const box = { clientHeight: 0, scrollHeight: 0, scrollTop: 0 };
		Object.defineProperty(list, 'clientHeight', { get: () => box.clientHeight });
		Object.defineProperty(list, 'scrollHeight', { get: () => box.scrollHeight });
		Object.defineProperty(list, 'scrollTop', {
			get: () => box.scrollTop,
			set: (top: number) => {
				box.scrollTop = Math.max(0, Math.min(top, box.scrollHeight - box.clientHeight));
			}
		});
		return {
			box,
			show(contentHeight: number) {
				box.clientHeight = CHAT_HEIGHT;
				box.scrollHeight = contentHeight;
				resize();
			},
			hide() {
				box.clientHeight = 0;
				box.scrollHeight = 0;
				box.scrollTop = 0;
				resize();
			},
			scrollTo(top: number) {
				list.scrollTop = top;
				list.dispatchEvent(new Event('scroll'));
			}
		};
	}

	it.each([
		['following the newest message sees the reply', null, 1200 - CHAT_HEIGHT],
		['who scrolled up to read stays where they were', SCROLLED_UP_TO, SCROLLED_UP_TO]
	])(
		'a musician %s when it arrived while Edit or Takes was shown',
		async (_case, scrolledUpTo, scrollTopOnReturn) => {
			fetchConversations.mockResolvedValue([activeConversation('c1')]);
			conversationPages(
				conversation(false, earlier, earlierReply),
				conversation(false, earlier, earlierReply, sent, reply)
			);
			let deliverReply = (): void => {};
			const replyDelivered = new Promise<void>((resolve) => {
				deliverReply = resolve;
			});
			streamCoWriterTurn.mockReturnValue(
				(async function* () {
					await replyDelivered;
					yield {
						type: 'final',
						conversation_id: 'c1',
						user_message: sent,
						assistant_message: reply
					} as CoWriterStreamEvent;
				})()
			);
			const target = await render();
			await vi.waitFor(() => expect(chatView(target)).toHaveLength(2));
			const list = target.querySelector<HTMLElement>('.messages');
			if (!list) throw new Error('Expected the message list');
			const chat = chatBox(list);
			chat.show(600);

			await sendTurn(target, sent.content);
			await tick();
			if (scrolledUpTo !== null) chat.scrollTo(scrolledUpTo);
			chat.hide();
			deliverReply();
			await vi.waitFor(() => expect(chatView(target)).toHaveLength(4));

			chat.show(1200);

			expect(chat.box.scrollTop).toBe(scrollTopOnReturn);
		}
	);
});

describe('CoWriterPanel unavailable before any turn', () => {
	it('names Claude unavailable and refuses Send via click, Enter, and the retry link once its tool surface drifts', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ claude_cli_tool_surface: 'ok' }));
		streamCoWriterTurn.mockReturnValueOnce(
			(async function* () {
				yield* [];
				throw new ApiError(503, 'Claude CLI is temporarily unavailable', '/api/chat/turn');
			})()
		);
		const target = await render();

		await sendTurn(target, 'write a chorus');
		await vi.waitFor(() =>
			expect(target.querySelector<HTMLButtonElement>('.retry-turn')).not.toBeNull()
		);
		expect(streamCoWriterTurn).toHaveBeenCalledTimes(1);

		stopHealthPolling();
		fetchHealth.mockResolvedValue(makeHealthResponse({ claude_cli_tool_surface: 'drift' }));
		startHealthPolling();
		await vi.waitFor(() =>
			expect(target.querySelector('.unavailable-banner')?.textContent).toContain(
				'Claude is currently unavailable'
			)
		);

		target.querySelector<HTMLButtonElement>('.send-btn')?.click();
		await tick();
		expect(streamCoWriterTurn).toHaveBeenCalledTimes(1);

		const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
		if (!input) throw new Error('Expected the chat textarea');
		input.value = 'another try';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(streamCoWriterTurn).toHaveBeenCalledTimes(1);

		target.querySelector<HTMLButtonElement>('.retry-turn')?.click();
		await tick();
		expect(streamCoWriterTurn).toHaveBeenCalledTimes(1);
	});

	it('warns without disabling Send when the tool surface is unverified, and still sends the turn', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ claude_cli_tool_surface: 'unverified' }));
		const target = await render();
		expect(target.querySelector('.unverified-banner')?.textContent).toBe(
			COWRITER_CLAUDE_UNVERIFIED_LABEL
		);
		expect(target.querySelector('.unavailable-banner')).toBeNull();

		await sendTurn(target, 'write a chorus');
		await vi.waitFor(() => expect(streamCoWriterTurn).toHaveBeenCalledTimes(1));
	});

	it('stays available when the tool surface is ok', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ claude_cli_tool_surface: 'ok' }));
		const target = await render();
		expect(target.querySelector('.unavailable-banner')).toBeNull();
		expect(target.querySelector('.unverified-banner')).toBeNull();
	});

	it('gives Grok no pre-emptive signal — it keeps the reactive 503 path', async () => {
		fetchCowriterSettings.mockResolvedValue({ provider: 'grok', model: 'grok-4' });
		fetchHealth.mockResolvedValue(makeHealthResponse({ claude_cli_tool_surface: 'drift' }));
		const target = await render();
		expect(target.querySelector('.unavailable-banner')).toBeNull();
		const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
		if (!input) throw new Error('Expected the chat textarea');
		input.value = 'write a chorus';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(target.querySelector<HTMLButtonElement>('.send-btn')?.disabled).toBe(false);
	});
});

describe('CoWriterPanel failed turns', () => {
	it('names a server error frame below the retained user message', async () => {
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{
					type: 'error',
					status: 503,
					reason: { message: 'Selected route failed.' }
				}
			])
		);
		const target = await render();

		await sendTurn(target, 'write a chorus');

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'Selected route failed.'
			)
		);
		expect(target.querySelector('.typing')).toBeNull();
		expect(target.querySelectorAll('.message.user')).toHaveLength(1);
		expect(target.querySelector<HTMLButtonElement>('.retry-turn')?.textContent).toBe('Try again');
	});

	it('offers Try again only on the newest message once a newer one failed too', async () => {
		streamCoWriterTurn.mockImplementation(() =>
			turnEvents([{ type: 'error', message: 'Selected route failed.' } as CoWriterStreamEvent])
		);
		const target = await render();

		await sendTurn(target, 'older message');
		await vi.waitFor(() => expect(target.querySelector('.retry-turn')).not.toBeNull());
		await sendTurn(target, 'newer message');
		await vi.waitFor(() => expect(streamCoWriterTurn).toHaveBeenCalledTimes(2));
		await vi.waitFor(() => expect(target.querySelector('.typing')).toBeNull());

		const retries = target.querySelectorAll<HTMLButtonElement>('.retry-turn');
		expect(retries).toHaveLength(1);
		expect(retries[0].closest('.message')?.textContent).toContain('newer message');
	});

	it.each(droppedStreams)(
		'names %s whose message never reached the server, with a retry',
		async (_shape, droppedStream) => {
			streamCoWriterTurn.mockReturnValue(droppedStream());
			const target = await render();

			await sendTurn(target, 'write a chorus');

			await vi.waitFor(() =>
				expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
					'The co-writer did not answer. Try again.'
				)
			);
			expect(target.querySelector('.typing')).toBeNull();
			expect(target.querySelectorAll('.message.user')).toHaveLength(1);
			expect(target.querySelector<HTMLButtonElement>('.retry-turn')).not.toBeNull();
		}
	);

	it('names a 503 below the user message, ends typing, and retries the retained message', async () => {
		streamCoWriterTurn.mockReturnValueOnce(
			(async function* () {
				yield* [];
				throw new ApiError(503, 'Codex CLI is temporarily unavailable', '/api/chat/turn');
			})()
		);
		streamCoWriterTurn.mockReturnValueOnce(
			turnEvents([
				{
					type: 'final',
					conversation_id: 'c1',
					user_message: {
						id: 'u1',
						role: 'user',
						content: 'write a chorus',
						created_at: '2026-01-01T00:00:00+00:00'
					},
					assistant_message: {
						id: 'a1',
						role: 'assistant',
						content: 'Here is a chorus',
						created_at: '2026-01-01T00:00:00+00:00'
					}
				}
			])
		);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		conversationPages(
			conversation(false),
			conversation(
				false,
				chatMessage('u1', 'user', 'write a chorus'),
				chatMessage('a1', 'assistant', 'Here is a chorus')
			)
		);
		const target = await render();

		await sendTurn(target, 'write a chorus');

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'Codex CLI is temporarily unavailable'
			)
		);
		expect(target.querySelector('.typing')).toBeNull();
		expect(target.querySelectorAll('.message.user')).toHaveLength(1);
		expect(target.querySelector<HTMLButtonElement>('.retry-turn')?.textContent).toBe('Try again');

		target.querySelector<HTMLButtonElement>('.retry-turn')?.click();

		await vi.waitFor(() => expect(streamCoWriterTurn).toHaveBeenCalledTimes(2));
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(2));
		await vi.waitFor(() =>
			expect(chatView(target)).toEqual(['write a chorus', 'Here is a chorus'])
		);
	});
});

describe('CoWriterPanel returning while a turn runs (#1014)', () => {
	const sent = chatMessage('u1', 'user', 'Ja bitte');
	const reply = chatMessage('a1', 'assistant', 'Erledigt.');

	async function leaveDuringATurnAndReturn(onturncompleted = vi.fn()): Promise<HTMLElement> {
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				yield { type: 'assistant_text', text: 'Mach ich' } as CoWriterStreamEvent;
				await new Promise(() => {});
			})()
		);
		const left = await render();
		await sendTurn(left, 'Ja bitte');
		await vi.waitFor(() => expect(left.textContent).toContain('Mach ich'));
		const leftPanel = mounted.pop();
		if (!leftPanel) throw new Error('Expected the panel the musician left');
		await unmount(leftPanel);

		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		return render({ onturncompleted });
	}

	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'Date'] });
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('shows the message sent at once and the reply as soon as the turn completes', async () => {
		conversationPages(
			conversation(true, sent),
			conversation(true, sent),
			conversation(false, sent, reply)
		);
		const onturncompleted = vi.fn();

		const target = await leaveDuringATurnAndReturn(onturncompleted);

		await vi.waitFor(() =>
			expect(target.querySelector('.message.user')?.textContent).toContain('Ja bitte')
		);
		expect(target.querySelector('.typing')).not.toBeNull();

		await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);
		expect(target.textContent).not.toContain('Erledigt.');

		await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);
		await vi.waitFor(() =>
			expect(target.querySelector('.message.assistant')?.textContent).toContain('Erledigt.')
		);
		expect(target.querySelector('.typing')).toBeNull();
		expect(target.querySelector('.turn-error')).toBeNull();
		expect(onturncompleted).toHaveBeenCalledTimes(1);
	});

	it('names a turn that ended unanswered below the retained message, with a retry', async () => {
		conversationPages(conversation(true, sent), conversation(false, sent));

		const target = await leaveDuringATurnAndReturn();
		await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'The co-writer did not answer. Try again.'
			)
		);
		expect(target.querySelector('.message.user')?.textContent).toContain('Ja bitte');
		expect(target.querySelector('.typing')).toBeNull();
		expect(target.querySelector<HTMLButtonElement>('.retry-turn')).not.toBeNull();
	});

	it('shows the retained unanswered message once when retrying it fails again', async () => {
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		fetchConversationMessages.mockResolvedValue(conversation(false, sent));
		streamCoWriterTurn.mockReturnValue(
			turnEvents([{ type: 'error', message: 'CLI is unavailable.' } as CoWriterStreamEvent])
		);
		const target = await render();
		await vi.waitFor(() => expect(target.querySelector('.retry-turn')).not.toBeNull());

		target.querySelector<HTMLButtonElement>('.retry-turn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'CLI is unavailable.'
			)
		);
		expect(target.querySelectorAll('.message.user')).toHaveLength(1);
		expect(target.querySelectorAll('.retry-turn')).toHaveLength(1);
	});

	it('names a conversation it can no longer reach instead of waiting in silence', async () => {
		conversationPages(conversation(true, sent));
		fetchConversationMessages.mockRejectedValue(new Error('Failed to fetch'));

		const target = await leaveDuringATurnAndReturn();
		await vi.advanceTimersByTimeAsync(
			COWRITER_RUNNING_TURN_POLL_MS * COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT
		);

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.history-error')?.textContent).toContain(
				'Conversation history unavailable'
			)
		);
		expect(target.querySelector('.typing')).toBeNull();
	});

	async function sendInAnOpenConversation(onturncompleted = vi.fn()): Promise<HTMLElement> {
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const target = await render({ onturncompleted });
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));
		await sendTurn(target, 'Ja bitte');
		return target;
	}

	it.each(droppedStreams)(
		'follows the turn the server still runs after %s, then shows its reply',
		async (_shape, droppedStream) => {
			streamCoWriterTurn.mockReturnValue(droppedStream());
			conversationPages(
				conversation(false),
				conversation(true, sent),
				conversation(false, sent, reply)
			);
			const onturncompleted = vi.fn();

			const target = await sendInAnOpenConversation(onturncompleted);

			await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(2));
			await vi.waitFor(() => expect(target.querySelector('.typing')).not.toBeNull());
			expect(target.querySelector('.turn-error')).toBeNull();
			expect(target.querySelector('.message.user')?.textContent).toContain('Ja bitte');

			await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);
			await vi.waitFor(() =>
				expect(target.querySelector('.message.assistant')?.textContent).toContain('Erledigt.')
			);
			expect(target.querySelector('.typing')).toBeNull();
			expect(target.querySelector('.turn-error')).toBeNull();
			expect(target.querySelectorAll('.message.user')).toHaveLength(1);
			expect(streamCoWriterTurn).toHaveBeenCalledTimes(1);
			expect(onturncompleted).toHaveBeenCalledTimes(1);
		}
	);

	it.each(droppedStreams)(
		'names %s whose repeated message never reached the server, with a retry',
		async (_shape, droppedStream) => {
			streamCoWriterTurn.mockReturnValue(droppedStream());
			conversationPages(conversation(false, sent, reply), conversation(false, sent, reply));
			const onturncompleted = vi.fn();

			const target = await sendInAnOpenConversation(onturncompleted);

			await vi.waitFor(() =>
				expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
					'The co-writer did not answer. Try again.'
				)
			);
			expect(target.querySelectorAll('.message.user')).toHaveLength(2);
			expect(target.querySelector<HTMLButtonElement>('.retry-turn')).not.toBeNull();
			expect(onturncompleted).not.toHaveBeenCalled();
		}
	);

	it('names a repeated message that never reached the server after a streamed exchange', async () => {
		streamCoWriterTurn.mockReturnValueOnce(
			turnEvents([
				{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
			])
		);
		streamCoWriterTurn.mockReturnValueOnce(droppedStreams[2][1]());
		const target = await render();
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		conversationPages(conversation(false, sent, reply), conversation(false, sent, reply));
		await sendTurn(target, 'Ja bitte');
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));
		await vi.waitFor(() => expect(target.textContent).toContain('Erledigt.'));

		await sendTurn(target, 'Ja bitte');

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'The co-writer did not answer. Try again.'
			)
		);
		expect(target.querySelectorAll('.message.user')).toHaveLength(2);
	});

	it('shows the reply of a turn that finished while its stream was down', async () => {
		streamCoWriterTurn.mockReturnValue(droppedStreams[2][1]());
		conversationPages(conversation(false), conversation(false, sent, reply));
		const onturncompleted = vi.fn();

		const target = await sendInAnOpenConversation(onturncompleted);

		await vi.waitFor(() =>
			expect(target.querySelector('.message.assistant')?.textContent).toContain('Erledigt.')
		);
		expect(target.querySelector('.turn-error')).toBeNull();
		expect(target.querySelector('.typing')).toBeNull();
		expect(onturncompleted).toHaveBeenCalledTimes(1);
	});

	it('keeps an older failed message once a newer one is answered, as a reload shows it', async () => {
		const failed = chatMessage('u0', 'user', 'Refrain kürzer');
		const persisted = conversation(false, failed, sent, reply);
		streamCoWriterTurn
			.mockReturnValueOnce(
				turnEvents([{ type: 'error', message: 'Selected route failed.' } as CoWriterStreamEvent])
			)
			.mockReturnValueOnce(
				turnEvents([
					{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
				])
			);
		conversationPages(conversation(false), persisted, persisted);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const live = await render();
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));

		await sendTurn(live, 'Refrain kürzer');
		await vi.waitFor(() => expect(live.querySelector('.retry-turn')).not.toBeNull());
		await sendTurn(live, 'Ja bitte');

		const expected = ['Refrain kürzer', 'Ja bitte', 'Erledigt.'];
		await vi.waitFor(() => expect(chatView(live)).toEqual(expected));
		const reloaded = await render();
		await vi.waitFor(() => expect(chatView(reloaded)).toEqual(expected));
		expect(live.querySelector('.retry-turn')).toBeNull();
	});

	it('follows a turn another tab is running and keeps what was typed', async () => {
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				yield* [] as CoWriterStreamEvent[];
				throw new ApiError(409, 'A co-writer reply is still being written', '/api/chat/turn');
			})()
		);
		const otherTab = chatMessage('u0', 'user', 'Refrain kürzer');
		conversationPages(
			conversation(false),
			conversation(true, otherTab),
			conversation(false, otherTab, reply)
		);

		const target = await sendInAnOpenConversation();

		await vi.waitFor(() =>
			expect(target.querySelector('.message.user')?.textContent).toContain('Refrain kürzer')
		);
		await vi.waitFor(() => expect(target.querySelector('.typing')).not.toBeNull());
		expect(target.querySelector<HTMLTextAreaElement>('.chat-input')?.value).toBe('Ja bitte');
		expect(target.querySelector('.turn-error')).toBeNull();

		await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);
		await vi.waitFor(() =>
			expect(target.querySelector('.message.assistant')?.textContent).toContain('Erledigt.')
		);
		expect(target.textContent).not.toContain('Ja bitte');
	});

	it('does not offer a message again that the running turn is already answering', async () => {
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				yield* [] as CoWriterStreamEvent[];
				throw new ApiError(409, 'A co-writer reply is still being written', '/api/chat/turn');
			})()
		);
		conversationPages(conversation(false), conversation(true, sent));

		const target = await sendInAnOpenConversation();

		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(2));
		await vi.waitFor(() => expect(target.querySelector('.typing')).not.toBeNull());
		expect(target.querySelectorAll('.message.user')).toHaveLength(1);
		expect(target.querySelector<HTMLTextAreaElement>('.chat-input')?.value).toBe('');
	});

	it('shows a message whose turn no longer runs as unanswered, without waiting for it', async () => {
		conversationPages(conversation(false, sent));
		fetchConversations.mockResolvedValue([activeConversation('c1')]);

		const target = await render();

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'The co-writer did not answer. Try again.'
			)
		);
		expect(target.querySelector('.typing')).toBeNull();
		streamCoWriterTurn.mockReturnValue(turnEvents([]));
		await sendTurn(target, 'Noch einmal');
		expect(streamCoWriterTurn).toHaveBeenCalledWith(
			expect.objectContaining({ message: 'Noch einmal' })
		);
	});
});

describe('CoWriterPanel proposal target (#238)', () => {
	beforeEach(() => {
		conversationPages(
			conversation(false),
			conversation(
				false,
				chatMessage('u1', 'user', 'the request'),
				chatMessage('a1', 'assistant', 'Done')
			)
		);
	});

	// The co-writer is one global conversation: a tool call streamed while
	// "Open Song" is showing can still target a different song entirely.
	it('badges a proposal for a different song than the one currently open', async () => {
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{
					type: 'tool_call',
					tool_use_id: 't1',
					name: 'update_song_lyrics',
					input: { song_id: 's2', lyrics: 'new verse' }
				},
				{
					type: 'final',
					conversation_id: 'c1',
					user_message: {
						id: 'u1',
						role: 'user',
						content: 'update the other song',
						created_at: '2026-01-01T00:00:00+00:00'
					},
					assistant_message: {
						id: 'a1',
						role: 'assistant',
						content: 'Done',
						created_at: '2026-01-01T00:00:00+00:00'
					}
				}
			])
		);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const target = await render({
			allSongs: [
				song({ slug: 'open-song', title: 'Open Song', generation_count: 0 }),
				song({ slug: 'open-song', generation_count: 0, id: 's2', title: 'Other Song' })
			]
		});

		await sendMessage(target, 'update the other song');

		const badge = target.querySelector<HTMLElement>('.tool-target');
		expect(badge?.textContent?.trim()).toBe('for: Other Song');
		expect(badge?.classList.contains('foreign')).toBe(true);
	});

	it('shows the same target without the foreign warning styling when the proposal targets the open song', async () => {
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{
					type: 'tool_call',
					tool_use_id: 't1',
					name: 'update_song_prompt',
					input: { song_id: 's1', prompt: 'darker' }
				},
				{
					type: 'final',
					conversation_id: 'c1',
					user_message: {
						id: 'u1',
						role: 'user',
						content: 'darken it',
						created_at: '2026-01-01T00:00:00+00:00'
					},
					assistant_message: {
						id: 'a1',
						role: 'assistant',
						content: 'Done',
						created_at: '2026-01-01T00:00:00+00:00'
					}
				}
			])
		);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const target = await render({
			allSongs: [song({ slug: 'open-song', title: 'Open Song', generation_count: 0 })]
		});

		await sendMessage(target, 'darken it');

		const badge = target.querySelector<HTMLElement>('.tool-target');
		expect(badge?.textContent?.trim()).toBe('for: Open Song');
		expect(badge?.classList.contains('foreign')).toBe(false);
	});

	it('does not badge read-only tool calls that have no song target', async () => {
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{
					type: 'tool_call',
					tool_use_id: 't1',
					name: 'list_songs',
					input: {}
				},
				{
					type: 'final',
					conversation_id: 'c1',
					user_message: {
						id: 'u1',
						role: 'user',
						content: 'what songs do I have?',
						created_at: '2026-01-01T00:00:00+00:00'
					},
					assistant_message: {
						id: 'a1',
						role: 'assistant',
						content: 'Here they are',
						created_at: '2026-01-01T00:00:00+00:00'
					}
				}
			])
		);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const target = await render();

		await sendMessage(target, 'what songs do I have?');

		expect(target.querySelector('.tool-target')).toBeNull();
	});

	it("keeps an earlier reply's proposal target after the next turn is answered", async () => {
		const answered = (userId: string, assistantId: string): CoWriterStreamEvent => ({
			type: 'final',
			conversation_id: 'c1',
			user_message: chatMessage(userId, 'user', 'request'),
			assistant_message: chatMessage(assistantId, 'assistant', 'Done')
		});
		streamCoWriterTurn
			.mockReturnValueOnce(
				turnEvents([
					{
						type: 'tool_call',
						tool_use_id: 't1',
						name: 'update_song_lyrics',
						input: { song_id: 's2', lyrics: 'new verse' }
					},
					answered('u1', 'a1')
				])
			)
			.mockReturnValueOnce(turnEvents([answered('u2', 'a2')]));
		conversationPages(
			conversation(
				false,
				chatMessage('u1', 'user', 'the request'),
				chatMessage('a1', 'assistant', 'Done'),
				chatMessage('u2', 'user', 'thanks'),
				chatMessage('a2', 'assistant', 'Done')
			)
		);
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		const target = await render({
			allSongs: [
				song({ slug: 'open-song', title: 'Open Song', generation_count: 0 }),
				song({ slug: 'open-song', generation_count: 0, id: 's2', title: 'Other Song' })
			]
		});
		await sendMessage(target, 'update the other song');

		await sendTurn(target, 'thanks');
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(3));
		await tick();
		expect(chatView(target)).toHaveLength(4);

		const badge = target.querySelector<HTMLElement>('.tool-target');
		expect(badge?.textContent?.trim()).toBe('for: Other Song');
		expect(badge?.classList.contains('foreign')).toBe(true);
	});
});
