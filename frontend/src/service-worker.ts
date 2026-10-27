/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

import { base, build, files, version } from '$service-worker';

declare const self: ServiceWorkerGlobalScope;

/** Versioned cache name for the SvelteKit app shell. */
const APP_SHELL_CACHE = `app-shell-${version}`;
const APP_SHELL_URL = '/index.html';

/**
 * The hashed Web Worker chunks, rewritten into the built file by
 * `scripts/inject_worker_precache.mjs`. Vite bundles workers in a pass whose
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
			.then((cache) =>
				cache.addAll([...PRECACHE_URLS, new Request(APP_SHELL_URL, { cache: 'reload' })])
			)
			.then(() => self.skipWaiting())
	);
});

// ── Activate: remove every cache but the current app shell ─────────────────

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(keys.filter((key) => key !== APP_SHELL_CACHE).map((key) => caches.delete(key)))
			)
			.then(() => self.clients.claim())
	);
});

// ── Fetch: app shell ──────────────────────────────────────────────────────

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

	// 2. Let the server resolve navigations; the cached shell is for connection failures.
	if (event.request.mode === 'navigate') {
		event.respondWith(serveNavigation(event.request));
	}
});

async function serveAppShell(request: Request, pathname: string): Promise<Response> {
	const cache = await caches.open(APP_SHELL_CACHE);
	return (await cache.match(pathname)) ?? fetch(request);
}

async function serveNavigation(request: Request): Promise<Response> {
	try {
		return await fetch(request);
	} catch {
		const cache = await caches.open(APP_SHELL_CACHE);
		return (await cache.match(APP_SHELL_URL)) ?? Response.error();
	}
}
