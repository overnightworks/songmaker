import { flushSync, mount, unmount } from 'svelte';
import { theme } from '$lib/stores/ui';
import { afterEach, expect, it, vi } from 'vitest';
import WaveformRangePicker from './WaveformRangePicker.svelte';

let picker: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (picker) await unmount(picker);
	picker = undefined;
	document.body.replaceChildren();
	document.documentElement.removeAttribute('style');
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

it.each([
	{ status: 200, height: 60 },
	{ status: 401, height: 6 },
	{ status: 429, height: 6 },
	{ status: 503, height: 6 }
])('925_M2_M4: media status $status draws bars of height $height', async ({ status, height }) => {
	const bars: number[] = [];
	let requestedUrl: string | undefined;
	let decodedBytes: ArrayBuffer | undefined;
	const context = {
		scale: () => undefined,
		clearRect: () => {
			bars.length = 0;
		},
		fillRect: (_x: number, _y: number, _width: number, barHeight: number) => bars.push(barHeight),
		fillStyle: ''
	};
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
		context as unknown as CanvasRenderingContext2D
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get').mockReturnValue(64);
	vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
	vi.stubGlobal('fetch', async (url: string) => {
		requestedUrl = url;
		return new Response(new Uint8Array([1, 2, 3]), { status });
	});
	vi.stubGlobal(
		'AudioContext',
		class {
			async decodeAudioData(bytes: ArrayBuffer) {
				decodedBytes = bytes;
				return { getChannelData: () => new Float32Array(300).fill(1) };
			}
			async close() {}
		}
	);
	picker = mount(WaveformRangePicker, {
		target: document.body,
		props: {
			audioUrl: '/audio/waveform',
			duration: 10,
			startPercent: 0,
			endPercent: 1,
			onchange: () => undefined
		}
	});
	await vi.waitFor(() => expect(bars).toEqual(Array(300).fill(height)));
	expect(requestedUrl).toBe('/audio/waveform');
	expect(decodedBytes ? [...new Uint8Array(decodedBytes)] : null).toEqual(
		status === 200 ? [1, 2, 3] : null
	);
});

it.each([
	{ seconds: 1.996, shown: '0:02.00' },
	{ seconds: 61.5, shown: '1:01.50' }
])('shows $seconds s as $shown', ({ seconds, shown }) => {
	picker = mount(WaveformRangePicker, {
		target: document.body,
		props: {
			audioUrl: '/audio/waveform',
			duration: seconds,
			startPercent: 1,
			endPercent: 1,
			onchange: () => undefined
		}
	});

	expect(document.body.textContent).toContain(shown);
});

it('draws the bars in the accent of the active theme and redraws on a theme switch', async () => {
	const fills = new Set<string>();
	const context = {
		scale: () => undefined,
		clearRect: () => undefined,
		fillRect: () => undefined,
		set fillStyle(value: string) {
			fills.add(value);
		}
	};
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
		context as unknown as CanvasRenderingContext2D
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get').mockReturnValue(64);
	vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
	vi.stubGlobal('fetch', async () => new Response(new Uint8Array([1]), { status: 503 }));
	document.documentElement.style.setProperty('--viz-accent-r', '10');
	document.documentElement.style.setProperty('--viz-accent-g', '20');
	document.documentElement.style.setProperty('--viz-accent-b', '30');
	picker = mount(WaveformRangePicker, {
		target: document.body,
		props: {
			audioUrl: '/audio/waveform',
			duration: 10,
			startPercent: 0,
			endPercent: 0.5,
			onchange: () => undefined
		}
	});
	await vi.waitFor(() =>
		expect(fills).toEqual(new Set(['rgba(10, 20, 30, 0.8)', 'rgba(10, 20, 30, 0.2)']))
	);

	fills.clear();
	document.documentElement.style.setProperty('--viz-accent-r', '40');
	theme.update((current) => (current === 'dark' ? 'light' : 'dark'));
	flushSync();
	expect(fills).toContain('rgba(40, 20, 30, 0.8)');
});
