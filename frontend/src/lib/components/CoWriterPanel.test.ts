import { makeHealthResponse, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoWriterStreamEvent } from '$lib/api/client';
import type { ChatMessageItem } from '$lib/api/types';
import {
	COWRITER_CLAUDE_UNVERIFIED_LABEL,
	COWRITER_CONVERSATION_MENU_LABEL,
	COWRITER_DELETE_CONVERSATION_TITLE,
	COWRITER_DELETE_CONVERSATION_WARNING,
	COWRITER_MEMORY_LABEL,
	COWRITER_MEMORY_PROPOSAL_WAITING_LABEL,
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
		saveUserMemory: vi.fn(async (body: string) => ({
			scope: 'user',
			target_id: 'u1',
			body
		})),
		fetchCowriterSettings: (...args: Parameters<typeof fetchCowriterSettings>) =>
			fetchCowriterSettings(...args),
		fetchHealth: (...args: Parameters<typeof fetchHealth>) => fetchHealth(...args),
		streamCoWriterTurn: (...args: Parameters<typeof streamCoWriterTurn>) =>
			streamCoWriterTurn(...args)
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';
import { describeBackClosesOverlay } from '$lib/test-utils/library-history';
import {
	deleteConversation,
	fetchMemory,
	saveUserMemory,
	startNewConversation
} from '$lib/api/client';
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
	target.querySelector<HTMLButtonElement>('button.convo-menu-btn')?.click();
	await tick();
	const menu = target.querySelector<HTMLElement>('[role="menu"]');
	if (!menu) throw new Error('Expected the conversation menu');
	return menu;
}

async function openMemoryFromMenu(target: HTMLElement): Promise<void> {
	const menu = await openConversationMenu(target);
	Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
		.find((item) => item.textContent?.trim() === 'Memory')
		?.click();
	await tick();
}

function userMemoryField(target: HTMLElement): HTMLTextAreaElement | null {
	return target.querySelector<HTMLTextAreaElement>('textarea[aria-label="User memory"]');
}

