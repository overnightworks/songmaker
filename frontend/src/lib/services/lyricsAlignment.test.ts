import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import { alignLyricsToCues, type AlignedLyricLine } from '$lib/utils/lyrics-align';
import type { AlignmentRequest, AlignmentResult } from './lyricsAlignment';

const LYRICS = ['the lantern hums quietly tonight', 'we count the fading city lights'].join('\n');
const CUES: WhisperCue[] = [
	{ start: 0, end: 1, text: 'the lantern hums quietly tonight' },
	{ start: 1, end: 2, text: 'we count the fading city lights' }
];
const WORKER_LINES: AlignedLyricLine[] = [
	{ text: 'answered by the worker', interval: { start: 0, end: 1 } }
];

// Stands in for the real worker: records what it was asked and lets the test
// decide when — and whether — an answer comes back.
class FakeAlignmentWorker {
	static latest: FakeAlignmentWorker | null = null;
	readonly requests: AlignmentRequest[] = [];
	private readonly listeners = new Map<string, ((event: unknown) => void)[]>();

	constructor() {
		FakeAlignmentWorker.latest = this;
	}

	addEventListener(type: string, listener: (event: unknown) => void): void {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	postMessage(request: AlignmentRequest): void {
		this.requests.push(request);
	}

	terminate(): void {}

	answer(result: AlignmentResult): void {
		this.emit('message', { data: result });
	}

	fail(message: string): void {
		this.emit('error', { message });
	}

	private emit(type: string, event: unknown): void {
		for (const listener of this.listeners.get(type) ?? []) listener(event);
	}
}

function workingWorker(): FakeAlignmentWorker {
	const worker = FakeAlignmentWorker.latest;
	if (!worker) throw new Error('Expected the service to have started a worker');
	return worker;
}

// The service keeps one worker and one in-flight take per module instance, so
// each test starts from a fresh copy of it.
async function loadService(withWorker: boolean) {
	FakeAlignmentWorker.latest = null;
	vi.stubGlobal('Worker', withWorker ? FakeAlignmentWorker : undefined);
	vi.resetModules();
	return await import('./lyricsAlignment');
}

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('alignInWorker', () => {
	it('aligns the take with the same pure function when the platform has no worker', async () => {
		const { alignInWorker } = await loadService(false);

		await expect(alignInWorker(LYRICS, CUES)).resolves.toEqual(alignLyricsToCues(LYRICS, CUES));
	});

	it('resolves with the lines the worker sends back for the take it was given', async () => {
		const { alignInWorker } = await loadService(true);

		const aligned = alignInWorker(LYRICS, CUES);
		const [request] = workingWorker().requests;
		expect(request).toMatchObject({ lyrics: LYRICS, cues: CUES });
		workingWorker().answer({ id: request.id, lines: WORKER_LINES });

		await expect(aligned).resolves.toEqual(WORKER_LINES);
	});

	it('settles a superseded take with no lines and answers only the latest one', async () => {
		const { alignInWorker } = await loadService(true);

		const superseded = alignInWorker(LYRICS, CUES);
		const latest = alignInWorker(LYRICS, CUES.slice(0, 1));
		const worker = workingWorker();
		expect(worker.requests).toHaveLength(2);

		worker.answer({ id: worker.requests[0].id, lines: WORKER_LINES });
		await expect(superseded).resolves.toBeNull();

		worker.answer({ id: worker.requests[1].id, lines: WORKER_LINES });
		await expect(latest).resolves.toEqual(WORKER_LINES);
	});

	it('reuses the one worker across takes', async () => {
		const { alignInWorker } = await loadService(true);

		alignInWorker(LYRICS, CUES);
		const first = workingWorker();
		alignInWorker(LYRICS, CUES);

		expect(workingWorker()).toBe(first);
	});

	it('rejects the take in flight when the worker fails', async () => {
		const { alignInWorker } = await loadService(true);

		const aligned = alignInWorker(LYRICS, CUES);
		workingWorker().fail('boom');

		await expect(aligned).rejects.toThrow('boom');
	});
});
