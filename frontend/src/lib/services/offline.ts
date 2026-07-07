import type { QueueStreamManifest } from '$lib/api/types';

/** Cache name shared with the service worker's fetch handler. */
export const OFFLINE_STREAMS_CACHE = 'offline-streams';

// ── Message types ──────────────────────────────────────────────────────────

export interface CacheStreamMessage {
	type: 'CACHE_STREAM';
	manifestUrl: string;
	streamUrl: string;
	meta: { title: string; trackCount: number };
}

export interface UncacheStreamMessage {
	type: 'UNCACHE_STREAM';
	streamUrl: string;
	manifestUrl: string;
}

export interface CacheProgressMessage {
	type: 'CACHE_PROGRESS';
	cached: number;
	total: number | null;
	done: boolean;
	error?: string;
}

// ── Pure message builders (testable without browser APIs) ──────────────────

/** Derives the cache key used to store a stream's manifest JSON. */
export function manifestCacheKey(snapshotId: string): string {
	return `/offline/manifest/${snapshotId}`;
}

/** Builds the CACHE_STREAM message posted to the service worker. */
export function buildCacheStreamMessage(manifest: QueueStreamManifest): CacheStreamMessage {
	return {
		type: 'CACHE_STREAM',
		manifestUrl: manifestCacheKey(manifest.snapshot_id),
		streamUrl: manifest.stream_url,
		meta: { title: manifest.snapshot_id, trackCount: manifest.tracks.length }
	};
}

/** Builds the UNCACHE_STREAM message posted to the service worker. */
export function buildUncacheStreamMessage(
	streamUrl: string,
	snapshotId: string
): UncacheStreamMessage {
	return {
		type: 'UNCACHE_STREAM',
		streamUrl,
		manifestUrl: manifestCacheKey(snapshotId)
	};
}

// ── Progress callback ──────────────────────────────────────────────────────

export interface StreamProgress {
	downloaded: number;
	total: number | null;
	done: boolean;
	error?: string;
}

export type ProgressCallback = (progress: StreamProgress) => void;

/**
 * Seam for server-side pin/unpin (later phase — Story B backend integration).
 * Called after the stream body is fully cached; absence is safe — the cached
 * MP3 remains usable offline regardless of server-side snapshot TTL.
 */
export type PinCallback = (snapshotId: string) => Promise<void>;

// ── Cache API helpers ──────────────────────────────────────────────────────

/** Returns true when the stream URL is present in the offline-streams cache. */
export async function isStreamSaved(streamUrl: string): Promise<boolean> {
	if (!('caches' in globalThis)) return false;
	const cache = await caches.open(OFFLINE_STREAMS_CACHE);
	const match = await cache.match(streamUrl);
	return match !== undefined;
}

/**
 * Saves a playlist stream for offline playback.
 *
 * 1. Writes the manifest JSON directly into the shared cache so the service
 *    worker can also serve it.
 * 2. Posts CACHE_STREAM to the active service worker, which fetches and
 *    caches the MP3 body while reporting progress.
 * 3. Calls onPin when the download completes (best-effort; errors are
 *    swallowed so they don't fail the save operation).
 */
export async function saveStream(
	manifest: QueueStreamManifest,
	onProgress?: ProgressCallback,
	onPin?: PinCallback
): Promise<void> {
	if (!('serviceWorker' in navigator) || !navigator.serviceWorker.controller) {
		throw new Error('Service worker not active — cannot save for offline');
	}

	// Store the manifest JSON directly so the cache is self-contained.
	const cache = await caches.open(OFFLINE_STREAMS_CACHE);
	await cache.put(
		manifestCacheKey(manifest.snapshot_id),
		new Response(JSON.stringify(manifest), {
			headers: { 'Content-Type': 'application/json' }
		})
	);

	return new Promise<void>((resolve, reject) => {
		const channel = new MessageChannel();

		channel.port1.onmessage = (event: MessageEvent) => {
			const data = event.data as CacheProgressMessage;
			if (data.type !== 'CACHE_PROGRESS') return;

			onProgress?.({
				downloaded: data.cached,
				total: data.total,
				done: data.done,
				error: data.error
			});

			if (!data.done) return;

			if (data.error) {
				reject(new Error(data.error));
			} else {
				if (onPin) {
					onPin(manifest.snapshot_id).catch(() => {
						// Pin is best-effort; swallow so save still completes.
					});
				}
				resolve();
			}
		};

		navigator.serviceWorker.controller!.postMessage(buildCacheStreamMessage(manifest), [
			channel.port2
		]);
	});
}

/**
 * Removes a saved stream from the offline-streams cache.
 *
 * Posts UNCACHE_STREAM to the service worker AND removes entries directly
 * from the Cache API so the UI reflects the change immediately.
 */
export async function removeStream(streamUrl: string, snapshotId: string): Promise<void> {
	const msg = buildUncacheStreamMessage(streamUrl, snapshotId);

	if (typeof navigator !== 'undefined' && navigator.serviceWorker?.controller) {
		navigator.serviceWorker.controller.postMessage(msg);
	}

	// Remove directly as well — the SW mirrors this, but doing it here ensures
	// the UI state stays consistent even before the SW processes the message.
	if ('caches' in globalThis) {
		const cache = await caches.open(OFFLINE_STREAMS_CACHE);
		await Promise.all([cache.delete(streamUrl), cache.delete(manifestCacheKey(snapshotId))]);
	}
}
