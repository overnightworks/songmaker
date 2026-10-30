import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import type { WhisperCue } from '#lib/api/types.ts';
import type { AlignmentRequest, AlignmentResult } from '#lib/services/lyricsAlignment.svelte.ts';
import { NOW_PLAYING_LYRICS_FOLLOW_LABEL } from '#lib/constants.ts';
import {
	NOW_PLAYING_LYRICS_UNSYNCED_NOTE,
	NOW_PLAYING_RESCORE_ACTION_LABEL
} from '#lib/constants/now-playing.ts';
import { alignLyricsToCues } from '#lib/utils/lyrics-align.ts';
import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';
import { reactiveProps } from '../../tests/reactive-fixtures.svelte';
import NowPlayingLyrics from './NowPlayingLyrics.svelte';
import nowPlayingLyricsSource from './NowPlayingLyrics.svelte?raw';

const EMPTY_LABEL = 'No lyrics for this take';

const LINE_1 = 'the lantern hums quietly tonight';
const LINE_2 = 'we count the fading city lights';
const LINE_3 = 'and the river keeps our names';

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
// test see the take as it reads before it is aligned. Requests are
// structured-cloned exactly as the browser clones them, so a take that could
// not cross the worker boundary fails here too.
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
		this.requests.push(structuredClone(request));
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
let live: MountedLyricsProps;

// jsdom has no scrollTo on elements; define a no-op once so vi.spyOn has a
// real implementation to wrap, then restoreAllMocks can clean the spy up
// after each test without leaving the raw prototype assignment behind.
if (typeof HTMLElement.prototype.scrollTo !== 'function') {
	HTMLElement.prototype.scrollTo = () => {};
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

// Three lines sung one second each, so the time names the sung line.
function syncedTake(): LyricsProps {
	return {
		lyrics: [LINE_1, LINE_2, LINE_3].join('\n'),
		cues: [cue(0, 1, LINE_1), cue(1, 2, LINE_2), cue(2, 3, LINE_3)],
		whisperText: null
	};
}

// jsdom lays nothing out, so the box is given the shape a browser gives it:
// 200 px tall with its last 40 px faded, each line 100 px below the one
// before and moved up by however far the box is scrolled. Unscrolled, the
// third line ends 70 px below the readable part.
const LINE_3_BELOW_VIEW_PX = 70;

function layOutSyncedLyrics(reducedMotion = false) {
	const { scrollTop } = stubScrollBox({ scrollHeight: 600, clientHeight: 200 });
	vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
		const index = this.getAttribute('data-line-index');
		if (index === null) return { top: 0, bottom: 200 } as DOMRect;
		const top = Number(index) * 100 - (this.parentElement?.scrollTop ?? 0);
		return { top, bottom: top + 30 } as DOMRect;
	});
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: reducedMotion }))
	);
	const scrolls = vi.spyOn(HTMLElement.prototype, 'scrollTo').mockImplementation(() => {});
	return { scrolls, scrollTop };
}

// Where each scroll the box made was sent, in order.
function scrollTargets(scrolls: MockInstance<HTMLElement['scrollTo']>): number[] {
	return scrolls.mock.calls.map(([options]) => (options as ScrollToOptions).top ?? 0);
}

// The box reports a scroll at every position it passes, as a browser does --
// whether the box sent itself there or the reader dragged its scrollbar.
async function scrollBoxThrough(scrollTop: MockInstance<() => number>, positions: number[]) {
	for (const position of positions) {
		scrollTop.mockReturnValue(position);
		lyricsBox().dispatchEvent(new Event('scroll'));
	}
	await tick();
}

async function singTo(seconds: number | null) {
	live.position = seconds;
	await tick();
}

