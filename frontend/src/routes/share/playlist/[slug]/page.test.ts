import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import type { QueueStreamManifest } from '#lib/api/types.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { hangsUntilAborted } from '#lib/test-utils/network.ts';

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
	buffered = { length: 0, end: () => 0 };
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

const sharedPlaylist = {
	title: 'Shared playlist',
	album_covers: [],
	entries: [
		{
			entry_id: 'entry-1',
			song_title: 'First',
			artist: 'Artist',
			album_title: 'Album',
			generation_number: 1,
			audio_url: '/audio/first.mp3'
		},
		{
			entry_id: 'entry-2',
			song_title: 'Second',
			artist: 'Artist',
			album_title: 'Album',
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
		tracks: sharedPlaylist.entries.map((entry, index) => ({
			key: entry.entry_id,
			index,
			entry_id: entry.entry_id,
			generation_id: `g${index + 1}`,
			song_id: `s${index + 1}`,
			song_title: entry.song_title,
			artist: entry.artist,
			album_title: entry.album_title,
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
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			observe() {}
			disconnect() {}
		}
	);
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
	it('925_M2_W1: asks the server for the playlist at its own share address', async () => {
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => sharedPlaylist });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));
		expect(mockFetch.mock.calls[0][0]).toBe('/shared/playlist/shared-playlist');
	});

	it('925_M2_W2: says in one line that a gone playlist link is no longer shared, with no player', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() =>
			expect(target.querySelector('h1')?.textContent).toBe('Playlist not found')
		);
		expect(target.textContent).toContain('This share link is invalid or was removed.');
		expect(target.querySelector('.now-playing')).toBeNull();
	});

	it('1374_rule_5 shows each entry with its album', async () => {
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => sharedPlaylist });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));
		expect(target.textContent).toContain('First');
		expect(target.textContent).toContain('Album');
	});

	it('925_M2_T2: a stream build that outlasts its 120 second budget falls back to classic playback', async () => {
		mockFetch.mockImplementation((path: string, init: RequestInit) =>
			path.endsWith('/stream')
				? hangsUntilAborted(path, init)
				: Promise.resolve({ ok: true, status: 200, json: async () => sharedPlaylist })
		);
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		vi.useFakeTimers();
		onTestFinished(() => void vi.useRealTimers());
		target.querySelectorAll<HTMLButtonElement>('.queue-row')[0].click();
		await vi.advanceTimersByTimeAsync(119_999);
		expect(audioPlayer.current).toBeNull();
		expect(audio.src).toBe('');

		await vi.advanceTimersByTimeAsync(1);
		vi.useRealTimers();

		await vi.waitFor(() => expect(audio.src).toBe('/audio/first.mp3'));
		audio.fire('canplay');
		expect(audioPlayer.current?.songTitle).toBe('First');
		expect(audioPlayer.mode).toBe('classic');
		expect(audioPlayer.transport).toBe('playing');
		expect(audio.paused).toBe(false);
	});

	it.each(['classic', 'stream'] as const)(
		'1374_rule_7 a playlist %s stops at its last song and Play again starts song 1',
		async (mode) => {
			mockFetch
				.mockResolvedValueOnce({ ok: true, status: 200, json: async () => sharedPlaylist })
				.mockResolvedValue({
					ok: mode === 'stream',
					status: mode === 'stream' ? 200 : 503,
					json: async () => manifest(false)
				});
			const target = document.createElement('div');
			document.body.appendChild(target);
			component = mount(Page, { target });
			await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

			target.querySelectorAll<HTMLButtonElement>('.queue-row')[1].click();
			await vi.waitFor(() => expect(audioPlayer.current?.songTitle).toBe('Second'));
			expect(audioPlayer.mode).toBe(mode);
			expect(audioPlayer.current?.albumTitle).toBe('Album');
			audio.fire('ended');
			await tick();

			const rows = () => target.querySelectorAll<HTMLButtonElement>('.queue-row');
			expect(rows()[1].classList).toContain('current');
			await vi.waitFor(() => expect(document.querySelector('.play-again')).not.toBeNull());
			expect(document.querySelector('.play-again')?.textContent).toContain('Play again');
			expect(
				document.querySelector<HTMLButtonElement>('button[aria-label="Next song"]')?.disabled
			).toBe(true);

			document.querySelector<HTMLButtonElement>('.play-again')?.click();
			await vi.waitFor(() => expect(rows()[0].classList).toContain('current'));
		}
	);
});
