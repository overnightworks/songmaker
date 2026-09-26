import { makeHealthResponse, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoWriterStreamEvent } from '$lib/api/client';
import type { ChatMessageItem } from '$lib/api/types';
import { COWRITER_CLAUDE_UNVERIFIED_LABEL, COWRITER_RUNNING_TURN_POLL_MS } from '$lib/constants';

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
import { startNewConversation } from '$lib/api/client';
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
	await vi.waitFor(() => expect(target.querySelector('.tool-call')).not.toBeNull());
	await tick();
}

async function sendTurn(target: HTMLElement, message: string): Promise<void> {
	const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
	if (!input) throw new Error('Expected the chat textarea');
	input.value = message;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	target.querySelector<HTMLButtonElement>('.send-btn')?.click();
}

describe('CoWriterPanel', () => {
	it('renders without a Close button (its lifecycle is owned by the Editor header toggle)', async () => {
		const target = await render();
		expect(target.querySelector('.close-btn')).toBeNull();
		expect(target.querySelector('.new-btn')).not.toBeNull();
	});

	it('starts a new conversation from the header action', async () => {
		const target = await render();
		target.querySelector<HTMLButtonElement>('.new-btn')?.click();
		await tick();
		expect(startNewConversation).toHaveBeenCalledTimes(1);
	});

	it('has no left border now that it fills the Write column instead of a side panel', async () => {
		const target = await render();
		const root = target.querySelector('.cowriter');
		expect(root).not.toBeNull();
		expect(getComputedStyle(root as Element).borderLeftWidth).not.toBe('1px');
	});

	it('renders no back control of its own — the phone push screen uses the shell app bar', async () => {
		const target = await render();
		expect(target.querySelector('.cowriter-back')).toBeNull();
		expect(target.querySelector('.cowriter-header.app-bar')).toBeNull();
	});
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
				'claude is currently unavailable'
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

	it('names a stream that ends before its final event', async () => {
		streamCoWriterTurn.mockReturnValue(turnEvents([]));
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
	});

	it('names a timed out stream below the retained user message', async () => {
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				yield* [] as CoWriterStreamEvent[];
				throw Object.assign(new Error('aborted'), { name: 'AbortError' });
			})()
		);
		const target = await render();

		await sendTurn(target, 'write a chorus');

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLElement>('.turn-error')?.textContent).toContain(
				'The co-writer did not answer. Try again.'
			)
		);
		expect(target.querySelectorAll('.message.user')).toHaveLength(1);
	});

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
		await vi.waitFor(() => expect(target.querySelector('.turn-error')).toBeNull());
		expect(target.textContent).toContain('Here is a chorus');
	});
});

describe('CoWriterPanel returning while a turn runs (#1014)', () => {
	function chatMessage(id: string, role: 'user' | 'assistant', content: string): ChatMessageItem {
		return { id, role, content, created_at: '2026-09-26T15:21:00+00:00' };
	}

	const sent = chatMessage('u1', 'user', 'Ja bitte');
	const reply = chatMessage('a1', 'assistant', 'Erledigt.');

	function conversation(turnRunning: boolean, ...messages: ChatMessageItem[]) {
		return {
			conversation_id: 'c1',
			title: null,
			archived_at: null,
			messages,
			turn_running: turnRunning
		};
	}

	function conversationPages(...pages: ReturnType<typeof conversation>[]): void {
		for (const page of pages) fetchConversationMessages.mockResolvedValueOnce(page);
	}

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
});
