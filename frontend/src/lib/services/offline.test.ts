import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import {
	offlineStreamUrl,
	saveStream,
	removeStream,
	rememberPlaylistOfflineStream,
	forgetPlaylistOfflineStream,
	loadSavedOfflinePlaylist,
	shouldInterceptInServiceWorker,
	responseForOfflineCacheHit,
	requestPathname
} from './offline';

const SAVED_PLAYLIST = {
	playlist_id: 'pl-1',
	snapshot_id: 'snap-1',
	stream_url: '/offline/stream/snap-1',
	manifest_url: '/offline/manifest/snap-1',
	version: 1
};

// ── Fixtures ───────────────────────────────────────────────────────────────

function makeManifest(overrides: Partial<QueueStreamManifest> = {}): QueueStreamManifest {
	return {
		snapshot_id: 'snap-1',
		stream_url: '/audio/queue-streams/snap-1.mp3',
		expires_at: '2026-12-31T00:00:00Z',
		total_duration: 120,
		tracks: [],
		windowed: false,
		skipped: [],
		skipped_complete: true,
		...overrides
	};
}

describe('service worker fetch routing', () => {
	it('does not intercept live per-track audio', () => {
		expect(shouldInterceptInServiceWorker('/audio/user/file.mp3')).toBe(false);
	});

	it('does not intercept live queue-stream audio', () => {
		expect(shouldInterceptInServiceWorker('/api/queue-streams/abc/audio')).toBe(false);
	});

	it('intercepts only the synthetic offline namespace', () => {
		expect(shouldInterceptInServiceWorker(offlineStreamUrl('snap-1'))).toBe(true);
		expect(shouldInterceptInServiceWorker('/offline/manifest/snap-1')).toBe(true);
		expect(shouldInterceptInServiceWorker('/api/jobs/1')).toBe(false);
	});

	it('strips query and hash from pathnames', () => {
		expect(requestPathname('https://x.example/offline/stream/s1?recover=2#t')).toBe(
			'/offline/stream/s1'
		);
	});
});

describe('responseForOfflineCacheHit', () => {
	it('fails closed on a cache miss instead of fetching the live URL', async () => {
		const response = await responseForOfflineCacheHit(undefined, null);
		expect(response.status).toBe(503);
	});

	it('returns the full body when no Range is sent', async () => {
		const cached = new Response('abcdefghij', { headers: { 'Content-Type': 'audio/mpeg' } });
		const response = await responseForOfflineCacheHit(cached, null);
		expect(response.status).toBe(200);
		expect(await response.text()).toBe('abcdefghij');
	});

	it('returns 206 with Content-Range for a valid Range', async () => {
		const cached = new Response('abcdefghij', { headers: { 'Content-Type': 'audio/mpeg' } });
		const response = await responseForOfflineCacheHit(cached, 'bytes=2-5');
		expect(response.status).toBe(206);
		expect(response.headers.get('Content-Range')).toBe('bytes 2-5/10');
		expect(await response.text()).toBe('cdef');
	});

	it('returns 416 for an unsatisfiable Range', async () => {
		const cached = new Response('abcdefghij');
		const response = await responseForOfflineCacheHit(cached, 'bytes=99-');
		expect(response.status).toBe(416);
	});
});

// ── Cache-API interaction ──────────────────────────────────────────────────

// Simple in-memory cache that the mock caches.open returns.
const store = new Map<string, Response>();

const mockCache = {
	match: vi.fn(async (url: string | Request) => {
		const key = typeof url === 'string' ? url : url.url;
		return store.get(key);
	}),
	put: vi.fn(async (url: string | Request, response: Response) => {
		const key = typeof url === 'string' ? url : (url as Request).url;
		store.set(key, response);
	}),
	delete: vi.fn(async (url: string | Request) => {
		const key = typeof url === 'string' ? url : (url as Request).url;
		return store.delete(key);
	})
};

const mockCaches = {
	open: vi.fn(async () => mockCache)
};

