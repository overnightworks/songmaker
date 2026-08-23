import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	WORKER_CHUNK_PLACEHOLDER,
	collectWorkerChunkPaths,
	injectWorkerChunkPaths
} from '../scripts/inject-worker-precache.mjs';
import serviceWorkerSource from './service-worker.ts?raw';

const ALIGN_WORKER = '/_app/immutable/workers/lyrics-align.worker-Db2gWdvJ.js';
const SHARED_CHUNK = '/_app/immutable/workers/chunks/BqT1nS9r.js';

async function buildDirContaining(...workerChunkPaths: string[]): Promise<string> {
	const buildDir = await mkdtemp(path.join(tmpdir(), 'worker-precache-'));
	for (const chunk of workerChunkPaths) {
		const file = path.join(buildDir, chunk);
		await mkdir(path.dirname(file), { recursive: true });
		await writeFile(file, '');
	}
	return buildDir;
}

describe('worker precache injection', () => {
	it('replaces the placeholder with the worker chunk paths', () => {
		const injected = injectWorkerChunkPaths(`const c='${WORKER_CHUNK_PLACEHOLDER}'.split(',')`, [
			ALIGN_WORKER,
			SHARED_CHUNK
		]);

		expect(injected).toBe(`const c='${ALIGN_WORKER},${SHARED_CHUNK}'.split(',')`);
	});

	it('rejects a build that produced no worker chunks', () => {
		expect(() => injectWorkerChunkPaths(WORKER_CHUNK_PLACEHOLDER, [])).toThrow(/no worker chunks/);
	});

	it('rejects a service worker that carries no placeholder', () => {
		expect(() => injectWorkerChunkPaths('const c=[]', [ALIGN_WORKER])).toThrow(/placeholder/);
	});

	it('rejects a chunk path that would split into two precache URLs', () => {
		expect(() =>
			injectWorkerChunkPaths(WORKER_CHUNK_PLACEHOLDER, ['/_app/immutable/workers/a,b-Db2g.js'])
		).toThrow(/must not contain/);
	});

	it('collects every worker chunk of a build, nested ones included', async () => {
		const buildDir = await buildDirContaining(SHARED_CHUNK, ALIGN_WORKER);

		await expect(collectWorkerChunkPaths(buildDir)).resolves.toEqual([SHARED_CHUNK, ALIGN_WORKER]);
	});

	it('leaves the service worker source carrying the placeholder the build injects into', () => {
		expect(serviceWorkerSource).toContain(WORKER_CHUNK_PLACEHOLDER);
	});
});
