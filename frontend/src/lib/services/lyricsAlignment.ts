// Owns the lyrics alignment worker (#158). Aligning a take costs a few
// hundred milliseconds of pure computation, so it runs off the main thread;
// Now Playing shows static lyrics until the result arrives.
//
// One take at a time is worth waiting for: when the listener skips to the next
// track, the take still being aligned is superseded and its caller settles
// with `null` right away, so a late result can never overwrite the lyrics of
// the take now playing. The worker cannot be interrupted mid-take, so its
// answer for a superseded request is dropped on arrival by request id.
import type { WhisperCue } from '$lib/api/types';
import { alignLyricsToCues, type AlignedLyricLine } from '$lib/utils/lyrics-align';

/** One take handed to the worker, identified for the latest-wins check. */
export interface AlignmentRequest {
	id: number;
	lyrics: string;
	cues: WhisperCue[];
}

export interface AlignmentResult {
	id: number;
	lines: AlignedLyricLine[];
}

interface AwaitedAlignment {
	id: number;
	resolve: (lines: AlignedLyricLine[] | null) => void;
	reject: (error: Error) => void;
}

let worker: Worker | null = null;
let awaited: AwaitedAlignment | null = null;
let lastRequestId = 0;

function startWorker(): Worker {
	const started = new Worker(new URL('../utils/lyrics-align.worker.ts', import.meta.url), {
		type: 'module'
	});
	started.addEventListener('message', (event: MessageEvent<AlignmentResult>) => {
		const request = awaited;
		if (!request || request.id !== event.data.id) return;
		awaited = null;
		request.resolve(event.data.lines);
	});
	started.addEventListener('error', (event) => {
		const request = awaited;
		awaited = null;
		request?.reject(new Error(`Lyrics alignment worker failed: ${event.message}`));
	});
	return started;
}

function supersedeAwaited(): void {
	awaited?.resolve(null);
	awaited = null;
}

/**
 * Aligns one take's lyrics against its cues off the main thread. Resolves with
 * the aligned lines, or with `null` when a later take superseded this request.
 * Where the platform has no worker — server-side rendering, jsdom — the same
 * pure function answers synchronously.
 */
export function alignInWorker(
	lyrics: string,
	cues: WhisperCue[]
): Promise<AlignedLyricLine[] | null> {
	if (typeof Worker === 'undefined') return Promise.resolve(alignLyricsToCues(lyrics, cues));

	worker ??= startWorker();
	supersedeAwaited();
	const id = ++lastRequestId;
	const aligned = new Promise<AlignedLyricLine[] | null>((resolve, reject) => {
		awaited = { id, resolve, reject };
	});
	worker.postMessage({ id, lyrics, cues } satisfies AlignmentRequest);
	return aligned;
}

// A hot reload replaces this module while its worker keeps running the old
// code and holding its memory.
import.meta.hot?.dispose(() => {
	worker?.terminate();
	worker = null;
	supersedeAwaited();
});