function followButton(): HTMLButtonElement | null {
	const button = target.querySelector('button');
	return button?.textContent?.includes(NOW_PLAYING_LYRICS_FOLLOW_LABEL) ? button : null;
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
	clearComponentStyles();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

interface LyricsProps {
	lyrics: string | null;
	cues: WhisperCue[] | null;
	whisperText: string | null;
	// Where the take stands; a take the test does not place stands at its start.
	position?: number | null;
	songTitle?: string;
}

type MountedLyricsProps = Required<Omit<LyricsProps, 'songTitle'>> & {
	emptyLabel: string;
	songTitle?: string;
};

// Props the test can change afterwards, as the panel's own props change when
// the listener moves to another take.
async function mountLyrics(props: LyricsProps): Promise<MountedLyricsProps> {
	target = document.createElement('div');
	document.body.append(target);
	live = reactiveProps({ emptyLabel: EMPTY_LABEL, position: 0, ...props });
	mounted = mount(NowPlayingLyrics, { target, props: live });
	await tick();
	return live;
}

/** The take's alignment comes back from the worker and is rendered. */
async function settleAlignment() {
	FakeAlignmentWorker.instance?.deliver();
	await tick();
}

async function render(props: LyricsProps) {
	await mountLyrics(props);
	await settleAlignment();
}

describe('NowPlayingLyrics', () => {
	it('1374_rule_2 names the song in the heading when given one, else only Lyrics', async () => {
		await render({ lyrics: LINE_1, cues: null, whisperText: null, songTitle: 'Paper Lanterns' });
		expect(target.querySelector('.lyrics-heading')?.textContent).toBe('Lyrics · Paper Lanterns');
	});

	it('keeps the plain Lyrics heading without a song title', async () => {
		await render({ lyrics: LINE_1, cues: null, whisperText: null });
		expect(target.querySelector('.lyrics-heading')?.textContent).toBe('Lyrics');
	});

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
		await mountLyrics({ lyrics, cues, whisperText: null, position: 1.5 });
		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics-text')?.textContent).toBe(lyrics);

		await settleAlignment();
		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('keeps the take static when it loses its cues before the answer arrives', async () => {
		// Moving to an unscored take re-runs the effect without asking for a new
		// alignment, so nothing supersedes the one still in flight. Its answer
		// belongs to a take that is no longer showing.
		const lyrics = [LINE_1, LINE_2].join('\n');
		const live = await mountLyrics({ lyrics, cues: [cue(0, 1, LINE_1)], whisperText: null });

		live.cues = null;
		await tick();
		await settleAlignment();

		expect(target.querySelector('.lyrics-line')).toBeNull();
		expect(target.querySelector('.lyrics-text')?.textContent).toBe(lyrics);
	});

	it('highlights the line whose cue interval covers the current playback time', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2)];

		await render({ lyrics, cues, whisperText: null, position: 1.5 });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[0].classList.contains('active')).toBe(false);
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('highlights each line at its own words when one segment covers both', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [sungCue(0, 0.5, `${LINE_1} ${LINE_2}`)];

		await render({ lyrics, cues, whisperText: null, position: 3 });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(lines[0].classList.contains('active')).toBe(false);
		expect(lines[1].classList.contains('active')).toBe(true);
	});

	it('highlights no line while playback is in a gap between cues', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(2, 3, LINE_2)];

		await render({ lyrics, cues, whisperText: null, position: 1.5 });

		const lines = target.querySelectorAll('.lyrics-line');
		expect(Array.from(lines).some((line) => line.classList.contains('active'))).toBe(false);
	});

	it('lights no line while nothing is sung, though the first cue starts at 0:00', async () => {
		const { scrolls } = layOutSyncedLyrics();

		await render({ ...syncedTake(), position: null });

		expect({
			lines: target.querySelectorAll('.lyrics-line').length,
			lit: target.querySelectorAll('.lyrics-line.active').length,
			scrolls: scrolls.mock.calls.length
		}).toEqual({ lines: 3, lit: 0, scrolls: 0 });
	});

	it('lights every line of a cue window at once', async () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(0, 6.3, `${LINE_1} ${LINE_2}`)];

		await render({ lyrics, cues, whisperText: null, position: 3 });

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

	it.each([
		{ motion: 'by default', reduced: false, behavior: 'smooth' },
		{ motion: 'when prefers-reduced-motion is set', reduced: true, behavior: 'auto' }
	])(
		'scrolls the lyrics box to the sung line, $behavior $motion',
		async ({ reduced, behavior }) => {
			const { scrolls } = layOutSyncedLyrics(reduced);

			await render({ ...syncedTake(), position: 2.5 });

			expect(scrolls.mock.calls).toEqual([[{ top: LINE_3_BELOW_VIEW_PX, behavior }]]);
		}
	);

	it.each([
		{ gesture: 'the wheel', event: () => new WheelEvent('wheel', { bubbles: true }) },
		{ gesture: 'a finger', event: () => new Event('touchmove', { bubbles: true }) },
		{
			gesture: 'Page Up',
			event: () => new KeyboardEvent('keydown', { key: 'PageUp', bubbles: true })
		}
	])('stays where the reader scrolls it with $gesture and offers Follow', async ({ event }) => {
		const { scrolls } = layOutSyncedLyrics();
		await render(syncedTake());

		lyricsBox().dispatchEvent(event());
		await singTo(2.5);

		expect({ scrolls: scrolls.mock.calls.length, follow: followButton() !== null }).toEqual({
			scrolls: 0,
			follow: true
		});
	});

	// The box sends itself 70 px down to the third line; whatever the row
	// does there, the first line sung again sends it back up.
	it.each([
		{
			input: 'its own scroll to the sung line',
			act: (scrollTop: MockInstance<() => number>) =>
				scrollBoxThrough(scrollTop, [35, LINE_3_BELOW_VIEW_PX])
		},
		{
			input: 'a key that scrolls nothing',
			act: async (scrollTop: MockInstance<() => number>) => {
				await scrollBoxThrough(scrollTop, [LINE_3_BELOW_VIEW_PX]);
				lyricsBox().dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
			}
		}
	])('keeps following the song through $input', async ({ act }) => {
		const { scrolls, scrollTop } = layOutSyncedLyrics();
		await render(syncedTake());
		await singTo(2.5);

		await act(scrollTop);
		await singTo(0.5);

		expect({ scrolls: scrollTargets(scrolls), follow: followButton() !== null }).toEqual({
			scrolls: [LINE_3_BELOW_VIEW_PX, 0],
			follow: false
		});
	});

	// A dragged scrollbar fires no wheel, touch or key -- only the scrolls.
	it.each([
		{ where: 'before the box moved itself', startAt: 0.5, positions: [300], thenAt: 2.5 },
		{ where: 'past where the box sent itself', startAt: 2.5, positions: [300], thenAt: 0.5 },
		{
			where: 'back over the way the box came',
			startAt: 2.5,
			positions: [LINE_3_BELOW_VIEW_PX, 35],
			thenAt: 0.5
		}
	])(
		'stays where the reader drags its scrollbar $where and offers Follow',
		async ({ startAt, positions, thenAt }) => {
			const { scrolls, scrollTop } = layOutSyncedLyrics();
			await render({ ...syncedTake(), position: startAt });
			const scrollsBeforeDrag = scrolls.mock.calls.length;

			await scrollBoxThrough(scrollTop, positions);
			await singTo(thenAt);

			expect({
				scrolls: scrolls.mock.calls.length - scrollsBeforeDrag,
				follow: followButton() !== null
			}).toEqual({ scrolls: 0, follow: true });
		}
	);

	it('stays where it stood and lights no line once the song stops being sung', async () => {
		const { scrolls } = layOutSyncedLyrics();
		await render({ ...syncedTake(), position: 2.5 });

		await singTo(null);

		expect({
			scrolls: scrollTargets(scrolls),
			lit: target.querySelectorAll('.lyrics-line.active').length
		}).toEqual({ scrolls: [LINE_3_BELOW_VIEW_PX], lit: 0 });
	});

	it('Follow brings the sung line back and follows it again', async () => {
		const { scrolls } = layOutSyncedLyrics();
		await render(syncedTake());
		lyricsBox().dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
		await singTo(2.5);

		followButton()?.click();
		await tick();

		expect({ scrolls: scrolls.mock.calls, follow: followButton() !== null }).toEqual({
			scrolls: [[{ top: LINE_3_BELOW_VIEW_PX, behavior: 'smooth' }]],
			follow: false
		});
	});

	it('follows a new take again from its start', async () => {
		const { scrolls } = layOutSyncedLyrics();
		const live = await mountLyrics(syncedTake());
		await settleAlignment();
		lyricsBox().dispatchEvent(new WheelEvent('wheel', { bubbles: true }));

		live.lyrics = [LINE_3, LINE_2, LINE_1].join('\n');
		live.cues = [cue(0, 1, LINE_3), cue(1, 2, LINE_2), cue(2, 3, LINE_1)];
		await tick();
		await settleAlignment();
		await singTo(2.5);

		expect({ scrolls: scrolls.mock.calls.length, follow: followButton() !== null }).toEqual({
			scrolls: 1,
			follow: false
		});
	});

	it('writes Follow in the action colour, --accent (#924)', async () => {
		layOutSyncedLyrics();
		await render(syncedTake());
		lyricsBox().dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
		await tick();
		const follow = followButton();
		if (!follow) throw new Error('Expected Follow');

		injectComponentStyles(nowPlayingLyricsSource, 'NowPlayingLyrics.svelte', follow);

		expect(getComputedStyle(follow).color).toBe('var(--accent)');
	});

	it('offers Follow only for lyrics that follow the song, never for plain text', async () => {
		layOutSyncedLyrics();
		const live = await mountLyrics(syncedTake());
		await settleAlignment();
		lyricsBox().dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
		await tick();
		const timedOffersFollow = followButton() !== null;

		live.cues = null;
		await tick();
		lyricsBox().dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
		await tick();

		expect({ timedOffersFollow, plainOffersFollow: followButton() !== null }).toEqual({
			timedOffersFollow: true,
			plainOffersFollow: false
		});
	});
});