describe('removeStream', () => {
	const mockController = { postMessage: vi.fn() };

	beforeEach(() => {
		store.clear();
		vi.clearAllMocks();
		mockCaches.open.mockResolvedValue(mockCache);
		mockCache.delete.mockImplementation(async (url: string | Request) => {
			const key = typeof url === 'string' ? url : (url as Request).url;
			return store.delete(key);
		});
		mockController.postMessage.mockReset();
		vi.stubGlobal('caches', mockCaches);
		vi.stubGlobal('navigator', { serviceWorker: { controller: mockController } });
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('posts an UNCACHE_STREAM message to the service worker', async () => {
		const streamUrl = offlineStreamUrl('snap-1');
		await removeStream(streamUrl, 'snap-1');
		expect(mockController.postMessage).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'UNCACHE_STREAM', streamUrl })
		);
	});

	it('removes the stream URL from the cache', async () => {
		const streamUrl = offlineStreamUrl('snap-1');
		store.set(streamUrl, new Response('data'));
		await removeStream(streamUrl, 'snap-1');
		expect(store.has(streamUrl)).toBe(false);
	});

	it('removes the manifest URL from the cache', async () => {
		const mKey = '/offline/manifest/snap-1';
		store.set(mKey, new Response('{}'));
		await removeStream(offlineStreamUrl('snap-1'), 'snap-1');
		expect(store.has(mKey)).toBe(false);
	});
});

