// Rewrites the hashed Web Worker chunk paths into the built service worker so
// that it precaches them along with the app shell.
//
// Neither build step knows them on its own: Vite bundles workers in a Rollup
// pass of its own whose output never reaches the client manifest that
// SvelteKit generates `$service-worker`'s `build` list from, and importing the
// worker URL from the service worker is no way out either — SvelteKit builds
// the service worker in yet another pass, which would emit a second,
// differently hashed copy of the worker. Only the finished build knows the
// paths, so they are injected here.

import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const BUILD_DIR = 'build';
const SERVICE_WORKER_FILE = 'service-worker.js';
const WORKER_CHUNK_DIR = path.join('_app', 'immutable', 'workers');

/** The literal `src/service-worker.ts` carries in place of the chunk paths. */
export const WORKER_CHUNK_PLACEHOLDER = '__SONGMAKER_WORKER_CHUNKS__';

/** The separator the service worker splits the injected paths on. */
const PATH_SEPARATOR = ',';

/**
 * The root-relative path of every worker chunk in a finished build.
 *
 * @param {string} buildDir
 * @returns {Promise<string[]>}
 */
export async function collectWorkerChunkPaths(buildDir) {
	const workerDir = path.join(buildDir, WORKER_CHUNK_DIR);
	const entries = await readdir(workerDir, { recursive: true, withFileTypes: true });
	return entries
		.filter((entry) => entry.isFile())
		.map((entry) => path.relative(buildDir, path.join(entry.parentPath, entry.name)))
		.map((chunk) => `/${chunk.split(path.sep).join('/')}`)
		.sort();
}

/**
 * The built service worker with its placeholder replaced by the given paths.
 *
 * @param {string} serviceWorkerCode
 * @param {string[]} workerChunkPaths
 * @returns {string}
 */
export function injectWorkerChunkPaths(serviceWorkerCode, workerChunkPaths) {
	if (workerChunkPaths.length === 0) {
		throw new Error('The build produced no worker chunks to precache.');
	}
	const ambiguous = workerChunkPaths.filter((chunk) => chunk.includes(PATH_SEPARATOR));
	if (ambiguous.length > 0) {
		throw new Error(
			`Worker chunk paths must not contain "${PATH_SEPARATOR}": ${ambiguous.join(' ')}`
		);
	}
	if (!serviceWorkerCode.includes(WORKER_CHUNK_PLACEHOLDER)) {
		throw new Error(`The built service worker carries no ${WORKER_CHUNK_PLACEHOLDER} placeholder.`);
	}
	return serviceWorkerCode.replaceAll(WORKER_CHUNK_PLACEHOLDER, () =>
		workerChunkPaths.join(PATH_SEPARATOR)
	);
}

async function precacheWorkerChunks() {
	const buildDir = path.resolve(BUILD_DIR);
	const serviceWorker = path.join(buildDir, SERVICE_WORKER_FILE);
	const workerChunkPaths = await collectWorkerChunkPaths(buildDir);
	const code = injectWorkerChunkPaths(await readFile(serviceWorker, 'utf8'), workerChunkPaths);
	await writeFile(serviceWorker, code);
	console.log(`${SERVICE_WORKER_FILE} precaches ${workerChunkPaths.length} worker chunk(s)`);
}

if (pathToFileURL(process.argv[1]).href === import.meta.url) {
	await precacheWorkerChunks();
}
