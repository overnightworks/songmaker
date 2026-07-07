import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import {
	manifestCacheKey,
	buildCacheStreamMessage,
	buildUncacheStreamMessage,
	isStreamSaved,
	removeStream
} from './offline';

// ── Fixtures ───────────────────────────────────────────────────────────────

function makeManifest(overrides: Partial<QueueStreamManifest> = {}): QueueStreamManifest {
	return {
		snapshot_id: 'snap-1',
		stream_url: '/audio/queue-streams/snap-1.mp3',
		expires_at: '2026-12-31T00:00:00Z',
		total_duration: 120,
		tracks: [],
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

	it('uses the manifest stream_url as streamUrl', () => {
		const manifest = makeManifest({ stream_url: '/audio/queue-streams/x.mp3' });
		expect(buildCacheStreamMessage(manifest).streamUrl).toBe('/audio/queue-streams/x.mp3');
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
		expect(await isStreamSaved('/audio/stream.mp3')).toBe(false);
	});

	it('returns true when the URL is present in the cache', async () => {
		store.set('/audio/stream.mp3', new Response('data'));
		expect(await isStreamSaved('/audio/stream.mp3')).toBe(true);
	});

	it('returns false when caches API is unavailable', async () => {
		vi.unstubAllGlobals();
		// caches is not stubbed — globalThis.caches is undefined in jsdom
		expect(await isStreamSaved('/audio/stream.mp3')).toBe(false);
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
		await removeStream('/audio/s.mp3', 'snap-1');
		expect(mockController.postMessage).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'UNCACHE_STREAM', streamUrl: '/audio/s.mp3' })
		);
	});

	it('removes the stream URL from the cache', async () => {
		store.set('/audio/s.mp3', new Response('data'));
		await removeStream('/audio/s.mp3', 'snap-1');
		expect(store.has('/audio/s.mp3')).toBe(false);
	});

	it('removes the manifest URL from the cache', async () => {
		const mKey = manifestCacheKey('snap-1');
		store.set(mKey, new Response('{}'));
		await removeStream('/audio/s.mp3', 'snap-1');
		expect(store.has(mKey)).toBe(false);
	});
});
