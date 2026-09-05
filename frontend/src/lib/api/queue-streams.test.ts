import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchSharedAlbumStream,
	fetchSharedPlaylistStream,
	pinQueueStream,
	unpinQueueStream
} from './queue-streams';

function acceptRequests(): void {
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ snapshot_id: 'snap-1' }) });
}

function request(): [string, RequestInit] {
	return mockFetch.mock.calls[0] as [string, RequestInit];
}

beforeEach(() => {
	mockFetch.mockReset();
	acceptRequests();
});

describe('queue stream API contract', () => {
	it('builds explicit and library snapshots with their declared defaults', async () => {
		await createQueueStreamSnapshot([{ generation_id: 'g-1' }]);
		let [url, init] = request();
		expect(url).toBe('/api/queue-streams');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({ tracks: [{ generation_id: 'g-1' }] });

		mockFetch.mockClear();
		await createLibraryQueueStreamSnapshot(null);
		[url, init] = request();
		expect(url).toBe('/api/queue-streams/library');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({ start_generation_id: null, shuffle: false, pool: 'mix' });
	});

	it.each([
		['pins', () => pinQueueStream('snap-1'), 'POST'],
		['unpins', () => unpinQueueStream('snap-1'), 'DELETE']
	])('%s a snapshot through its pin endpoint', async (_name, send, method) => {
		await send();
		const [url, init] = request();
		expect(url).toBe('/api/queue-streams/snap-1/pin');
		expect(init.method).toBe(method);
	});

	it.each([
		['playlist', () => fetchSharedPlaylistStream('shared-playlist'), '/shared/playlist/shared-playlist/stream'],
		['album', () => fetchSharedAlbumStream('shared-album'), '/shared/shared-album/stream']
	])('returns the shared %s manifest and reports an unavailable stream', async (_name, fetchStream, url) => {
		mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ snapshot_id: 'snap-1' }) });
		expect(await fetchStream()).toEqual({ snapshot_id: 'snap-1' });
		expect(request()[0]).toBe(url);
		expect(request()[1]).toEqual({ method: 'POST' });

		mockFetch.mockReset();
		mockFetch.mockResolvedValueOnce({ ok: false });
		await expect(fetchStream()).rejects.toThrow('Failed to create shared');
	});
});
