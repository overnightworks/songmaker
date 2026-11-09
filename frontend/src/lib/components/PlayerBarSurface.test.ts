import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import { NOW_PLAYING_LABEL } from '#lib/constants/now-playing.ts';
import { audioPlayer, type PlaybackInfo } from '#lib/services/audioPlayer.svelte.ts';
import { nowPlayingDockable, nowPlayingSurface, setShuffle } from '#lib/stores/player.ts';
import PlayerBar from './PlayerBar.svelte';

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

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;
let audio: FakeAudio;

beforeEach(async () => {
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
		'matchMedia',
		vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	nowPlayingSurface.set('closed');
	nowPlayingDockable.set(true);
	setShuffle(false);
	const playing: PlaybackInfo = {
		generation: makeGeneration({ mp3_path: 'take.mp3' }),
		songId: 's1',
		songTitle: 'Opening Move',
		artist: 'Artist',
		albumTitle: 'Album',
		lyrics: null
	};
	audioPlayer.load(playing, { autoplay: false });
	component = mount(PlayerBar, { target });
	await tick();
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	audioPlayer.destroy();
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

function control(selector: string): HTMLButtonElement {
	const found = target.querySelector<HTMLButtonElement>(selector);
	if (!found) throw new Error(`Expected ${selector} in the transport bar`);
	return found;
}

async function pressAndSettle(control: HTMLButtonElement): Promise<void> {
	control.click();
	await tick();
	await Promise.resolve();
}

describe('PlayerBar while a take is loaded', () => {
	// Spec: REQ-PLAYER-01 -- the bar names the current song, and its Now Playing control opens the one surface and puts it away again.
	it('names the song and opens and closes its one Now Playing surface', async () => {
		expect(target.querySelector('.track-title')?.textContent).toBe('Opening Move');

		await pressAndSettle(control(`button[aria-label="${NOW_PLAYING_LABEL}"]`));
		expect(get(nowPlayingSurface)).toBe('docked');

		await pressAndSettle(control(`button[aria-label="${NOW_PLAYING_LABEL}"]`));
		expect(get(nowPlayingSurface)).toBe('closed');
	});
});
