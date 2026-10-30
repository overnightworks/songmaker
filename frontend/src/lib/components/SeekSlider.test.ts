import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SEEK_PLAYBACK_LABEL } from '#lib/constants.ts';
import { formatTime } from '#lib/utils/format.ts';
import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';
import { laidOutSeekLine, pointerOnSeekLine, shownSeekTime } from '#lib/test-utils/seek-line.ts';
import SeekSlider from './SeekSlider.svelte';
import seekSliderSource from './SeekSlider.svelte?raw';

const SONG_SECONDS = 180;

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	clearComponentStyles();
	vi.restoreAllMocks();
});

async function renderSeek(currentTime = 0, duration = SONG_SECONDS) {
	const onSeek = vi.fn();
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SeekSlider, {
		target,
		props: { currentTime, duration, formatTime, onSeek, size: 'full' }
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

	it('a tap does nothing while the song has no length yet', async () => {
		const { line, onSeek } = await renderSeek(0, 0);

		await pointerOnSeekLine(line, 'pointerdown', 0.5);
		await pointerOnSeekLine(line, 'pointerup', 0.5);

		expect({ shown: shownSeekTime(target), seeks: onSeek.mock.calls.length }).toEqual({
			shown: null,
			seeks: 0
		});
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

	it.each([
		{ key: 'ArrowRight', from: 72, seeks: 77 },
		{ key: 'ArrowUp', from: 72, seeks: 77 },
		{ key: 'ArrowLeft', from: 72, seeks: 67 },
		{ key: 'ArrowDown', from: 72, seeks: 67 },
		{ key: 'PageUp', from: 72, seeks: 102 },
		{ key: 'PageDown', from: 72, seeks: 42 },
		{ key: 'ArrowLeft', from: 3, seeks: 0 },
		{ key: 'PageUp', from: 170, seeks: SONG_SECONDS },
		{ key: 'Home', from: 72, seeks: 0 },
		{ key: 'End', from: 72, seeks: SONG_SECONDS }
	])('$key at $from s plays from $seeks s at once', async ({ key, from, seeks }) => {
		const { onSeek } = await renderSeek(from);

		slider().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));

		expect(onSeek.mock.calls).toEqual([[seeks]]);
	});

	// jsdom does not step a range the way a screen reader's swipe does, so the
	// row plays the input event the browser sends once the swipe moved it.
	it("a screen reader's step seeks where it set the slider", async () => {
		const { onSeek } = await renderSeek(72);

		slider().value = '75';
		slider().dispatchEvent(new Event('input', { bubbles: true }));

		expect(onSeek.mock.calls).toEqual([[75]]);
	});

	it('fills the played part of the line in the action colour, --accent (#924)', async () => {
		await renderSeek(72);
		const played = target.querySelector<HTMLElement>('.seek-played');
		if (!played) throw new Error('Expected the played part of the line');

		injectComponentStyles(seekSliderSource, 'SeekSlider.svelte', played);

		expect(getComputedStyle(played).background).toBe('var(--accent)');
	});

	it('reads its position out as the time of the song', async () => {
		await renderSeek(72);

		expect(slider().getAttribute('aria-valuetext')).toBe('1:12 of 3:00');
	});
});
