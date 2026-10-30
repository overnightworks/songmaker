import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import type {
	QueueStreamManifest,
	SharedAlbumPayload,
	SharedAlbumSongPayload,
	WhisperCue
} from '#lib/api/types.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { hangsUntilAborted } from '#lib/test-utils/network.ts';

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

const FIRST_LINE = 'the lantern hums quietly tonight';
const SECOND_LINE = 'we count the fading city lights';

// One segment per lyric line, a word every second, as a take scored with
// word timestamps delivers them.
function sungCue(start: number, text: string): WhisperCue {
	const words = text.split(' ').map((word, index) => ({
		start: start + index,
		end: start + index + 1,
		text: word
	}));
	return { start: words[0].start, end: words[words.length - 1].end, text, words };
}

function albumSong(
	id: string,
	title: string,
	trackNumber: number,
	audioUrl: string | null
): SharedAlbumSongPayload {
	return {
		id,
		title,
		track_number: trackNumber,
		audio_url: audioUrl,
		generation_id: audioUrl ? `gen-${id}` : null,
		audio_duration: audioUrl ? 187 : null,
		lyrics: audioUrl ? `${FIRST_LINE}\n${SECOND_LINE}` : null,
		whisper_cues: audioUrl ? [sungCue(0, FIRST_LINE), sungCue(6, SECOND_LINE)] : null
	};
}

const album: SharedAlbumPayload = {
	title: 'Shared album',
	artist: 'Artist',
	subtitle: '',
	year: '',
	cover: null,
	songs: [
		albumSong('s1', 'First', 1, '/audio/first.mp3'),
		albumSong('s2', 'Second', 2, '/audio/second.mp3')
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
		// sharing_api.py's stream builder skips songs without a pick, so a
		// manifest only ever carries playable tracks.
		tracks: album.songs
			.filter(
				(song): song is SharedAlbumSongPayload & { audio_url: string } => song.audio_url !== null
			)
			.map((song, index) => ({
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
	// jsdom has no intersections; visibility scenarios install a controllable observer.
	vi.stubGlobal(
		'IntersectionObserver',
		vi.fn(
			class {
				observe = vi.fn();
				disconnect = vi.fn();
			}
		)
	);
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
	it('925_M2_W1: asks the server for the album at its own share address', async () => {
		mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));
		expect(mockFetch.mock.calls[0][0]).toBe('/shared/shared-album');
	});

	it('925_M2_W2: says in one line that a gone album link is no longer shared, with no player', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelector('h1')?.textContent).toBe('Album not found'));
		expect(target.textContent).toContain('This share link is invalid or was removed.');
		expect(target.querySelector('.now-playing')).toBeNull();
	});

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
			expect(target.querySelector('h1')?.textContent).toBe('Recovered album');
		});
	});

	it('925_M2_T1: a read that gets no answer within 30 seconds shows the error status with Try again', async () => {
		vi.useFakeTimers();
		onTestFinished(() => void vi.useRealTimers());
		mockFetch.mockImplementation(hangsUntilAborted);
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await tick();
		expect(target.querySelector('h1')?.textContent).toBe('Loading album');

		await vi.advanceTimersByTimeAsync(30_000);

		expect(target.querySelector('h1')?.textContent).toBe('Could not load this album');
		expect(target.querySelector('button')?.textContent).toBe('Try again');
	});

	it('hides songs without a pick instead of showing a disabled row', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				...album,
				songs: [...album.songs, albumSong('s3', 'Unpicked', 3, null)]
			})
		});
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));
		expect(target.textContent).not.toContain('Unpicked');
	});

	it('follows the sung words in stream mode, where the manifest redacts the lyrics', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.queue-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		expect(audioPlayer.current?.lyrics).toBeNull();

		await vi.waitFor(() => expect(document.querySelector('.lyrics-synced')).not.toBeNull());
		audioPlayer.currentTime = 7.5;
		await tick();

		const active = [...document.querySelectorAll('.lyrics-line.active')].map((el) =>
			el.textContent?.trim()
		);
		expect(active).toEqual([SECOND_LINE]);
	});

	it('#1374 rule 7: an album stream stops at its last song and Play again starts song 1', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.queue-row')[1].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
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
		await vi.waitFor(() => expect(target.querySelector('.cover-art img')).not.toBeNull());
		const img = target.querySelector<HTMLImageElement>('.cover-art img');
		expect(img?.getAttribute('src')).toContain('variant=detail');
		expect(img?.getAttribute('alt')).toBe('');
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
		await vi.waitFor(() => expect(target.querySelector('.cover-art img')).not.toBeNull());
		target.querySelector('img')?.dispatchEvent(new Event('error'));
		await tick();
		expect(target.querySelector('.cover-art img')).toBeNull();
		expect(target.querySelector('h1')?.textContent).toBe('Shared album');
	});

	it('1374_rule_2 opens the player page with its manifest queue', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.queue-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

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
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.queue-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		await tick();
		await tick();

		expect(target.querySelector('.cover-meta')?.textContent).not.toContain('Take');
		expect(target.querySelectorAll('.queue-take')).toHaveLength(0);
	});

	it('1374_rule_2 keeps the player in the page without a modal or an always-visible bar', async () => {
		mockFetch
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => album })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => manifest(false) });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });
		await vi.waitFor(() => expect(target.querySelectorAll('.queue-row')).toHaveLength(2));

		target.querySelectorAll<HTMLButtonElement>('.queue-row')[0].click();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		await tick();

		const surface = target.querySelector('.now-playing');
		expect(surface).not.toBeNull();
		expect(surface?.classList.contains('page')).toBe(true);
		expect(surface?.getAttribute('aria-modal')).toBeNull();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(document.documentElement.dataset.transportBar).toBeUndefined();
	});
});
