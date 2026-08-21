import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest, QueueStreamTrackItem } from '$lib/api/types';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { queueContext, songList } from '$lib/stores/player';
import PlayerBar from './PlayerBar.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	ended = false;
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

function track(index: number): QueueStreamTrackItem {
	return {
		key: `entry-${index}`,
		index,
		entry_id: `entry-${index}`,
		generation_id: 'same-generation',
		song_id: 'same-song',
		song_title: 'Repeated take',
		artist: 'Artist',
		generation_number: 1,
		mp3_path: 'take.mp3',
		audio_url: '/audio/take.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: index * 10,
		end_offset: (index + 1) * 10
	};
}

function manifest(tracks: QueueStreamTrackItem[]): QueueStreamManifest {
	return {
		snapshot_id: 'snapshot',
		stream_url: '/stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: tracks.reduce((total, item) => total + item.duration, 0),
		tracks,
		windowed: true,
		skipped: [],
		skipped_complete: true
	};
}

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;
let audio: FakeAudio;

beforeEach(() => {
	target = document.createElement('div');
	document.body.appendChild(target);
	audio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(() => audio)
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	songList.set([]);
	queueContext.set({ type: 'playlist', entries: [], index: 0 });
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	audioPlayer.destroy();
	document.body.replaceChildren();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('PlayerBar stream boundaries', () => {
	it('reacts at window boundaries even when adjacent entries use the same generation', async () => {
		audioPlayer.loadStream(manifest([track(0), track(1)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();

		const previous = target.querySelector<HTMLButtonElement>('button[aria-label="Previous"]');
		const next = target.querySelector<HTMLButtonElement>('button[aria-label="Next"]');
		expect(previous?.disabled).toBe(true);
		expect(next?.disabled).toBe(false);

		audio.currentTime = 15;
		audio.fire('timeupdate');
		await tick();

		expect(previous?.disabled).toBe(false);
		expect(next?.disabled).toBe(true);

		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		await tick();

		expect(previous?.disabled).toBe(true);
		expect(next?.disabled).toBe(true);
	});
});
