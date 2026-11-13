import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/fetch.ts';
import { words } from '#lib/words/en.ts';

const fetchConversations = vi.hoisted(() => vi.fn());
const fetchConversationMessages = vi.hoisted(() => vi.fn());
const streamCoWriterTurn = vi.hoisted(() => vi.fn());

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		fetchConversations: (...args: Parameters<typeof fetchConversations>) =>
			fetchConversations(...args),
		fetchConversationMessages: (...args: Parameters<typeof fetchConversationMessages>) =>
			fetchConversationMessages(...args),
		streamCoWriterTurn: (...args: Parameters<typeof streamCoWriterTurn>) =>
			streamCoWriterTurn(...args)
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	fetchConversations.mockReset().mockResolvedValue([]);
	fetchConversationMessages.mockReset().mockResolvedValue({ messages: [] });
	streamCoWriterTurn.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('CoWriterPanel refused turn', () => {
	it.each([
		{
			name: 'shows the words of the refusal key under the message and never the detail',
			key: 'cowriterRefusal.takeNotInSong',
			expected: words['cowriterRefusal.takeNotInSong']
		},
		{
			name: 'shows the page fallback for a refusal key the page does not know, never the detail',
			key: 'cowriterRefusal.notAKnownKey',
			expected: words['cowriterProblem.noAnswer']
		}
	])('$name', async ({ key, expected }) => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		streamCoWriterTurn.mockReturnValue(
			(async function* () {
				yield* [];
				throw new ApiError(422, 'Sentence of the server', '/api/chat/turn', null, '', null, null, {
					key,
					values: {}
				});
			})()
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(CoWriterPanel, {
			target,
			props: { currentSongId: 's1', currentAlbumId: 'a1' }
		});
		await tick();
		const input = target.querySelector<HTMLTextAreaElement>('.chat-input');
		if (!input) throw new Error('Expected the chat textarea');
		input.value = 'write a chorus';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		target.querySelector<HTMLButtonElement>('.send-btn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('.turn-error .text')?.textContent).toBe(expected)
		);
	});
});
