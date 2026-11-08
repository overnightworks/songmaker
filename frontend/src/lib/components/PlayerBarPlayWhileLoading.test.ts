import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '#lib/constants.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import type { PlaybackInfo } from '#lib/services/playbackTypes.ts';
import { nowPlayingSurface } from '#lib/stores/player.ts';
import type { SharedCollectionView } from '#lib/share/sharedCollection.ts';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import NowPlaying from './NowPlaying.svelte';
import PlayerBar from './PlayerBar.svelte';
import SharedCollection from './share/SharedCollection.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	buffered = { length: 0, end: () => 0 };
	ended = false;
	error: MediaError | null = null;
	private listeners = new Map<string, Array<(event: Event) => void>>();

	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
	load() {
		this.fire('loadstart');
	}
	play() {
		this.paused = false;
		this.fire('play');
		return Promise.resolve();
	}
	pause() {
		this.paused = true;
		this.fire('pause');
	}
	removeAttribute() {}
	fire(name: string) {
		for (const listener of this.listeners.get(name) ?? []) listener({ type: name } as Event);
	}
}

const loadingTake: PlaybackInfo = {
	generation: makeGeneration({ mp3_path: 'take.mp3' }),
	songId: 's1',
	songTitle: 'Opening Move',
	artist: 'Artist',
	albumTitle: 'Album',
	lyrics: null
};

const sharedView: SharedCollectionView = {
	kind: 'song',
	title: 'Neon Tide',
	artist: 'Mara Lind',
	albumTitle: null,
	year: null,
	cover: null,
	playlistCovers: [],
	tracks: [
		{
			key: 'single',
			title: 'Neon Tide',
			subtitle: null,
			audioUrl: '/shared/audio/single.mp3',
			durationSec: 180,
			lyrics: null,
			cues: null,
			cover: null,
			albumTitle: null
		}
	]
};

const SURFACES = [
	{
		name: 'the transport bar',
		render: (target: HTMLElement) => {
			audioPlayer.load(loadingTake, { autoplay: false });
			return mount(PlayerBar, { target });
		}
	},
	{
		name: 'Now Playing',
		render: (target: HTMLElement) => {
			audioPlayer.load(loadingTake, { autoplay: false });
			nowPlayingSurface.set('full');
			return mount(NowPlaying, { target, props: { info: loadingTake } });
		}
	},
	{
		name: 'the share player',
		render: (target: HTMLElement) =>
			mount(SharedCollection, {
				target,
				props: {
					loading: false,
					errorKind: null,
					resource: 'album',
					view: sharedView,
					fetchStream: null
				}
			})
	}
];

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;
let audio: FakeAudio;

beforeEach(() => {
	target = document.createElement('div');
	document.body.appendChild(target);
	audio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return audio;
		})
	);
	vi.stubGlobal('AudioContext', vi.fn());
	vi.stubGlobal(
		'IntersectionObserver',
		vi.fn(
			class {
				observe = vi.fn();
				disconnect = vi.fn();
			}
		)
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	nowPlayingSurface.set('closed');
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	audioPlayer.current = null;
	audioPlayer.destroy();
	nowPlayingSurface.set('closed');
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

async function pressPlay(): Promise<void> {
	const play = target.querySelector<HTMLButtonElement>('.play-btn');
	if (!play) throw new Error('Expected a Play control');
	play.click();
	await tick();
	await Promise.resolve();
}

function playLabel(): string | null | undefined {
	return target.querySelector('.play-btn')?.getAttribute('aria-label');
}

describe('Play while the audio loads', () => {
	// Spec: REQ-PLAYER-02 -- on every player surface a first Play press while the audio loads queues playback and a second press cancels it.
	it.each(SURFACES)('on $name a second press cancels the queued play', async ({ render }) => {
		component = render(target);
		await tick();
		const playSpy = vi.spyOn(audio, 'play');

		await pressPlay();
		expect(playLabel()).toBe(TRANSPORT_PAUSE_LABEL);
		await pressPlay();
		expect(playLabel()).toBe(TRANSPORT_PLAY_LABEL);

		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();
		expect(playSpy).not.toHaveBeenCalled();
	});
});