function focusedConversationMenuTrigger(): boolean {
	return document.activeElement?.getAttribute('aria-label') === COWRITER_CONVERSATION_MENU_LABEL;
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
		const empty = { ...activeConversation('c2'), message_count: 0 };
		fetchConversations.mockResolvedValue([
			empty,
			conversationStartedAt('2026-09-22T10:00:00'),
			older
		]);
		const target = await render();

		const menu = await openConversationMenu(target);

		expect(Array.from(menu.querySelectorAll('.conv-title'), (title) => title.textContent)).toEqual([
			'New conversation',
			'Conversation since Tue 10:00',
			'Archived · Sep 17 10:00'
		]);
		expect(menu.querySelector('.conv-meta')?.textContent?.trim()).toBe('0 msgs');
	});

	describe('with two conversations started the same day', () => {
		const archivedThisMorning = {
			...activeConversation('c0'),
			created_at: '2026-09-27T07:30:00',
			archived_at: '2026-09-27T09:12:00'
		};
		const runningSinceNine = { ...conversationStartedAt('2026-09-27T09:12:00'), message_count: 4 };

		function rowNames(menu: HTMLElement): Array<string | null> {
			return Array.from(menu.querySelectorAll('.conv-title'), (title) => title.textContent);
		}

		it('tells them apart and keeps the active one first after the list is read again', async () => {
			const sent = chatMessage('m5', 'user', 'now a bridge');
			const reply = chatMessage('m6', 'assistant', 'Four lines.');
			fetchConversations.mockResolvedValue([archivedThisMorning, runningSinceNine]);
			streamCoWriterTurn.mockReturnValue(
				turnEvents([
					{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
				])
			);
			const target = await render();
			await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));
			const firstOpening = rowNames(await openConversationMenu(target));
			target.querySelector<HTMLButtonElement>('button.convo-menu-btn')?.click();
			await tick();

			fetchConversations.mockResolvedValue([
				{ ...archivedThisMorning, updated_at: '2026-09-27T11:00:00' },
				{ ...runningSinceNine, message_count: 6 }
			]);
			fetchConversationMessages.mockResolvedValue(conversation(false, sent, reply));
			await sendTurn(target, sent.content);
			await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalledTimes(2));

			expect(firstOpening).toEqual(['Conversation since today 09:12', 'Archived · today 07:30']);
			expect(rowNames(await openConversationMenu(target))).toEqual(firstOpening);
		});

		it('names the conversation whose ✕ was tapped in the delete confirm', async () => {
			fetchConversations.mockResolvedValue([runningSinceNine, archivedThisMorning]);
			const target = await render();
			await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
			const menu = await openConversationMenu(target);

			menu
				.querySelectorAll<HTMLButtonElement>('button[aria-label="Delete conversation"]')[1]
				.click();
			await tick();

			expect(document.querySelector('[role="dialog"] li')?.textContent).toBe(
				'Archived · today 07:30 · 2 msgs'
			);
		});
	});

	it('reads “conversation since today” once the first message is sent, before the reply arrives', async () => {
		let deliverReply = (): void => {};
		const replyDelivered = new Promise<void>((resolve) => {
			deliverReply = resolve;
		});
		const ask = chatMessage('m1', 'user', 'write a chorus');
		const answer = chatMessage('m2', 'assistant', 'Here it is.');
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				await replyDelivered;
				yield {
					type: 'final',
					conversation_id: 'c1',
					user_message: ask,
					assistant_message: answer
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
		fetchConversationMessages.mockResolvedValue(conversation(false, ask, answer));
		deliverReply();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalledTimes(2));
		expect(conversationLine(target)).toBe('Claude · conversation since today');
	});

	it('counts an earlier failed message the server stored once the answered turn is read back', async () => {
		const failed = chatMessage('m1', 'user', 'write a verse');
		const sent = chatMessage('m2', 'user', 'now a bridge');
		const reply = chatMessage('m3', 'assistant', 'Four lines.');
		fetchConversations
			.mockResolvedValueOnce([conversationStartedAt('2026-09-22T10:00:00')])
			.mockReturnValue(new Promise(() => {}));
		conversationPages(conversation(false), conversation(false, failed, sent, reply));
		streamCoWriterTurn
			.mockReturnValueOnce(
				turnEvents([{ type: 'error', message: 'CLI is unavailable.' } as CoWriterStreamEvent])
			)
			.mockReturnValue(
				turnEvents([
					{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
				])
			);
		const target = await render();
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(1));
		await sendTurn(target, failed.content);
		await vi.waitFor(() => expect(target.querySelector('.turn-error')).not.toBeNull());

		await sendTurn(target, sent.content);
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(2));
		await vi.waitFor(() => expect(target.querySelector('.turn-error')).toBeNull());
		const menu = await openConversationMenu(target);

		expect(menu.querySelector('.conv-meta')?.textContent?.trim()).toBe('3 msgs');
	});

	it('shows the current message count in its ⋯ menu as soon as the reply is in', async () => {
		const earlier = [
			chatMessage('m1', 'user', 'write a verse'),
			chatMessage('m2', 'assistant', 'Here it is.')
		];
		const sent = chatMessage('m3', 'user', 'now a bridge');
		const reply = chatMessage('m4', 'assistant', 'Four lines.');
		fetchConversations
			.mockResolvedValueOnce([conversationStartedAt('2026-09-22T10:00:00')])
			.mockReturnValue(new Promise(() => {}));
		conversationPages(
			conversation(false, ...earlier),
			conversation(false, ...earlier, sent, reply)
		);
		streamCoWriterTurn.mockReturnValue(
			turnEvents([
				{ type: 'final', conversation_id: 'c1', user_message: sent, assistant_message: reply }
			])
		);
		const target = await render();
		await vi.waitFor(() => expect(target.textContent).toContain('Here it is.'));

		await sendTurn(target, sent.content);
		await vi.waitFor(() => expect(target.textContent).toContain('Four lines.'));
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

	it('keeps Memory in its ⋯ menu rather than a row above the chat, moves focus into the memory editor it opens, and returns focus to ⋯ on close', async () => {
		vi.mocked(fetchMemory).mockResolvedValueOnce({
			user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' }
		});
		const target = await render();
		expect(
			Array.from(target.querySelectorAll('button'), (button) => button.textContent?.trim())
		).not.toContainEqual(expect.stringMatching(/^Memory/));

		await openMemoryFromMenu(target);

		expect(target.querySelector('[role="menu"]')).toBeNull();
		await vi.waitFor(() => expect(userMemoryField(target)?.value).toBe('Prefers short lines'));
		expect(
			target.querySelector('section[aria-label="Memory"]')?.contains(document.activeElement)
		).toBe(true);

		target.querySelector<HTMLButtonElement>('button[aria-label="Close memory"]')?.click();
		await tick();
		expect(userMemoryField(target)).toBeNull();
		expect(focusedConversationMenuTrigger()).toBe(true);
	});

	it('closes Memory on Escape from inside the editor without leaving the song', async () => {
		vi.mocked(fetchMemory).mockResolvedValueOnce({
			user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' }
		});
		const target = await render();
		await openMemoryFromMenu(target);
		await vi.waitFor(() => expect(userMemoryField(target)).not.toBeNull());
		userMemoryField(target)?.focus();
		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });

		userMemoryField(target)?.dispatchEvent(escape);
		await tick();

		expect(userMemoryField(target)).toBeNull();
		expect(escape.defaultPrevented).toBe(true);
		expect(focusedConversationMenuTrigger()).toBe(true);
	});

	async function renderWithOneWaitingProposal(): Promise<HTMLElement> {
		vi.mocked(fetchMemory).mockResolvedValue({
			user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' }
		});
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		fetchConversationMessages.mockResolvedValue(
			conversation(
				false,
				chatMessage('m1', 'user', 'remember that I hate rhymes'),
				chatMessage(
					'm2',
					'assistant',
					'Noted. <memory_proposal scope="user"><current>Prefers short lines</current>' +
						'<proposed>Prefers short lines, no rhymes</proposed></memory_proposal>'
				)
			)
		);
		return render();
	}

	it.each(['accept', 'reject'])(
		'keeps focus in Memory after %s answers the last proposal, so Escape closes Memory without leaving the song',
		async (answer) => {
			const target = await renderWithOneWaitingProposal();
			await openMemoryFromMenu(target);
			await vi.waitFor(() => expect(target.querySelector(`.proposal .${answer}`)).not.toBeNull());
			const answerButton = target.querySelector<HTMLButtonElement>(`.proposal .${answer}`);
			answerButton?.focus();
			answerButton?.click();
			await vi.waitFor(() => expect(target.querySelector('.proposal')).toBeNull());
			await tick();

			const memory = target.querySelector('section[aria-label="Memory"]');
			expect(memory?.contains(document.activeElement)).toBe(true);
			const escape = new KeyboardEvent('keydown', {
				key: 'Escape',
				bubbles: true,
				cancelable: true
			});
			document.activeElement?.dispatchEvent(escape);
			await tick();

			expect(target.querySelector('section[aria-label="Memory"]')).toBeNull();
			expect(escape.defaultPrevented).toBe(true);
			expect(focusedConversationMenuTrigger()).toBe(true);
		}
	);

	it('keeps focus where the musician moved it while a slow answer to a proposal completes', async () => {
		let finishSave: () => void = () => {};
		vi.mocked(saveUserMemory).mockImplementationOnce(
			(body: string) =>
				new Promise((resolve) => {
					finishSave = () => resolve({ scope: 'user', target_id: 'u1', body });
				})
		);
		const target = await renderWithOneWaitingProposal();
		await openMemoryFromMenu(target);
		await vi.waitFor(() => expect(target.querySelector('.proposal .accept')).not.toBeNull());
		target.querySelector<HTMLButtonElement>('.proposal .accept')?.click();
		await tick();

		const composer = target.querySelector<HTMLTextAreaElement>('.chat-input');
		composer?.focus();
		finishSave();
		await vi.waitFor(() => expect(target.querySelector('.proposal')).toBeNull());
		await tick();

		expect(composer).not.toBeNull();
		expect(document.activeElement).toBe(composer);
	});

	it('marks ⋯ and its Memory item while a memory proposal waits, and says so in their names until it is answered', async () => {
		const target = await renderWithOneWaitingProposal();
		const trigger = target.querySelector<HTMLButtonElement>('button.convo-menu-btn');
		const waitingName = (label: string) =>
			`${label}, ${COWRITER_MEMORY_PROPOSAL_WAITING_LABEL.toLowerCase()}`;

		await vi.waitFor(() =>
			expect(trigger?.getAttribute('aria-label')).toBe(
				waitingName(COWRITER_CONVERSATION_MENU_LABEL)
			)
		);
		expect(trigger?.querySelectorAll('.proposal-waiting')).toHaveLength(1);
		const menu = await openConversationMenu(target);
		const memoryItem = menu.querySelector<HTMLButtonElement>('.convo-memory');
		expect(memoryItem?.getAttribute('aria-label')).toBe(waitingName(COWRITER_MEMORY_LABEL));
		expect(memoryItem?.querySelector('.proposal-waiting')).not.toBeNull();

		memoryItem?.click();
		await tick();
		await vi.waitFor(() => expect(target.querySelector('.proposal .reject')).not.toBeNull());
		target.querySelector<HTMLButtonElement>('.proposal .reject')?.click();
		await tick();

		expect(target.querySelectorAll('.proposal-waiting')).toHaveLength(0);
		expect(trigger?.getAttribute('aria-label')).toBe(COWRITER_CONVERSATION_MENU_LABEL);
	});

	it('shows the waiting proposal above the memory fields when Memory opens from its marked item', async () => {
		const target = await renderWithOneWaitingProposal();
		await vi.waitFor(() =>
			expect(target.querySelector('.convo-menu-btn .proposal-waiting')).not.toBeNull()
		);

		await openMemoryFromMenu(target);
		await vi.waitFor(() => expect(target.querySelector('.proposal')).not.toBeNull());

		const proposal = target.querySelector('.proposal');
		const firstField = target.querySelector('section[aria-label="Memory"] textarea');
		if (!proposal || !firstField) throw new Error('Expected the proposal and the memory fields');
		expect(
			proposal.compareDocumentPosition(firstField) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});
});

