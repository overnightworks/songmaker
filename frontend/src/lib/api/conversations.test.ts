import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { streamCoWriterTurn } from './conversations';

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	return new ReadableStream({
		start(controller) {
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
			controller.close();
		}
	});
}

describe('v2 co-writer request contract', () => {
	beforeEach(() => {
		mockFetch.mockReset();
		mockFetch.mockResolvedValue({
			ok: true,
			body: streamFrom([])
		});
	});

	it('serializes mention selectors and optional current_generation_id once', async () => {
		const gen = streamCoWriterTurn({
			message: 'compare',
			current_song_id: 's1',
			mentioned_song_ids: ['s2'],
			mentioned_version_ids: ['v1'],
			mentioned_album_id: 'alb1',
			current_generation_id: 'g9'
		});
		await gen.next();
		const init = mockFetch.mock.calls[0][1] as RequestInit;
		const body = JSON.parse(init.body as string);
		expect(body).toEqual({
			message: 'compare',
			current_song_id: 's1',
			mentioned_song_ids: ['s2'],
			mentioned_version_ids: ['v1'],
			mentioned_album_id: 'alb1',
			current_generation_id: 'g9'
		});
		expect(body.lyrics).toBeUndefined();
	});
});
