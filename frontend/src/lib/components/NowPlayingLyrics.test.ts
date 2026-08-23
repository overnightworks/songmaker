import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import {
	NOW_PLAYING_LYRICS_UNSYNCED_NOTE,
	NOW_PLAYING_RESCORE_ACTION_LABEL
} from '$lib/constants/now-playing';
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

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	audioPlayer.currentTime = 0;
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

async function render(props: {
	lyrics: string | null;
	cues: WhisperCue[] | null;
	whisperText: string | null;
}) {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlayingLyrics, { target, props: { emptyLabel: EMPTY_LABEL, ...props } });
	await tick();
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
