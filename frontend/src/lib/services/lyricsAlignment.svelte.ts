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

interface AwaitedAlignment extends AlignmentRequest {
	resolve: (lines: AlignedLyricLine[] | null) => void;
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
		if (request?.id !== event.data.id) return;
		awaited = null;
		request.resolve(event.data.lines);
	});
	// A worker that never loaded — an offline listener whose cache has no
	// worker chunk — or one that died mid-take would otherwise leave the take
	// on static lyrics forever. It is dropped, the take is aligned on the main
	// thread as it was before #158, and the next take starts a fresh worker.
	started.addEventListener('error', (event) => {
		const cause = event.message || 'the worker script could not be loaded';
		console.error(`Lyrics alignment worker failed, aligning on the main thread: ${cause}`);
		started.terminate();
		if (worker === started) worker = null;
		const request = awaited;
		awaited = null;
		if (request) request.resolve(alignLyricsToCues(request.lyrics, request.cues));
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
	// Share pages read the playing take's cues off reactive state, and a
	// `$state` proxy cannot cross a worker boundary — structuredClone rejects
	// it. The take is snapshotted here, at the boundary that needs it plain.
	const takeCues = $state.snapshot(cues) as WhisperCue[];
	if (typeof Worker === 'undefined') return Promise.resolve(alignLyricsToCues(lyrics, takeCues));

	// Constructing a worker can fail outright — a stricter CSP, a chunk served
	// with the wrong MIME type — and it throws where the caller can no longer
	// catch it, so the take takes the same road as a worker that dies later.
	let running: Worker;
	try {
		running = worker ??= startWorker();
	} catch (cause) {
		console.error(`Lyrics alignment worker could not start, aligning on the main thread: ${cause}`);
		return Promise.resolve(alignLyricsToCues(lyrics, takeCues));
	}

	supersedeAwaited();
	const id = ++lastRequestId;
	const aligned = new Promise<AlignedLyricLine[] | null>((resolve) => {
		awaited = { id, lyrics, cues: takeCues, resolve };
	});
	running.postMessage({ id, lyrics, cues: takeCues } satisfies AlignmentRequest);
	return aligned;
}

// A hot reload replaces this module while its worker keeps running the old
// code and holding its memory.
import.meta.hot?.dispose(() => {
	worker?.terminate();
	worker = null;
	supersedeAwaited();
});
