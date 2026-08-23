import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { AlignmentRequest, AlignmentResult } from '$lib/services/lyricsAlignment';
import {
	NOW_PLAYING_LYRICS_UNSYNCED_NOTE,
	NOW_PLAYING_RESCORE_ACTION_LABEL
} from '$lib/constants/now-playing';
import { alignLyricsToCues } from '$lib/utils/lyrics-align';
import NowPlayingLyrics from './NowPlayingLyrics.svelte';

const EMPTY_LABEL = 'No lyrics for this take';

const LINE_1 = 'the lantern hums quietly tonight';
const LINE_2 = 'we count the fading city lights';

function cue(start: number, end: number, text: string): WhisperCue {
	return { start, end, text };
}

// One segment carrying word timestamps: a word every `secondsPerWord`
// seconds, as a take scored with word timestamps delivers them.
function sungCue(start: number, secondsPerWord: number, text: string): WhisperCue {
	const words = text.split(' ').map((word, index) => ({
		start: start + index * secondsPerWord,
		end: start + (index + 1) * secondsPerWord,
		text: word
	}));
	return { start: words[0].start, end: words[words.length - 1].end, text, words };
}

// Plays the part the browser's worker plays (#158): the same pure alignment,
// but delivered only once a test says the answer arrived. That is what lets a
// test see the take as it reads before it is aligned.
class FakeAlignmentWorker {
	static instance: FakeAlignmentWorker | null = null;
	private requests: AlignmentRequest[] = [];
	private readonly listeners: ((event: { data: AlignmentResult }) => void)[] = [];

	constructor() {
		FakeAlignmentWorker.instance = this;
	}

	addEventListener(type: string, listener: (event: { data: AlignmentResult }) => void): void {
		if (type === 'message') this.listeners.push(listener);
	}

	postMessage(request: AlignmentRequest): void {
		this.requests.push(request);
	}

	terminate(): void {}

	deliver(): void {
		const pending = this.requests;
		this.requests = [];
		for (const request of pending) {
			const lines = alignLyricsToCues(request.lyrics, request.cues);
			for (const listener of this.listeners) listener({ data: { id: request.id, lines } });
		}
	}
}

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

// jsdom has no scrollIntoView; define a no-op once so vi.spyOn has a real
// implementation to wrap, then restoreAllMocks can clean the spy up after
// each test without leaving the raw prototype assignment behind.
if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
	HTMLElement.prototype.scrollIntoView = () => {};
}

function stubScrollIntoView() {
	return vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {});
}

// jsdom does no layout, so a scroll box has to be given its measurements.
// Returns the scrollTop spy, the one metric a test moves.
function stubScrollBox(metrics: { scrollHeight: number; clientHeight: number }) {
	return {
		scrollHeight: vi
			.spyOn(Element.prototype, 'scrollHeight', 'get')
			.mockReturnValue(metrics.scrollHeight),
		clientHeight: vi
			.spyOn(Element.prototype, 'clientHeight', 'get')
			.mockReturnValue(metrics.clientHeight),
		scrollTop: vi.spyOn(Element.prototype, 'scrollTop', 'get').mockReturnValue(0)
	};
}

// Lets a test play the part the browser plays: the box changed size, here is
// the callback again. Returns a trigger for every observer the component made.
function stubResizeObserver(): () => void {
	const callbacks: ResizeObserverCallback[] = [];
	vi.stubGlobal(
		'ResizeObserver',
		class {
			constructor(callback: ResizeObserverCallback) {
				callbacks.push(callback);
			}
			observe(): void {}
			unobserve(): void {}
			disconnect(): void {}
		}
	);
	return () => {
		for (const callback of callbacks) callback([], {} as ResizeObserver);
	};
}

function lyricsBox(): HTMLElement {
	const box = target.querySelector<HTMLElement>('.lyrics');
	if (!box) throw new Error('Expected the lyrics box');
	return box;
}

