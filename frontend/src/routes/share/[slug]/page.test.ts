import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-album' } } }));

import Page from './+page.svelte';

const mockFetch = vi.fn();

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

const album = {
	title: 'Shared album',
	artist: 'Artist',
	subtitle: '',
	year: '',
	cover: null,
	songs: [
		{ id: 's1', title: 'First', track_number: 1, audio_url: '/audio/first.mp3' },
		{ id: 's2', title: 'Second', track_number: 2, audio_url: '/audio/second.mp3' }
	]
};

function manifest(windowed: boolean): QueueStreamManifest {
	return {
		snapshot_id: 'shared-stream',
		stream_url: '/shared-stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: 20,
		windowed,
		skipped: [],
		skipped_complete: true,
		tracks: album.songs.map((song, index) => ({
			key: song.id,
			index,
			entry_id: null,
			generation_id: `g${index + 1}`,
			song_id: song.id,
			song_title: song.title,
			artist: album.artist,
			album_title: album.title,
			lyrics: null,
			generation_number: 1,
			mp3_path: `${song.id}.mp3`,
			audio_url: song.audio_url,
			seed: null,
			model_mode: 'sft',
			duration: 10,
			start_offset: index * 10,
			end_offset: (index + 1) * 10
		}))
	};
}

let component: ReturnType<typeof mount> | undefined;
let audio: FakeAudio;

beforeEach(() => {
	audio = new FakeAudio();
	vi.stubGlobal('fetch', mockFetch);
	vi.stubGlobal(
		'Audio',
		vi.fn(() => audio)
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

describe('shared album page', () => {
	it('shows loading during retry and can recover into the album', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => {
			expect(target.querySelector('h1')?.textContent).toBe('Could not load this album');
		});

		let finishRetry: ((response: unknown) => void) | undefined;
		mockFetch.mockReturnValueOnce(new Promise((resolve) => (finishRetry = resolve)));
		target.querySelector<HTMLButtonElement>('button')?.click();
		await tick();
		expect(target.querySelector('h1')?.textContent).toBe('Loading album');

		finishRetry?.({
			ok: true,
			status: 200,
			json: async () => ({
				title: 'Recovered album',
				artist: 'Artist',
				subtitle: '',
				year: '',
				songs: []
			})
		});
		await vi.waitFor(() => {
			expect(target.querySelector('.header-title')?.textContent).toBe('Recovered album');
		});
	});

	it('hides songs without a pick instead of showing a disabled row', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				...album,
				songs: [...album.songs, { id: 's3', title: 'Unpicked', track_number: 3, audio_url: null }]
			})
		});
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));
		expect(target.textContent).not.toContain('Unpicked');
	});

	it('passes windowed manifests through and stops without wrapping', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
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

	it('keeps direct non-windowed album playback wrapping', async () => {
		setQueuePlaybackMode('classic');
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album });
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

	it('renders a cover image when the shared album includes one', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				...album,
				cover: {
					card: '/shared/shared-album/cover?variant=card&v=abc.jpg',
					detail: '/shared/shared-album/cover?variant=detail&v=abc.jpg'
				}
			})
		});
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelector('.header-cover img')).not.toBeNull());
		const img = target.querySelector<HTMLImageElement>('.header-cover img');
		expect(img?.getAttribute('src')).toContain('variant=detail');
		expect(img?.getAttribute('alt')).toBe('Album Shared album');
	});

	it('hides a broken cover instead of leaving a dead image', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				...album,
				cover: {
					card: '/shared/shared-album/cover?variant=card&v=missing.jpg',
					detail: '/shared/shared-album/cover?variant=detail&v=missing.jpg'
				}
			})
		});
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelector('.header-cover img')).not.toBeNull());
		target.querySelector('img')?.dispatchEvent(new Event('error'));
		await tick();
		expect(target.querySelector('.header-cover img')).toBeNull();
		expect(target.querySelector('.header-title')?.textContent).toBe('Shared album');
	});

	it('opens Now Playing showing the manifest queue', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.track-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		target.querySelector<HTMLButtonElement>('.now-playing-btn')?.click();
		await tick();
		// jsdom's stubbed matchMedia matches every query, so Now Playing always
		// renders its stacked (mobile) layout here — open the queue sheet to
		// reach the same NowPlayingQueue content the desktop layout renders
		// inline.
		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();

		expect(target.querySelector('.now-playing')).not.toBeNull();
		const queueTitles = Array.from(target.querySelectorAll('.queue-title')).map(
			(el) => el.textContent
		);
		expect(queueTitles).toEqual(['First', 'Second']);
	});

	it('never shows an internal take number to a public listener', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.track-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.track-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		target.querySelector<HTMLButtonElement>('.now-playing-btn')?.click();
		await tick();
		target.querySelector<HTMLButtonElement>('.mobile-panel-trigger')?.click();
		await tick();

		expect(target.querySelector('.cover-meta')?.textContent).not.toContain('Take');
		expect(target.querySelectorAll('.queue-take')).toHaveLength(0);
	});
});
