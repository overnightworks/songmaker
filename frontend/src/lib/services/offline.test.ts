import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import {
	manifestCacheKey,
	offlineStreamUrl,
	buildCacheStreamMessage,
	buildUncacheStreamMessage,
	isStreamSaved,
	saveStream,
	removeStream,
	offlinePlaylistMetaKey,
	playlistOfflineMeta,
	rememberPlaylistOfflineStream,
	forgetPlaylistOfflineStream,
	loadSavedOfflinePlaylist,
	OFFLINE_STREAM_META_VERSION,
	isOfflinePlaylistStreamMeta,
	isLiveAudioPath,
	isOfflineAudioPath,
	shouldInterceptInServiceWorker,
	responseForOfflineCacheHit,
	requestPathname
} from './offline';

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

// ── Pure message builders ──────────────────────────────────────────────────

describe('manifestCacheKey', () => {
	it('produces a stable URL from snapshot id', () => {
		expect(manifestCacheKey('abc-123')).toBe('/offline/manifest/abc-123');
	});
});

describe('buildCacheStreamMessage', () => {
	it('sets type CACHE_STREAM', () => {
		expect(buildCacheStreamMessage(makeManifest()).type).toBe('CACHE_STREAM');
	});

	it('fetches the live stream and caches the synthetic offline URL', () => {
		const manifest = makeManifest({
			snapshot_id: 'snap-9',
			stream_url: '/api/queue-streams/snap-9/audio'
		});
		const msg = buildCacheStreamMessage(manifest);
		expect(msg.sourceUrl).toBe('/api/queue-streams/snap-9/audio');
		expect(msg.streamUrl).toBe(offlineStreamUrl('snap-9'));
	});

	it('derives manifestUrl from snapshot_id', () => {
		const manifest = makeManifest({ snapshot_id: 'snap-42' });
		expect(buildCacheStreamMessage(manifest).manifestUrl).toBe(manifestCacheKey('snap-42'));
	});

	it('reports trackCount in meta', () => {
		const manifest = makeManifest({ tracks: [] });
		expect(buildCacheStreamMessage(manifest).meta.trackCount).toBe(0);
	});
});

