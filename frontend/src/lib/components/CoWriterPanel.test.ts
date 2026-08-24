import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoWriterStreamEvent } from '$lib/api/client';
import type { SongItem } from '$lib/api/types';

const streamCoWriterTurn = vi.hoisted(() => vi.fn());
const fetchConversations = vi.hoisted(() => vi.fn());

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchConversations: (...args: Parameters<typeof fetchConversations>) =>
			fetchConversations(...args),
		fetchConversationMessages: vi.fn().mockResolvedValue({ messages: [] }),
		startNewConversation: vi.fn(async () => ({
			id: 'c1',
			title: null,
			message_count: 0,
			archived_at: null,
			created_at: '2026-01-01T00:00:00+00:00'
		})),
		deleteConversation: vi.fn(),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: 'sonnet' }),
		streamCoWriterTurn: (...args: Parameters<typeof streamCoWriterTurn>) =>
			streamCoWriterTurn(...args)
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';
import { startNewConversation } from '$lib/api/client';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	fetchConversations.mockReset().mockResolvedValue([]);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	streamCoWriterTurn.mockReset();
});

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Open Song',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		version_count: 1,
		generation_count: 0,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		generations: [],
		...overrides
	};
}

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
	mounted.push(
		mount(CoWriterPanel, {
			target,
			props: {
				currentSongId: 's1',
				currentAlbumId: 'a1',
				currentAlbumTitle: 'Album',
				allSongs: [song()],
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
			allSongs: [song({ id: 's1', title: 'Open Song' }), song({ id: 's2', title: 'Other Song' })]
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
			allSongs: [song({ id: 's1', title: 'Open Song' })]
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
