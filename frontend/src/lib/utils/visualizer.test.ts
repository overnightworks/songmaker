import { afterEach, describe, expect, it, vi } from 'vitest';

import { AudioVisualizer, playbackVisualizerAllowed, type VizColors } from './visualizer';

const colors: VizColors = { pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 };

interface DrawnPath {
	points: Array<[number, number]>;
}

function fakeCanvas(
	width = 120,
	height = 48
): {
	canvas: HTMLCanvasElement;
	clearAreas: Array<[number, number, number, number]>;
	filledBars: Array<[number, number, number, number]>;
	particleCircles: Array<[number, number, number]>;
	strokedPaths: DrawnPath[];
	transforms: Array<[number, number, number, number, number, number]>;
} {
	const clearAreas: Array<[number, number, number, number]> = [];
	const filledBars: Array<[number, number, number, number]> = [];
	const particleCircles: Array<[number, number, number]> = [];
	const strokedPaths: DrawnPath[] = [];
	const transforms: Array<[number, number, number, number, number, number]> = [];
	let activePath: DrawnPath = { points: [] };
	const context = {
		globalAlpha: 1,
		fillStyle: '',
		strokeStyle: '',
		lineWidth: 1,
		shadowColor: '',
		shadowBlur: 0,
		setTransform: (...values: [number, number, number, number, number, number]) =>
			transforms.push(values),
		clearRect: (...area: [number, number, number, number]) => clearAreas.push(area),
		fillRect: (...area: [number, number, number, number]) => filledBars.push(area),
		beginPath: () => {
			activePath = { points: [] };
		},
		moveTo: (x: number, y: number) => activePath.points.push([x, y]),
		lineTo: (x: number, y: number) => activePath.points.push([x, y]),
		closePath: () => {},
		stroke: () => strokedPaths.push({ points: [...activePath.points] }),
		save: () => {},
		restore: () => {},
		arc: (x: number, y: number, radius: number) => particleCircles.push([x, y, radius]),
		fill: () => {}
	} as unknown as CanvasRenderingContext2D;
	const canvas = document.createElement('canvas');
	vi.spyOn(canvas, 'getContext').mockReturnValue(context);
	vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ width, height } as DOMRect);

	return { canvas, clearAreas, filledBars, particleCircles, strokedPaths, transforms };
}

function analyserWith(frequencyValue: number): AnalyserNode {
	return {
		getByteFrequencyData: (data: Uint8Array) => data.fill(frequencyValue),
		getByteTimeDomainData: (data: Uint8Array) => data.fill(128)
	} as unknown as AnalyserNode;
}

function stubMedia(narrow: boolean, coarse: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches:
				query === '(max-width: 640px)' ? narrow : query === '(any-pointer: coarse)' && coarse,
			media: query,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn()
		}))
	);
}

afterEach(() => {
	document.documentElement.removeAttribute('data-pointer');
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe('playbackVisualizerAllowed', () => {
	it('stays off when browser globals are unavailable', () => {
		vi.stubGlobal('window', undefined);

		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it.each([
		['a narrow viewport', true, false],
		['a coarse pointer', false, true]
	])('keeps Web Audio off for %s', (_label, narrow, coarse) => {
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		stubMedia(narrow, coarse);

		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it('keeps Web Audio off for the app coarse-pointer override and hidden documents', () => {
		stubMedia(false, false);
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		document.documentElement.dataset.pointer = 'coarse';
		expect(playbackVisualizerAllowed()).toBe(false);

		document.documentElement.removeAttribute('data-pointer');
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it('allows Web Audio only on a visible wide fine-pointer device', () => {
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		stubMedia(false, false);

		expect(playbackVisualizerAllowed()).toBe(true);
	});
});

describe('AudioVisualizer', () => {
	it('resizes for device pixels and draws frequency bars and waveforms across the visible canvas', () => {
		Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 });
		const drawing = fakeCanvas(100.4, 40.3);
		const energy = vi.fn();
		const visualizer = new AudioVisualizer();

		visualizer.startLoop(
			drawing.canvas,
			analyserWith(255),
			new Uint8Array(32),
			new Uint8Array(32),
			colors,
			energy
		);
		visualizer.destroy();

		expect(drawing.canvas).toMatchObject({ width: 201, height: 81 });
		expect(drawing.transforms).toContainEqual([2, 0, 0, 2, 0, 0]);
		expect(drawing.filledBars).toHaveLength(32);
		expect(
			drawing.filledBars.every(
				([x, _y, barWidth, barHeight]) => x >= 0 && x < 100.4 && barWidth > 0 && barHeight > 0
			)
		).toBe(true);
		const waveformPaths = drawing.strokedPaths.filter((path) => path.points.length === 32);
		expect(waveformPaths).toHaveLength(3);
		expect(
			waveformPaths.every((path) => {
				const xCoordinates = path.points.map(([x]) => x);
				return Math.min(...xCoordinates) === 0 && Math.max(...xCoordinates) > 90;
			})
		).toBe(true);
		expect(energy).toHaveBeenCalledWith(expect.closeTo(0.2), expect.closeTo(0.2));
	});

	it('shows particles only when a bass hit begins', () => {
		const drawing = fakeCanvas();
		const visualizer = new AudioVisualizer();
		vi.spyOn(Math, 'random').mockReturnValue(0.5);

		for (let frame = 0; frame < 3; frame++) {
			visualizer.drawFrame(
				drawing.canvas,
				analyserWith(255),
				new Uint8Array(32),
				new Uint8Array(32),
				colors
			);
		}

		expect(drawing.particleCircles).toHaveLength(14);
		expect(drawing.particleCircles.every(([_x, _y, radius]) => radius > 0)).toBe(true);
	});

	it('runs one frame loop and clears its rendered result after stopping fades it out', () => {
		const drawing = fakeCanvas(80, 30);
		const scheduledFrames = new Map<number, FrameRequestCallback>();
		let nextFrameId = 1;
		vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
			const frameId = nextFrameId++;
			scheduledFrames.set(frameId, callback);
			return frameId;
		});
		vi.stubGlobal('cancelAnimationFrame', (frameId: number) => scheduledFrames.delete(frameId));
		const visualizer = new AudioVisualizer();

		visualizer.startLoop(
			drawing.canvas,
			analyserWith(100),
			new Uint8Array(32),
			new Uint8Array(32),
			colors
		);
		visualizer.startLoop(
			drawing.canvas,
			analyserWith(100),
			new Uint8Array(32),
			new Uint8Array(32),
			colors
		);

		expect(scheduledFrames.size).toBe(1);
		visualizer.stopLoop(drawing.canvas);
		for (let step = 0; scheduledFrames.size > 0 && step < 30; step++) {
			const [frameId, callback] = scheduledFrames.entries().next().value as [
				number,
				FrameRequestCallback
			];
			scheduledFrames.delete(frameId);
			callback(0);
		}

		expect(scheduledFrames.size).toBe(0);
		expect(drawing.clearAreas).toContainEqual([0, 0, drawing.canvas.width, drawing.canvas.height]);
	});
});
