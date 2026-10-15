import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SEEK_PLAYBACK_LABEL } from '$lib/constants';
import { formatTime } from '$lib/utils/format';
import { laidOutSeekLine, pointerOnSeekLine, shownSeekTime } from '$lib/test-utils/seek-line';
import SeekSlider from './SeekSlider.svelte';

const SONG_SECONDS = 180;

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.restoreAllMocks();
});

async function renderSeek(currentTime = 0) {
	const onSeek = vi.fn();
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SeekSlider, {
		target,
		props: { currentTime, duration: SONG_SECONDS, formatTime, onSeek, size: 'full' }
	});
	await tick();
	return { line: laidOutSeekLine(target), onSeek };
}

function slider(): HTMLInputElement {
	const input = target.querySelector<HTMLInputElement>(
		`input[aria-label="${SEEK_PLAYBACK_LABEL}"]`
	);
	if (!input) throw new Error('Expected the seek slider');
	return input;
}

describe('SeekSlider', () => {
	it.each([
		{ where: 'three quarters along', fraction: 0.75, lands: 135 },
		{ where: 'at its start', fraction: 0, lands: 0 },
		{ where: 'before its start', fraction: -0.2, lands: 0 },
		{ where: 'past its end', fraction: 1.2, lands: SONG_SECONDS }
	])('a tap $where on the line of a 3:00 song plays from $lands s', async ({ fraction, lands }) => {
		const { line, onSeek } = await renderSeek();

		await pointerOnSeekLine(line, 'pointerdown', fraction);
		await pointerOnSeekLine(line, 'pointerup', fraction);

		expect(onSeek.mock.calls).toEqual([[lands]]);
	});

	it('shows where a drag will land and moves the song only on release', async () => {
		const { line, onSeek } = await renderSeek();

		await pointerOnSeekLine(line, 'pointerdown', 0.2);
		await pointerOnSeekLine(line, 'pointermove', 0.4);
		const whileDragging = { shown: shownSeekTime(target), seeks: onSeek.mock.calls.length };
		await pointerOnSeekLine(line, 'pointerup', 0.4);

		expect(whileDragging).toEqual({ shown: '1:12', seeks: 0 });
		expect({ shown: shownSeekTime(target), seeks: onSeek.mock.calls }).toEqual({
			shown: null,
			seeks: [[72]]
		});
	});

	it('leaves the song where it was when the browser takes the drag away', async () => {
		const { line, onSeek } = await renderSeek(30);

		await pointerOnSeekLine(line, 'pointerdown', 0.6);
		await pointerOnSeekLine(line, 'pointercancel', 0.6);

		expect({ shown: shownSeekTime(target), seeks: onSeek.mock.calls.length }).toEqual({
			shown: null,
			seeks: 0
		});
	});

	// jsdom does not step a range from the keyboard, so each row plays the
	// input event the browser sends once a key has moved the slider.
	it.each([
		{ key: 'an arrow key', value: '72.1', seeks: 72.1 },
		{ key: 'End', value: String(SONG_SECONDS), seeks: SONG_SECONDS },
		{ key: 'Home', value: '0', seeks: 0 }
	])('a step by $key seeks there at once', async ({ value, seeks }) => {
		const { onSeek } = await renderSeek(72);

		slider().value = value;
		slider().dispatchEvent(new Event('input', { bubbles: true }));

		expect(onSeek.mock.calls).toEqual([[seeks]]);
	});

	it('reads its position out as the time of the song', async () => {
		await renderSeek(72);

		expect(slider().getAttribute('aria-valuetext')).toBe('1:12 of 3:00');
	});
});