describe('saveStream', () => {
	const mockController = { postMessage: vi.fn() };
	const serviceWorker: { controller: { postMessage: ReturnType<typeof vi.fn> } | null } = {
		controller: mockController
	};

	beforeEach(() => {
		store.clear();
		vi.clearAllMocks();
		serviceWorker.controller = mockController;
		mockCaches.open.mockResolvedValue(mockCache);
		mockCache.put.mockImplementation(async (url: string | Request, response: Response) => {
			const key = typeof url === 'string' ? url : (url as Request).url;
			store.set(key, response);
		});
		vi.stubGlobal('caches', mockCaches);
		vi.stubGlobal('navigator', { serviceWorker });
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('posts CACHE_STREAM to the controller that is active after caching', async () => {
		mockController.postMessage.mockImplementation((_msg, ports: MessagePort[]) => {
			ports[0].postMessage({ type: 'CACHE_PROGRESS', cached: 1, total: 1, done: true });
		});
		await saveStream(makeManifest());
		expect(mockController.postMessage).toHaveBeenCalledWith(
			{
				type: 'CACHE_STREAM',
				sourceUrl: '/audio/queue-streams/snap-1.mp3',
				streamUrl: '/offline/stream/snap-1',
				manifestUrl: '/offline/manifest/snap-1',
				meta: { title: 'snap-1', trackCount: 0 }
			},
			expect.any(Array)
		);
	});

	it('reports cache progress and completes even when the best-effort pin fails', async () => {
		mockController.postMessage.mockImplementation((_msg, ports: MessagePort[]) => {
			ports[0].postMessage({ type: 'CACHE_PROGRESS', cached: 4, total: 10, done: false });
			ports[0].postMessage({ type: 'CACHE_PROGRESS', cached: 10, total: 10, done: true });
		});
		const progress = vi.fn();
		const pin = vi.fn().mockRejectedValue(new Error('pin unavailable'));

		await saveStream(makeManifest(), progress, pin);

		expect(progress).toHaveBeenCalledWith({
			downloaded: 4,
			total: 10,
			done: false,
			error: undefined
		});
		expect(progress).toHaveBeenCalledWith({
			downloaded: 10,
			total: 10,
			done: true,
			error: undefined
		});
		expect(pin).toHaveBeenCalledWith('snap-1');
	});

	it('surfaces the service worker cache error to the caller', async () => {
		mockController.postMessage.mockImplementation((_msg, ports: MessagePort[]) => {
			ports[0].postMessage({
				type: 'CACHE_PROGRESS',
				cached: 0,
				total: null,
				done: true,
				error: 'disk full'
			});
		});

		await expect(saveStream(makeManifest())).rejects.toThrow('disk full');
	});

	it('fails if the controller is gone after the cache write', async () => {
		mockCache.put.mockImplementation(async () => {
			serviceWorker.controller = null;
		});
		await expect(saveStream(makeManifest())).rejects.toThrow(
			'Service worker not active — cannot save for offline'
		);
		expect(mockController.postMessage).not.toHaveBeenCalled();
	});
});

describe('playlist offline metadata', () => {
	beforeEach(() => {
		store.clear();
		sessionStorage.clear();
		vi.clearAllMocks();
		mockCaches.open.mockResolvedValue(mockCache);
		mockCache.match.mockImplementation(async (url: string | Request) => {
			const key = typeof url === 'string' ? url : url.url;
			return store.get(key);
		});
		mockCache.put.mockImplementation(async (url: string | Request, response: Response) => {
			const key = typeof url === 'string' ? url : (url as Request).url;
			store.set(key, response);
		});
		mockCache.delete.mockImplementation(async (url: string | Request) => {
			const key = typeof url === 'string' ? url : (url as Request).url;
			return store.delete(key);
		});
		vi.stubGlobal('caches', mockCaches);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		sessionStorage.clear();
	});

	it('reconstructs saved status from cache metadata with empty sessionStorage', async () => {
		const meta = SAVED_PLAYLIST;
		store.set('/offline/meta/playlist/pl-1', new Response(JSON.stringify(meta)));
		store.set(meta.stream_url, new Response('audio'));

		const loaded = await loadSavedOfflinePlaylist('pl-1');

		expect(sessionStorage).toHaveLength(0);
		expect(loaded).toEqual(meta);
		expect(loaded?.version).toBe(1);
	});

	it('forgets metadata when the stream body is gone', async () => {
		const meta = SAVED_PLAYLIST;
		store.set('/offline/meta/playlist/pl-1', new Response(JSON.stringify(meta)));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
		expect(store.has('/offline/meta/playlist/pl-1')).toBe(false);
	});

	it('ignores an unknown metadata version', async () => {
		store.set(
			'/offline/meta/playlist/pl-1',
			new Response(
				JSON.stringify({
					...SAVED_PLAYLIST,
					version: 2
				})
			)
		);
		store.set(offlineStreamUrl('snap-1'), new Response('audio'));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
	});

	it('rejects metadata stored under a different playlist key', async () => {
		const meta = { ...SAVED_PLAYLIST, playlist_id: 'pl-other' };
		store.set('/offline/meta/playlist/pl-1', new Response(JSON.stringify(meta)));
		store.set(meta.stream_url, new Response('audio'));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
		expect(store.has('/offline/meta/playlist/pl-1')).toBe(false);
	});

	it.each([
		['an older version', { ...SAVED_PLAYLIST, version: 0 }],
		['an empty snapshot id', { ...SAVED_PLAYLIST, snapshot_id: '' }],
		['a missing manifest URL', { ...SAVED_PLAYLIST, manifest_url: undefined }],
		['a non-object value', 'not metadata']
	])('does not treat %s as reusable offline playlist metadata', async (_name, candidate) => {
		store.set('/offline/meta/playlist/pl-1', new Response(JSON.stringify(candidate)));
		store.set(SAVED_PLAYLIST.stream_url, new Response('audio'));
		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
	});

	it('writes and removes playlist metadata in the cache', async () => {
		await rememberPlaylistOfflineStream('pl-1', 'snap-1');
		const raw = store.get('/offline/meta/playlist/pl-1');
		if (!raw) {
			throw new Error('expected cached playlist metadata');
		}
		expect(await raw.json()).toEqual(SAVED_PLAYLIST);

		await forgetPlaylistOfflineStream('pl-1');
		expect(store.has('/offline/meta/playlist/pl-1')).toBe(false);
	});
});
