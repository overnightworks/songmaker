import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-playlist' } } }));

import Page from './+page.svelte';

class FakeAudio {
	paused = true;
	currentTime = 0;
	duration = 20;
	readyState = 1;
	src = '';
	preload = '';
	crossOrigin: string | null = null;
	private listeners = new Map<string, Array<(event: Event) => void>>();

	addEventListener(name: string, listener: (event: Event) => void) {
		this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
	}
	removeAttribute() {}
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
	fire(name: string) {
		for (const listener of this.listeners.get(name) ?? []) listener({ type: name } as Event);
	}
}

const playlist = {
	title: 'Shared playlist',
	entries: [
		{
			entry_id: 'entry-1',
			song_title: 'First',
			artist: 'Artist',
			generation_number: 1,
			audio_url: '/audio/first.mp3'
		},
		{
			entry_id: 'entry-2',
			song_title: 'Second',
			artist: 'Artist',
			generation_number: 1,
			audio_url: '/audio/second.mp3'
		}
	]
};

function manifest(windowed: boolean): QueueStreamManifest {
	return {
		snapshot_id: 'shared-playlist-stream',
		stream_url: '/shared-playlist-stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: 20,
		windowed,
		skipped: [],
		skipped_complete: true,
		tracks: playlist.entries.map((entry, index) => ({
			key: entry.entry_id,
			index,
			entry_id: entry.entry_id,
			generation_id: `g${index + 1}`,
			song_id: `s${index + 1}`,
			song_title: entry.song_title,
			artist: entry.artist,
			album_title: '',
			lyrics: null,
			generation_number: entry.generation_number,
			mp3_path: `${entry.entry_id}.mp3`,
			audio_url: entry.audio_url,
			seed: null,
			model_mode: 'sft',
			duration: 10,
			start_offset: index * 10,
			end_offset: (index + 1) * 10
		}))
	};
}

const mockFetch = vi.fn();
let component: ReturnType<typeof mount> | undefined;
let audio: FakeAudio;

beforeEach(() => {
	audio = new FakeAudio();
	vi.stubGlobal('fetch', mockFetch);
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return audio;
		})
	);
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	setQueuePlaybackMode('stream');
	audioPlayer.destroy();
});

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	mockFetch.mockReset();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('shared playlist page', () => {
	it('shows each entry with its own artist', async () => {
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => playlist });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));
		expect(target.textContent).toContain('First');
		expect(target.textContent).toContain('Artist');
	});

	it('passes windowed manifests through and stops without wrapping', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => playlist })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(true) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.track-row')[1].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		audio.fire('ended');
		await tick();

		expect(target.querySelectorAll<HTMLButtonElement>('.track-row')[1].classList).toContain(
			'current'
		);
	});

	it('keeps direct non-windowed playlist playback wrapping', async () => {
		setQueuePlaybackMode('classic');
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => playlist });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.track-row')[1].click();
		await vi.waitFor(() => expect(target.querySelector('.player-bar')).not.toBeNull());
		audio.fire('ended');
		await tick();

		expect(target.querySelectorAll<HTMLButtonElement>('.track-row')[0].classList).toContain(
			'current'
		);
	});
});