describe('service worker fetch routing', () => {
	it('does not intercept live per-track audio', () => {
		expect(isLiveAudioPath('/audio/user/file.mp3')).toBe(true);
		expect(shouldInterceptInServiceWorker('/audio/user/file.mp3')).toBe(false);
	});

	it('does not intercept live queue-stream audio', () => {
		expect(isLiveAudioPath('/api/queue-streams/abc/audio')).toBe(true);
		expect(shouldInterceptInServiceWorker('/api/queue-streams/abc/audio')).toBe(false);
	});

	it('intercepts only the synthetic offline namespace', () => {
		expect(isOfflineAudioPath(offlineStreamUrl('snap-1'))).toBe(true);
		expect(shouldInterceptInServiceWorker(offlineStreamUrl('snap-1'))).toBe(true);
		expect(shouldInterceptInServiceWorker(manifestCacheKey('snap-1'))).toBe(true);
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

describe('buildUncacheStreamMessage', () => {
	it('sets type UNCACHE_STREAM', () => {
		expect(buildUncacheStreamMessage('/audio/s.mp3', 'snap-1').type).toBe('UNCACHE_STREAM');
	});

	it('preserves streamUrl and derives manifestUrl', () => {
		const msg = buildUncacheStreamMessage('/audio/s.mp3', 'snap-1');
		expect(msg.streamUrl).toBe('/audio/s.mp3');
		expect(msg.manifestUrl).toBe(manifestCacheKey('snap-1'));
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

describe('isStreamSaved', () => {
	beforeEach(() => {
		store.clear();
		vi.clearAllMocks();
		mockCaches.open.mockResolvedValue(mockCache);
		mockCache.match.mockImplementation(async (url: string | Request) => {
			const key = typeof url === 'string' ? url : (url as Request).url;
			return store.get(key);
		});
		vi.stubGlobal('caches', mockCaches);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('returns false when the URL is not in the cache', async () => {
		expect(await isStreamSaved(offlineStreamUrl('snap-1'))).toBe(false);
	});

	it('returns true when the URL is present in the cache', async () => {
		store.set(offlineStreamUrl('snap-1'), new Response('data'));
		expect(await isStreamSaved(offlineStreamUrl('snap-1'))).toBe(true);
	});

	it('returns false when caches API is unavailable', async () => {
		vi.unstubAllGlobals();
		expect(await isStreamSaved(offlineStreamUrl('snap-1'))).toBe(false);
	});
});

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
		const mKey = manifestCacheKey('snap-1');
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
			expect.objectContaining({ type: 'CACHE_STREAM' }),
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

		expect(progress).toHaveBeenCalledWith({ downloaded: 4, total: 10, done: false, error: undefined });
		expect(progress).toHaveBeenCalledWith({ downloaded: 10, total: 10, done: true, error: undefined });
		expect(pin).toHaveBeenCalledWith('snap-1');
	});

	it('surfaces the service worker cache error to the caller', async () => {
		mockController.postMessage.mockImplementation((_msg, ports: MessagePort[]) => {
			ports[0].postMessage({ type: 'CACHE_PROGRESS', cached: 0, total: null, done: true, error: 'disk full' });
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
		const meta = playlistOfflineMeta('pl-1', 'snap-1');
		store.set(offlinePlaylistMetaKey('pl-1'), new Response(JSON.stringify(meta)));
		store.set(meta.stream_url, new Response('audio'));

		const loaded = await loadSavedOfflinePlaylist('pl-1');

		expect(sessionStorage).toHaveLength(0);
		expect(loaded).toEqual(meta);
		expect(loaded?.version).toBe(OFFLINE_STREAM_META_VERSION);
	});

	it('forgets metadata when the stream body is gone', async () => {
		const meta = playlistOfflineMeta('pl-1', 'snap-1');
		store.set(offlinePlaylistMetaKey('pl-1'), new Response(JSON.stringify(meta)));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
		expect(store.has(offlinePlaylistMetaKey('pl-1'))).toBe(false);
	});

	it('ignores an unknown metadata version', async () => {
		store.set(
			offlinePlaylistMetaKey('pl-1'),
			new Response(
				JSON.stringify({
					...playlistOfflineMeta('pl-1', 'snap-1'),
					version: OFFLINE_STREAM_META_VERSION + 1
				})
			)
		);
		store.set(offlineStreamUrl('snap-1'), new Response('audio'));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
	});

	it('rejects metadata stored under a different playlist key', async () => {
		const meta = playlistOfflineMeta('pl-other', 'snap-1');
		store.set(offlinePlaylistMetaKey('pl-1'), new Response(JSON.stringify(meta)));
		store.set(meta.stream_url, new Response('audio'));

		expect(await loadSavedOfflinePlaylist('pl-1')).toBeNull();
		expect(store.has(offlinePlaylistMetaKey('pl-1'))).toBe(false);
	});

	it.each([
		['an older version', { ...playlistOfflineMeta('pl-1', 'snap-1'), version: 0 }],
		['an empty snapshot id', { ...playlistOfflineMeta('pl-1', 'snap-1'), snapshot_id: '' }],
		['a missing manifest URL', { ...playlistOfflineMeta('pl-1', 'snap-1'), manifest_url: undefined }],
		['a non-object value', 'not metadata']
	])('does not treat %s as reusable offline playlist metadata', (_name, candidate) => {
		expect(isOfflinePlaylistStreamMeta(candidate)).toBe(false);
	});

	it('writes and removes playlist metadata in the cache', async () => {
		await rememberPlaylistOfflineStream('pl-1', 'snap-9');
		const raw = store.get(offlinePlaylistMetaKey('pl-1'));
		if (!raw) {
			throw new Error('expected cached playlist metadata');
		}
		expect(await raw.json()).toEqual(playlistOfflineMeta('pl-1', 'snap-9'));

		await forgetPlaylistOfflineStream('pl-1');
		expect(store.has(offlinePlaylistMetaKey('pl-1'))).toBe(false);
	});
});
