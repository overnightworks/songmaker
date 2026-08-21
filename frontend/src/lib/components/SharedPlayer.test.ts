import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamTrackItem } from '$lib/api/types';
import SharedPlayer from './SharedPlayer.svelte';

class FakeAudio {
	private resolvedSrc = '';
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	private listeners = new Map<string, Array<(event: Event) => void>>();
	playMock = vi.fn(() => {
		this.paused = false;
		this.fire('play');
		return Promise.resolve();
	});
	pauseMock = vi.fn(() => {
		this.paused = true;
		this.fire('pause');
	});
	loadMock = vi.fn(() => this.fire('loadstart'));
	get src() {
		return this.resolvedSrc;
	}
	set src(value: string) {
		this.resolvedSrc = value ? new URL(value, window.location.href).href : '';
	}
	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
	load() {
		this.loadMock();
	}
	play() {
		return this.playMock();
	}
	pause() {
		this.pauseMock();
	}
	fire(name: string) {
		for (const listener of this.listeners.get(name) ?? []) listener({ type: name } as Event);
	}
}

const tracks: QueueStreamTrackItem[] = [
	{
		key: 'a',
		index: 0,
		entry_id: null,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'One',
		artist: 'A',
		generation_number: 1,
		mp3_path: 'a.mp3',
		audio_url: '/audio/a.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: 0,
		end_offset: 10
	},
	{
		key: 'b',
		index: 1,
		entry_id: null,
		generation_id: 'g2',
		song_id: 's2',
		song_title: 'Two',
		artist: 'A',
		generation_number: 1,
		mp3_path: 'b.mp3',
		audio_url: '/audio/b.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: 10,
		end_offset: 20
	}
];

let target: HTMLDivElement;
let component: ReturnType<typeof mount> & { loadAndPlay: (url: string, options: unknown) => void };
let audio: FakeAudio;
let audioContextConstructor: ReturnType<typeof vi.fn>;
let mediaSessionHandlers: Map<MediaSessionAction, MediaSessionActionHandler | null>;

beforeEach(() => {
	target = document.createElement('div');
	document.body.appendChild(target);
	audio = new FakeAudio();
	audioContextConstructor = vi.fn();
	vi.stubGlobal(
		'Audio',
		vi.fn(() => audio)
	);
	vi.stubGlobal('AudioContext', audioContextConstructor);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	mediaSessionHandlers = new Map();
	Object.defineProperty(navigator, 'mediaSession', {
		configurable: true,
		value: {
			metadata: null,
			playbackState: 'none',
			setActionHandler: vi.fn(
				(action: MediaSessionAction, handler: MediaSessionActionHandler | null) =>
					mediaSessionHandlers.set(action, handler)
			),
			setPositionState: vi.fn()
		}
	});
});

afterEach(async () => {
	if (component) await unmount(component);
	document.body.replaceChildren();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
	Reflect.deleteProperty(navigator, 'mediaSession');
});

describe('SharedPlayer stream windows', () => {
	it('ends a windowed stream once without calling the route callback and resets on reload', async () => {
		const onended = vi.fn();
		component = mount(SharedPlayer, {
			target,
			props: {
				audioUrl: '/stream.mp3',
				title: 'One',
				streamTracks: tracks,
				streamWindowed: true,
				startIndex: 1,
				autoplay: true,
				onended,
				onnext: vi.fn()
			}
		}) as typeof component;
		await tick();
		audio.fire('ended');
		audio.fire('ended');
		await tick();
		expect(onended).not.toHaveBeenCalled();
		expect(target.textContent).toContain('Weitere Takes nicht geladen');
		expect(target.querySelector('button[aria-label="Next"]')?.hasAttribute('disabled')).toBe(true);
		await audio.play();
		await tick();
		expect(target.textContent).not.toContain('Weitere Takes nicht geladen');
		audio.fire('ended');
		await tick();
		expect(onended).not.toHaveBeenCalled();
		expect(target.textContent).toContain('Weitere Takes nicht geladen');

		component.loadAndPlay('/stream.mp3', {
			startIndex: 0,
			streamTracks: tracks,
			streamWindowed: false
		});
		await tick();
		expect(target.textContent).not.toContain('Weitere Takes nicht geladen');
		audio.fire('ended');
		expect(onended).toHaveBeenCalledOnce();
	});
});

describe('SharedPlayer loading intent', () => {
	async function renderLoadingPlayer() {
		component = mount(SharedPlayer, {
			target,
			props: { audioUrl: '/shared.mp3', title: 'Shared song', autoplay: false }
		}) as typeof component;
		await tick();
		await Promise.resolve();
		await tick();
		audio.playMock.mockClear();
		audio.pauseMock.mockClear();
		audio.loadMock.mockClear();
		const play = target.querySelector<HTMLButtonElement>('.play-btn');
		if (!play) throw new Error('Expected shared play button');
		return play;
	}

	it('queues then consumes one loading tap, while a second tap cancels it', async () => {
		const play = await renderLoadingPlayer();
		expect(play.disabled).toBe(false);

		play.click();
		play.click();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();
		expect(audio.playMock).not.toHaveBeenCalled();

		audio.readyState = HTMLMediaElement.HAVE_NOTHING;
		play.click();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		audio.fire('canplay');
		await tick();
		expect(audio.playMock).toHaveBeenCalledOnce();
		expect(audioContextConstructor).not.toHaveBeenCalled();
	});

	it('preserves a replacement autoplay intent across the old stream pause event', async () => {
		await renderLoadingPlayer();
		audio.readyState = HTMLMediaElement.HAVE_NOTHING;
		component.loadAndPlay('/replacement.mp3', {});
		audio.fire('pause');
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(audio.playMock).toHaveBeenCalledOnce();
	});

	it('ignores a stale play rejection after a replacement load starts', async () => {
		await renderLoadingPlayer();
		let rejectOldPlay: ((reason: unknown) => void) | undefined;
		audio.playMock.mockImplementationOnce(
			() =>
				new Promise<void>((_resolve, reject) => {
					rejectOldPlay = reject;
				})
		);
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		component.loadAndPlay('/shared.mp3', {});
		await tick();

		audio.readyState = HTMLMediaElement.HAVE_NOTHING;
		component.loadAndPlay('/replacement.mp3', {});
		rejectOldPlay?.(new DOMException('Superseded source', 'AbortError'));
		await Promise.resolve();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(audio.playMock).toHaveBeenCalledTimes(2);
	});

	it.each(['pause', 'stop'] as const)(
		'cancels a queued loading play from the Media Session %s action',
		async (action) => {
			const play = await renderLoadingPlayer();
			play.click();
			await tick();

			mediaSessionHandlers.get(action)?.({ action });
			audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
			audio.fire('canplay');
			await tick();

			expect(audio.playMock).not.toHaveBeenCalled();
		}
	);

	it('lets a loading tap cancel an explicit loadAndPlay intent', async () => {
		const play = await renderLoadingPlayer();
		component.loadAndPlay('/replacement.mp3', {});
		play.click();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(audio.playMock).not.toHaveBeenCalled();
	});

	it('plays an already-ready same URL once and does not replay on another canplay', async () => {
		const play = await renderLoadingPlayer();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');

		component.loadAndPlay('/shared.mp3', {});
		await tick();
		expect(audio.playMock).toHaveBeenCalledOnce();
		expect(target.querySelector('.spinner')).toBeNull();

		audio.fire('canplay');
		await tick();
		expect(audio.playMock).toHaveBeenCalledOnce();

		play.click();
		await tick();
		expect(audio.pauseMock).toHaveBeenCalled();
	});
});
