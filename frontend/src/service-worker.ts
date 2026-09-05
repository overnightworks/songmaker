/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

import { base, build, files, version } from '$service-worker';
import {
	OFFLINE_STREAMS_CACHE,
	requestPathname,
	responseForOfflineCacheHit,
	shouldInterceptInServiceWorker
} from '$lib/services/offline';

declare const self: ServiceWorkerGlobalScope;

/** Versioned cache name for the SvelteKit app shell. */
const APP_SHELL_CACHE = `app-shell-${version}`;

/**
 * The hashed Web Worker chunks, rewritten into the built file by
 * `scripts/inject-worker-precache.mjs`. Vite bundles workers in a pass whose
 * output never reaches the client manifest that `build` is generated from, so
 * the finished build is the only place these paths exist.
 */
const WORKER_CHUNKS = '__SONGMAKER_WORKER_CHUNKS__'.split(',').map((chunk) => base + chunk);

/** Every precacheable URL: app bundle + worker chunks + static files. */
const PRECACHE_URLS = new Set([...build, ...WORKER_CHUNKS, ...files]);

// ── Install: precache the app shell ───────────────────────────────────────

self.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(APP_SHELL_CACHE)
			.then((cache) => cache.addAll([...PRECACHE_URLS]))
			.then(() => self.skipWaiting())
	);
});

// ── Activate: remove stale app-shell caches ────────────────────────────────

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(
					keys
						.filter((key) => key !== APP_SHELL_CACHE && key !== OFFLINE_STREAMS_CACHE)
						.map((key) => caches.delete(key))
				)
			)
			.then(() => self.clients.claim())
	);
});

// ── Fetch: app shell + offline streams ────────────────────────────────────

self.addEventListener('fetch', (event) => {
	// Only handle GET on same-origin requests — let everything else pass through.
	if (event.request.method !== 'GET') return;
	const url = new URL(event.request.url);
	if (url.origin !== self.location.origin) return;

	// 1. Precached app-shell asset → cache-first.
	if (PRECACHE_URLS.has(url.pathname)) {
		event.respondWith(serveAppShell(event.request, url.pathname));
		return;
	}

	// 2. SPA navigation → serve cached index.html (offline shell).
	if (event.request.mode === 'navigate') {
		event.respondWith(serveNavigation(event.request));
		return;
	}

	if (!shouldInterceptInServiceWorker(url.pathname)) return;

	event.respondWith(serveOfflineNamespace(event.request));
});

async function serveAppShell(request: Request, pathname: string): Promise<Response> {
	const cache = await caches.open(APP_SHELL_CACHE);
	return (await cache.match(pathname)) ?? fetch(request);
}

async function serveNavigation(request: Request): Promise<Response> {
	const cache = await caches.open(APP_SHELL_CACHE);
	return (await cache.match('/index.html')) ?? fetch(request);
}

async function serveOfflineNamespace(request: Request): Promise<Response> {
	const cache = await caches.open(OFFLINE_STREAMS_CACHE);
	const pathname = requestPathname(request.url);
	const cached = (await cache.match(pathname)) ?? (await cache.match(request.url));
	return responseForOfflineCacheHit(cached, request.headers.get('Range'));
}

// ── Message handlers ───────────────────────────────────────────────────────

interface CacheStreamMessage {
	type: 'CACHE_STREAM';
	manifestUrl: string;
	streamUrl: string;
	sourceUrl: string;
	meta: Record<string, unknown>;
}

interface UncacheStreamMessage {
	type: 'UNCACHE_STREAM';
	streamUrl: string;
	manifestUrl: string;
}

self.addEventListener('message', (event) => {
	const data = event.data as CacheStreamMessage | UncacheStreamMessage;

	if (data.type === 'CACHE_STREAM') {
		const port = event.ports[0] as MessagePort | undefined;
		event.waitUntil(handleCacheStream(data, port));
	} else if (data.type === 'UNCACHE_STREAM') {
		event.waitUntil(handleUncacheStream(data));
	}
});

async function handleCacheStream(
	msg: CacheStreamMessage,
	port: MessagePort | undefined
): Promise<void> {
	try {
		const response = await fetch(msg.sourceUrl);
		if (!response.ok || !response.body) {
			port?.postMessage({
				type: 'CACHE_PROGRESS',
				cached: 0,
				total: 0,
				done: true,
				error: `HTTP ${response.status}`
			});
			return;
		}

		const contentLengthHeader = response.headers.get('Content-Length');
		const total = contentLengthHeader ? Number.parseInt(contentLengthHeader, 10) : null;
		const contentType = response.headers.get('Content-Type') ?? 'audio/mpeg';

		const reader = response.body.getReader();
		const chunks: Uint8Array[] = [];
		let downloaded = 0;

		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			chunks.push(value);
			downloaded += value.byteLength;
			port?.postMessage({ type: 'CACHE_PROGRESS', cached: downloaded, total, done: false });
		}

		const fullBody = new Blob(chunks, { type: contentType });

		const cache = await caches.open(OFFLINE_STREAMS_CACHE);
		await cache.put(
			msg.streamUrl,
			new Response(fullBody, {
				headers: {
					'Content-Type': contentType,
					'Content-Length': String(downloaded),
					'Accept-Ranges': 'bytes'
				}
			})
		);

		port?.postMessage({
			type: 'CACHE_PROGRESS',
			cached: downloaded,
			total: downloaded,
			done: true
		});
	} catch (error) {
		const message = error instanceof Error ? error.message : 'Download failed';
		port?.postMessage({ type: 'CACHE_PROGRESS', cached: 0, total: 0, done: true, error: message });
	}
}

async function handleUncacheStream(msg: UncacheStreamMessage): Promise<void> {
	const cache = await caches.open(OFFLINE_STREAMS_CACHE);
	await Promise.all([cache.delete(msg.streamUrl), cache.delete(msg.manifestUrl)]);
}
