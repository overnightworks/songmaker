import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatTime } from '#lib/utils/format.ts';
import { clearComponentStyles, injectComponentStyles } from '#lib/test-utils/component-styles.ts';
import { laidOutSeekLine, pointerOnSeekLine, shownSeekTime } from '#lib/test-utils/seek-line.ts';
import { followingGlowSnippet } from '#lib/test-utils/glow-snippet.svelte.ts';
import { reactiveProps } from '../../tests/reactive-fixtures.svelte';
import TransportBarFrame from './TransportBarFrame.svelte';
import transportBarFrameSource from './TransportBarFrame.svelte?raw';

let component: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	clearComponentStyles();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
	document.documentElement.removeAttribute('style');
});

async function mountDesktopFrame({
	takeIsCurrent,
	duration = 0,
	onSeek = () => {}
}: {
	takeIsCurrent: boolean;
	duration?: number;
	onSeek?: (seconds: number) => void;
}): Promise<HTMLElement> {
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	const target = document.createElement('div');
	document.body.appendChild(target);
	component = mount(TransportBarFrame, {
		target,
		props: {
			transport: 'paused',
			takeIsCurrent,
			currentTime: 0,
			duration,
			formatTime,
			canPrev: false,
			canNext: false,
			onPrev: () => {},
			onNext: () => {},
			onTogglePlay: () => {},
			onSeek,
			trackInfo: createRawSnippet(() => ({ render: () => '<span>Nachtstrom</span>' })),
			nowPlayingOpen: false,
			onOpenNowPlaying: () => {},
			nowPlayingDisabled: true,
			mobileTransport: false
		}
	});
	await tick();
	return target;
}

describe('TransportBarFrame time readouts (#1312)', () => {
	it.each([
		{ moment: 'a take is current', takeIsCurrent: true, readouts: ['0:00', '0:00'], seek: true },
		{ moment: 'no take is current', takeIsCurrent: false, readouts: [], seek: false }
	])('shows the position only while $moment', async ({ takeIsCurrent, readouts, seek }) => {
		const target = await mountDesktopFrame({ takeIsCurrent });

		expect({
			readouts: Array.from(target.querySelectorAll('.timeline .time'), (el) => el.textContent),
			seek: target.querySelector('[aria-label="Seek playback"]') !== null
		}).toEqual({ readouts, seek });
	});
});

describe('TransportBarFrame seek line (#1382)', () => {
	it('shows the time above the pointer while dragging and moves the song on release', async () => {
		const onSeek = vi.fn();
		const target = await mountDesktopFrame({ takeIsCurrent: true, duration: 180, onSeek });
		const line = laidOutSeekLine(target);

		await pointerOnSeekLine(line, 'pointerdown', 0.1);
		await pointerOnSeekLine(line, 'pointermove', 0.4);
		const whileDragging = { shown: shownSeekTime(target), seeks: onSeek.mock.calls.length };
		await pointerOnSeekLine(line, 'pointerup', 0.4);

		expect({ whileDragging, seeks: onSeek.mock.calls }).toEqual({
			whileDragging: { shown: '1:12', seeks: 0 },
			seeks: [[72]]
		});
	});
});

describe('TransportBarFrame play button (#924)', () => {
	it('paints Play in the action colour, --accent, with the ink that reads on it', async () => {
		const target = await mountDesktopFrame({ takeIsCurrent: true });
		const play = target.querySelector<HTMLElement>('.play-btn');
		if (!play) throw new Error('Expected the play button');

		injectComponentStyles(transportBarFrameSource, 'TransportBarFrame.svelte', play);
		const style = getComputedStyle(play);

		expect({ fill: style.background, ink: style.color }).toEqual({
			fill: 'var(--accent)',
			ink: 'var(--on-accent)'
		});
	});
});

describe('TransportBarFrame title glow colours (#1966)', () => {
	function setVizAccent(red: number, green: number, blue: number): void {
		const root = document.documentElement;
		root.style.setProperty('--viz-accent-r', String(red));
		root.style.setProperty('--viz-accent-g', String(green));
		root.style.setProperty('--viz-accent-b', String(blue));
	}

	async function mountGlowFrame(transport: 'paused' | 'playing') {
		vi.stubGlobal('matchMedia', (query: string) => ({ matches: true, media: query }));
		const target = document.createElement('div');
		document.body.appendChild(target);
		const props = reactiveProps({
			transport,
			takeIsCurrent: true,
			currentTime: 0,
			duration: 0,
			formatTime,
			canPrev: false,
			canNext: false,
			onPrev: () => {},
			onNext: () => {},
			onTogglePlay: () => {},
			onSeek: () => {},
			trackInfo: followingGlowSnippet(),
			nowPlayingOpen: false,
			onOpenNowPlaying: () => {},
			nowPlayingDisabled: true,
			mobileTransport: true
		});
		component = mount(TransportBarFrame, { target, props });
		await tick();
		return { props, glow: () => target.querySelector<HTMLElement>('.glow')?.dataset.style };
	}

	it('tints the playing title glow from the --viz-accent tokens when the visualizer loop never starts', async () => {
		setVizAccent(122, 24, 192);

		const { glow } = await mountGlowFrame('playing');

		expect(glow()).toContain('122, 24, 192');
	});

	it('picks up a theme switch that happened while paused once playback starts', async () => {
		setVizAccent(10, 20, 30);
		const { props, glow } = await mountGlowFrame('paused');

		setVizAccent(122, 24, 192);
		props.transport = 'playing';
		await tick();

		expect(glow()).toContain('122, 24, 192');
	});
});