beforeEach(() => {
	vi.stubGlobal('Worker', FakeAlignmentWorker);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	audioPlayer.currentTime = 0;
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

async function mountLyrics(props: {
	lyrics: string | null;
	cues: WhisperCue[] | null;
	whisperText: string | null;
}) {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlayingLyrics, { target, props: { emptyLabel: EMPTY_LABEL, ...props } });
	await tick();
}

/** The take's alignment comes back from the worker and is rendered. */
async function settleAlignment() {
	FakeAlignmentWorker.instance?.deliver();
	await tick();
}

async function render(props: {
	lyrics: string | null;
	cues: WhisperCue[] | null;
	whisperText: string | null;
}) {
	await mountLyrics(props);
	await settleAlignment();
}

describe('NowPlayingLyrics', () => {
	it('shows the named empty state when there are no lyrics', async () => {
		await render({ lyrics: null, cues: null, whisperText: null });

		expect(target.textContent).toContain(EMPTY_LABEL);
		expect(target.querySelector('.lyrics')).toBeNull();
	});

	it('renders static lyrics when there are no cues', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		await render({ lyrics, cues: null, whisperText: null });

		expect(target.querySelector('.lyrics')?.textContent).toContain(LINE_1);
		expect(target.querySelector('.lyrics-line')).toBeNull();
	});

	it('renders static lyrics when cues is an empty array', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		await render({ lyrics, cues: [], whisperText: null });

		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics')?.textContent).toContain(LINE_1);
	});

	it('names the unsynced state only when a transcript exists without cues', async () => {
		const lyrics = LINE_1;
		await render({ lyrics, cues: null, whisperText: 'a rough transcript' });
		expect(target.textContent).toContain(NOW_PLAYING_LYRICS_UNSYNCED_NOTE);
	});

	it('stops naming the unsynced state once cues exist', async () => {
		const lyrics = LINE_1;
		await render({ lyrics, cues: [cue(0, 1, LINE_1)], whisperText: 'a rough transcript' });
		expect(target.textContent).not.toContain(NOW_PLAYING_LYRICS_UNSYNCED_NOTE);
	});

	it('stays silent about syncing without a transcript either', async () => {
		await render({ lyrics: LINE_1, cues: null, whisperText: null });
		expect(target.textContent).not.toContain(NOW_PLAYING_LYRICS_UNSYNCED_NOTE);
	});

	it('never asks the reader to re-score, having no take to act on', async () => {
		// The panel also renders for a public share listener, who cannot
		// re-score anything — NowPlayingTake owns that action.
		await render({ lyrics: LINE_1, cues: null, whisperText: 'a rough transcript' });
		expect(target.textContent).not.toContain(NOW_PLAYING_RESCORE_ACTION_LABEL);
		expect(target.querySelector('button')).toBeNull();
	});

	it('reads the take as plain lyrics until the alignment comes back', async () => {
		// #158: aligning a take costs a few hundred milliseconds, so it happens
		// off the main thread. Until its answer arrives the lyrics are simply
		// text — no line is highlighted, and none is claimed to be sung.
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2)];
		audioPlayer.currentTime = 1.5;

		await mountLyrics({ lyrics, cues, whisperText: null });
		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics-text')?.textContent).toBe(lyrics);

		await settleAlignment();
		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('highlights the line whose cue interval covers the current playback time', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2)];
		audioPlayer.currentTime = 1.5;

		await render({ lyrics, cues, whisperText: null });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[0].classList.contains('active')).toBe(false);
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('highlights each line at its own words when one segment covers both', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [sungCue(0, 0.5, `${LINE_1} ${LINE_2}`)];
		audioPlayer.currentTime = 3;

		await render({ lyrics, cues, whisperText: null });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[0].classList.contains('active')).toBe(false);
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('highlights no line while playback is in a gap between cues', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(2, 3, LINE_2)];
		audioPlayer.currentTime = 1.5;

		await render({ lyrics, cues, whisperText: null });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(Array.from(lines).some((line) => line.classList.contains('active'))).toBe(false);
	});

	it('lights every line of a cue window at once', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 6.3, `${LINE_1} ${LINE_2}`)];
		audioPlayer.currentTime = 3;

		await render({ lyrics, cues, whisperText: null });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(Array.from(lines).map((line) => line.classList.contains('active'))).toEqual([
			true,
			true
		]);
	});

	it('fades its bottom edge while more lyrics follow below the visible box', async () => {
		// #163/8: docked beside the workspace the box is far shorter than the
		// lyrics, and a hard cut through the middle of a line reads as broken
		// text rather than as "scroll for the rest".
		stubScrollBox({ scrollHeight: 600, clientHeight: 200 });
		await render({ lyrics: [LINE_1, LINE_2].join('\n'), cues: null, whisperText: null });

		expect(lyricsBox().classList.contains('more-below')).toBe(true);
	});

	it('drops the fade once the last line has been scrolled to', async () => {
		const scrollBox = stubScrollBox({ scrollHeight: 600, clientHeight: 200 });
		await render({ lyrics: [LINE_1, LINE_2].join('\n'), cues: null, whisperText: null });

		scrollBox.scrollTop.mockReturnValue(400);
		lyricsBox().dispatchEvent(new Event('scroll'));
		await tick();

		expect(lyricsBox().classList.contains('more-below')).toBe(false);
	});

	it('re-measures when the box changes size, without waiting for a scroll', async () => {
		// #163/8 review: docking, expanding or collapsing Now Playing resizes
		// the box without remounting it. A fade measured once would stay over
		// text that now fits, or leave a fresh cut edge unmarked.
		const scrollBox = stubScrollBox({ scrollHeight: 600, clientHeight: 200 });
		const resize = stubResizeObserver();
		await render({ lyrics: [LINE_1, LINE_2].join('\n'), cues: null, whisperText: null });
		expect(lyricsBox().classList.contains('more-below')).toBe(true);

		scrollBox.clientHeight.mockReturnValue(600);
		resize();
		await tick();
		expect(lyricsBox().classList.contains('more-below')).toBe(false);

		scrollBox.clientHeight.mockReturnValue(200);
		resize();
		await tick();
		expect(lyricsBox().classList.contains('more-below')).toBe(true);
	});

	it('never fades lyrics that fit', async () => {
		stubScrollBox({ scrollHeight: 200, clientHeight: 200 });
		await render({ lyrics: LINE_1, cues: null, whisperText: null });

		expect(lyricsBox().classList.contains('more-below')).toBe(false);
	});

	it("keeps the take's own line breaks in unsynced lyrics", async () => {
		await render({ lyrics: [LINE_1, LINE_2].join('\n'), cues: null, whisperText: null });

		expect(target.querySelector('.lyrics-text')?.textContent).toBe([LINE_1, LINE_2].join('\n'));
	});

	it('scrolls the active line into view, smoothly by default', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2)];
		const scrollIntoView = stubScrollIntoView();
		vi.stubGlobal(
			'matchMedia',
			vi.fn(() => ({ matches: false }))
		);
		audioPlayer.currentTime = 0.5;

		await render({ lyrics, cues, whisperText: null });
		await tick();

		expect(scrollIntoView).toHaveBeenCalledWith(
			expect.objectContaining({ block: 'nearest', behavior: 'smooth' })
		);
	});

	it('scrolls the active line instantly when prefers-reduced-motion is set', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2)];
		const scrollIntoView = stubScrollIntoView();
		vi.stubGlobal(
			'matchMedia',
			vi.fn(() => ({ matches: true }))
		);
		audioPlayer.currentTime = 0.5;

		await render({ lyrics, cues, whisperText: null });
		await tick();

		expect(scrollIntoView).toHaveBeenCalledWith(
			expect.objectContaining({ block: 'nearest', behavior: 'auto' })
		);
	});
});