describe('CoWriterPanel deleting a conversation', () => {
	async function openDeleteConfirm(target: HTMLElement): Promise<HTMLElement> {
		const menu = await openConversationMenu(target);
		menu.querySelector<HTMLButtonElement>('button[aria-label="Delete conversation"]')?.click();
		await tick();
		const dialog = target.ownerDocument.querySelector<HTMLElement>('[role="dialog"]');
		if (!dialog) throw new Error('Expected the delete confirmation');
		return dialog;
	}

	function dialogButton(dialog: HTMLElement, label: string): HTMLButtonElement | undefined {
		return Array.from(dialog.querySelectorAll('button')).find(
			(button) => button.textContent?.trim() === label
		);
	}

	async function conversationRows(target: HTMLElement): Promise<number> {
		const menu = await openConversationMenu(target);
		return menu.querySelectorAll('.conv-row').length;
	}

	beforeEach(() => {
		fetchConversations.mockResolvedValue([activeConversation('c1')]);
		vi.mocked(deleteConversation).mockReset().mockResolvedValue(undefined);
	});

	it('asks “Delete conversation? This can’t be undone.” with Delete and Cancel before deleting', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());

		const dialog = await openDeleteConfirm(target);

		expect(dialog.querySelector('h3')?.textContent).toBe(COWRITER_DELETE_CONVERSATION_TITLE);
		expect(dialog.querySelector('.warning')?.textContent).toBe(
			COWRITER_DELETE_CONVERSATION_WARNING
		);
		expect(dialogButton(dialog, 'Delete')).toBeDefined();
		expect(dialogButton(dialog, 'Cancel')).toBeDefined();
		expect(deleteConversation).not.toHaveBeenCalled();
	});

	it('names the confirmation by its title for assistive technology', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());

		const dialog = await openDeleteConfirm(target);
		const labelId = dialog.getAttribute('aria-labelledby');

		expect(labelId).toBeTruthy();
		expect(document.getElementById(labelId ?? '')?.textContent).toBe(
			COWRITER_DELETE_CONVERSATION_TITLE
		);
	});

	it('keeps the conversation when Cancel answers the confirmation', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
		const dialog = await openDeleteConfirm(target);

		dialogButton(dialog, 'Cancel')?.click();
		await tick();

		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(deleteConversation).not.toHaveBeenCalled();
		expect(await conversationRows(target)).toBe(1);
	});

	it('keeps the conversation when Escape answers the confirmation, without leaving the song', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
		const dialog = await openDeleteConfirm(target);
		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });

		dialog.dispatchEvent(escape);
		await tick();

		expect(escape.defaultPrevented).toBe(true);
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(deleteConversation).not.toHaveBeenCalled();
		expect(await conversationRows(target)).toBe(1);
	});

	it('deletes the conversation only once Delete confirms it', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
		const dialog = await openDeleteConfirm(target);

		dialogButton(dialog, 'Delete')?.click();
		await vi.waitFor(() => expect(deleteConversation).toHaveBeenCalledWith('c1'));
		await tick();

		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(await conversationRows(target)).toBe(0);
	});

	it.each(['Cancel', 'Delete'])(
		'returns focus to ⋯ once %s answers the confirmation',
		async (answer) => {
			const target = await render();
			await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
			const dialog = await openDeleteConfirm(target);
			const answerButton = dialogButton(dialog, answer);

			answerButton?.focus();
			answerButton?.click();
			await tick();

			expect(document.querySelector('[role="dialog"]')).toBeNull();
			expect(focusedConversationMenuTrigger()).toBe(true);
		}
	);

	it('gives the delete ✕ the frequent touch target, 44px on a phone', async () => {
		const target = await render();
		await vi.waitFor(() => expect(fetchConversations).toHaveBeenCalled());
		const menu = await openConversationMenu(target);

		expect(
			menu.querySelector('button[aria-label="Delete conversation"]')?.getAttribute('data-hitbox')
		).toBe('frequent');
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
	it.each([
		[
			'the provider’s reason after its name',
			{ type: 'error', status: 503, reason: { message: 'CLI is unavailable.' } },
			'Claude: CLI is unavailable.'
		],
		[
			'the provider the server’s error frame names over the panel’s setting',
			{
				type: 'error',
				status: 503,
				provider: 'grok',
				route: 'api',
				reason: { message: 'Route is unavailable.' }
			},
			'Grok: Route is unavailable.'
		],
		[
			'the endpoint’s own failure after the panel’s provider',
			{ type: 'error', status: 500, message: 'Chat request failed' },
			'Claude: Chat request failed'
		]
	] as Array<[string, CoWriterStreamEvent, string]>)(
		'names %s below the retained user message',
		async (_case, frame, failure) => {
			streamCoWriterTurn.mockReturnValue(turnEvents([frame]));
			const target = await render();

			await sendTurn(target, 'write a chorus');

			await vi.waitFor(() =>
				expect(target.querySelector<HTMLElement>('.turn-error span')?.textContent).toBe(failure)
			);
			expect(target.querySelector('.typing')).toBeNull();
			expect(target.querySelectorAll('.message.user')).toHaveLength(1);
			expect(target.querySelector<HTMLButtonElement>('.retry-turn')?.textContent).toBe('Try again');
		}
	);

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

	const earlier = [
		chatMessage('u0', 'user', 'Strophe eins'),
		chatMessage('a0', 'assistant', 'Steht.')
	];

	/** The read that ends the turn: from then on the conversation list counts its reply too. */
	function turnEndsWith(page: ReturnType<typeof conversation>): void {
		fetchConversationMessages.mockImplementationOnce(async () => {
			fetchConversations.mockResolvedValue([
				{ ...activeConversation('c1'), message_count: page.messages.length }
			]);
			return page;
		});
	}

	const followedTurns: Array<[string, () => Promise<HTMLElement>]> = [
		[
			'a turn it returned to',
			() => {
				conversationPages(conversation(true, ...earlier, sent));
				turnEndsWith(conversation(false, ...earlier, sent, reply));
				return leaveDuringATurnAndReturn();
			}
		],
		[
			'a turn it followed after its stream dropped',
			() => {
				streamCoWriterTurn.mockReturnValue(droppedStreams[2][1]());
				conversationPages(conversation(false, ...earlier), conversation(true, ...earlier, sent));
				turnEndsWith(conversation(false, ...earlier, sent, reply));
				return sendInAnOpenConversation();
			}
		],
		[
			'a turn that finished while its stream was down',
			() => {
				streamCoWriterTurn.mockReturnValue(droppedStreams[2][1]());
				conversationPages(conversation(false, ...earlier));
				turnEndsWith(conversation(false, ...earlier, sent, reply));
				return sendInAnOpenConversation();
			}
		]
	];

	it.each(followedTurns)(
		'counts the reply of %s in its ⋯ menu once the turn ends',
		async (_shape, followTurn) => {
			const target = await followTurn();
			await vi.advanceTimersByTimeAsync(COWRITER_RUNNING_TURN_POLL_MS);
			await vi.waitFor(() => expect(target.textContent).toContain('Erledigt.'));

			const menu = await openConversationMenu(target);

			await vi.waitFor(() =>
				expect(menu.querySelector('.conv-meta')?.textContent?.trim()).toBe('4 msgs')
			);
		}
	);

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

describe('CoWriterPanel sending before the first history read arrives (#1170)', () => {
	const earlier = [
		chatMessage('u0', 'user', 'earlier'),
		chatMessage('a0', 'assistant', 'earlier reply')
	];
	const sent = chatMessage('u1', 'user', 'write a chorus');
	const reply = chatMessage('a1', 'assistant', 'Here is a chorus');

	const outcomes: Array<[string, () => AsyncGenerator<CoWriterStreamEvent>, unknown[]]> = [
		[
			'its answer',
			() =>
				turnEvents([
					{
						type: 'final',
						conversation_id: 'c1',
						user_message: sent,
						assistant_message: reply
					} as CoWriterStreamEvent
				]),
			['write a chorus', 'Here is a chorus']
		],
		[
			'its refusal',
			async function* () {
				yield* [] as CoWriterStreamEvent[];
				throw new ApiError(503, 'Codex CLI is temporarily unavailable', '/api/chat/turn');
			},
			[expect.stringMatching(/^write a chorus.*Codex CLI is temporarily unavailable/)]
		],
		[
			'its failed stream',
			() =>
				turnEvents([{ type: 'error', message: 'Selected route failed.' } as CoWriterStreamEvent]),
			[expect.stringMatching(/^write a chorus.*Selected route failed\./)]
		]
	];
	const lateReads: Array<[string, ChatMessageItem[]]> = [
		['the history before it', earlier],
		['a history that already stored it', [...earlier, sent]]
	];

	async function* endingWith(
		turn: AsyncGenerator<CoWriterStreamEvent>,
		onEnded: () => void
	): AsyncGenerator<CoWriterStreamEvent> {
		try {
			yield* turn;
		} finally {
			onEnded();
		}
	}

	const cases = outcomes.flatMap(([outcome, turn, exchange]) =>
		lateReads.map(([read, lateHistory]) => [outcome, read, turn, exchange, lateHistory] as const)
	);

	it.each(cases)(
		'keeps the sent message with %s once when the late read holds %s',
		async (_outcome, _read, turn, exchange, lateHistory) => {
			const firstRead = Promise.withResolvers<ReturnType<typeof conversation>>();
			fetchConversations.mockResolvedValue([activeConversation('c1')]);
			fetchConversationMessages
				.mockReturnValueOnce(firstRead.promise)
				.mockResolvedValueOnce(conversation(false, ...earlier, sent, reply));
			const turnEnded = Promise.withResolvers<undefined>();
			streamCoWriterTurn.mockReturnValue(endingWith(turn(), () => turnEnded.resolve(undefined)));
			const target = await render();

			await sendTurn(target, 'write a chorus');
			await turnEnded.promise;
			firstRead.resolve(conversation(false, ...lateHistory));

			await vi.waitFor(() =>
				expect(chatView(target)).toEqual(['earlier', 'earlier reply', ...exchange])
			);
		}
	);

	it('keeps an archived conversation out of the active one sent to while it still loads', async () => {
		const [, refused, refusedExchange] = outcomes[1];
		const archived = { ...activeConversation('c0'), archived_at: '2026-09-22T10:00:00' };
		const activeRead = Promise.withResolvers<ReturnType<typeof conversation>>();
		fetchConversations.mockResolvedValue([activeConversation('c1'), archived]);
		fetchConversationMessages
			.mockResolvedValueOnce(conversation(false, ...earlier))
			.mockResolvedValueOnce({
				...conversation(false, chatMessage('u9', 'user', 'archived question')),
				conversation_id: 'c0',
				archived_at: archived.archived_at
			})
			.mockReturnValueOnce(activeRead.promise);
		const turnEnded = Promise.withResolvers<undefined>();
		streamCoWriterTurn.mockReturnValue(endingWith(refused(), () => turnEnded.resolve(undefined)));
		const target = await render();
		await vi.waitFor(() => expect(chatView(target)).toEqual(['earlier', 'earlier reply']));

		(await openConversationMenu(target))
			.querySelectorAll<HTMLButtonElement>('.conv-pick')[1]
			.click();
		await vi.waitFor(() => expect(chatView(target)).toEqual(['archived question']));
		(await openConversationMenu(target))
			.querySelectorAll<HTMLButtonElement>('.conv-pick')[0]
			.click();
		await vi.waitFor(() => expect(fetchConversationMessages).toHaveBeenCalledTimes(3));

		await sendTurn(target, 'write a chorus');
		await turnEnded.promise;
		activeRead.resolve(conversation(false, ...earlier));

		await vi.waitFor(() =>
			expect(chatView(target)).toEqual(['earlier', 'earlier reply', ...refusedExchange])
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

function typeIntoChat(target: HTMLElement, text: string): void {
	const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
	if (!input) throw new Error('Expected the chat textarea');
	input.value = text;
	input.dispatchEvent(new Event('input', { bubbles: true }));
}

function pressEscapeIn(element: Element | null): void {
	element?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

describeBackClosesOverlay({
	name: 'the co-writer conversations menu',
	render: () => render(),
	open: (target) => target.querySelector<HTMLButtonElement>('button.convo-menu-btn')?.click(),
	isShown: (target) => target.querySelector('[role="menu"]') !== null,
	closeWays: [
		{ way: 'a tap outside', close: () => document.body.click() },
		{ way: 'Escape', close: () => pressEscapeIn(document.body) },
		{
			way: 'choosing Memory',
			close: (target) =>
				Array.from(target.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
					.find((item) => item.textContent?.trim() === 'Memory')
					?.click()
		}
	]
});

describeBackClosesOverlay({
	name: 'the @-mention list',
	render: () => render({ allSongs: [song({ id: 's2', slug: 'open-song', title: 'Open Song' })] }),
	open: (target) => typeIntoChat(target, '@Op'),
	isShown: (target) => target.querySelector('.mention-dropdown') !== null,
	closeWays: [
		{
			way: 'Escape',
			close: (target) => pressEscapeIn(target.querySelector('.chat-input'))
		},
		{
			way: 'choosing a song',
			close: (target) => target.querySelector<HTMLButtonElement>('.mention-option')?.click()
		},
		{ way: 'typing past the mention', close: (target) => typeIntoChat(target, 'plain words') }
	]
});
