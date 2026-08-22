import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest, QueueStreamTrackItem } from '$lib/api/types';
import { NOW_PLAYING_LABEL, NOW_PLAYING_NO_LYRICS, RAIL_LIBRARY_LABEL } from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { AlbumItem, PlaylistDetailItem } from '$lib/api/types';
import {
	albumList,
	playStartNotice,
	queueContext,
	selectedAlbumId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import * as playerStore from '$lib/stores/player';
import { openCollection } from '$lib/stores/collection';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import { LIBRARY_QUEUE_EMPTY_TITLE, LIBRARY_QUEUE_LOADING_TITLE } from '$lib/constants';
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

function albumItem(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function playlistItem(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [
			{
				id: 'pe1',
				position: 0,
				generation_id: 'g1',
				song_id: 's1',
				song_title: 'Tide',
				album_title: 'Nachtstrom',
				artist: 'Artist',
				generation_number: 1,
				version_number: 1,
				is_picked: false,
				audio_duration: 180,
				mp3_path: 'tide.mp3',
				seed: 1,
				model_mode: 'sft',
				lyrics: null
			}
		],
		...overrides
	};
}

function track(index: number, overrides: Partial<QueueStreamTrackItem> = {}): QueueStreamTrackItem {
	return {
		key: `entry-${index}`,
		index,
		entry_id: `entry-${index}`,
		generation_id: 'same-generation',
		song_id: 'same-song',
		song_title: 'Repeated take',
		artist: 'Artist',
		album_title: 'Album',
		lyrics: 'old verse',
		generation_number: 1,
		mp3_path: 'take.mp3',
		audio_url: '/audio/take.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 10,
		start_offset: index * 10,
		end_offset: (index + 1) * 10,
		...overrides
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
let audioContextConstructor: ReturnType<typeof vi.fn>;

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
		vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
	);
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	songList.set([]);
	albumList.set([]);
	queueContext.set({ type: 'playlist', entries: [], index: 0 });
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedPlaylistDetail.set(null);
	openCollection.set(null);
	playStartNotice.set('idle');
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
	it('names the library, never the take pool, as the idle Play target with no collection open', async () => {
		queueContext.set({ type: 'library' });
		openCollection.set(null);
		selectedPlaylistDetail.set(null);
		const playIdleStart = vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();

		expect(audioPlayer.current).toBeNull();
		const play = target.querySelector<HTMLButtonElement>('button[aria-label="Play"]');
		expect(play?.disabled).toBe(false);
		expect(target.querySelector('.track-title')?.textContent).toBe(RAIL_LIBRARY_LABEL);
		play?.click();
		expect(playIdleStart).toHaveBeenCalledOnce();
	});

	it('idle Play copy follows an open album interior', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(null);
		albumList.set([albumItem()]);
		vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.querySelector('.track-title')?.textContent).toBe('Nachtstrom');
		expect(target.textContent).toContain('Nachtstrom');
	});

	it('idle Play copy follows an open playlist interior', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(playlistItem());
		vi.spyOn(playerStore, 'playIdleStart').mockResolvedValue();
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.querySelector('.track-title')?.textContent).toBe('Night Drive');
		expect(target.textContent).toContain('Night Drive');
	});

	it('pressing Play on an empty playlist shows the no-takes notice', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedSongId.set(null);
		selectedPlaylistDetail.set(playlistItem({ entry_count: 0, entries: [] }));
		component = mount(PlayerBar, { target });
		await tick();

		target.querySelector<HTMLButtonElement>('button[aria-label="Play"]')?.click();
		await vi.waitFor(() => expect(target.textContent).toContain(LIBRARY_QUEUE_EMPTY_TITLE));
		expect(target.textContent).toContain('Night Drive');
		expect(audioPlayer.current).toBeNull();

		selectedPlaylistDetail.set(playlistItem());
		target.querySelector<HTMLButtonElement>('button[aria-label="Play"]')?.click();
		await vi.waitFor(() => expect(audioPlayer.current?.songTitle).toBe('Tide'));
		expect(target.textContent).not.toContain(LIBRARY_QUEUE_EMPTY_TITLE);
	});

	it('uses English loading and empty copy instead of German leftovers', async () => {
		queueContext.set({ type: 'library' });
		playStartNotice.set('building');
		component = mount(PlayerBar, { target });
		await tick();
		expect(target.textContent).toContain(LIBRARY_QUEUE_LOADING_TITLE);
		expect(target.textContent).not.toContain('Queue wird gebaut');
		playStartNotice.set('empty');
		await tick();
		expect(target.textContent).toContain(LIBRARY_QUEUE_EMPTY_TITLE);
		expect(target.textContent).not.toContain('Keine Takes');
	});

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

	it('keeps Play enabled and queues one loading tap until canplay', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		const play = target.querySelector<HTMLButtonElement>('.play-btn');
		if (!play) throw new Error('Expected player Play button');
		const playSpy = vi.spyOn(audio, 'play');

		expect(play.disabled).toBe(false);
		play.click();
		await tick();
		await Promise.resolve();
		expect(playSpy).not.toHaveBeenCalled();

		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(playSpy).toHaveBeenCalledOnce();
		expect(audioContextConstructor).not.toHaveBeenCalled();
	});

	it('cancels a queued loading play on a second tap', async () => {
		audioPlayer.loadStream(manifest([track(0)]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		const play = target.querySelector<HTMLButtonElement>('.play-btn');
		if (!play) throw new Error('Expected player Play button');
		const playSpy = vi.spyOn(audio, 'play');

		play.click();
		play.click();
		await tick();
		await Promise.resolve();
		audio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
		audio.fire('canplay');
		await tick();

		expect(playSpy).not.toHaveBeenCalled();
	});
});

describe('PlayerBar Now Playing', () => {
	it('opens Now Playing from the compact title and swaps lyrics with the take', async () => {
		audioPlayer.loadStream(
			manifest([
				track(0, {
					generation_id: 'g-old',
					song_id: 's-old',
					song_title: 'Tide',
					lyrics: 'old verse'
				}),
				track(1, {
					generation_id: 'g-new',
					song_id: 's-new',
					song_title: 'Second',
					lyrics: 'second verse',
					generation_number: 4
				})
			]),
			0,
			{ autoplay: false }
		);
		component = mount(PlayerBar, { target });
		await tick();

		const title = target.querySelector<HTMLButtonElement>(
			`button[aria-label="${NOW_PLAYING_LABEL}"]`
		);
		title?.click();
		await tick();

		const sheet = document.querySelector('.now-playing-sheet');
		expect(sheet?.textContent).toContain('Tide');
		expect(sheet?.textContent).toContain('old verse');
		expect(sheet?.textContent).not.toContain('second verse');

		audio.currentTime = 15;
		audio.fire('timeupdate');
		await tick();

		expect(sheet?.textContent).toContain('Second');
		expect(sheet?.textContent).toContain('second verse');
		expect(sheet?.textContent).not.toContain('old verse');
	});

	it('shows the empty lyrics state for a take without version lyrics', async () => {
		audioPlayer.loadStream(manifest([track(0, { lyrics: null })]), 0, { autoplay: false });
		component = mount(PlayerBar, { target });
		await tick();
		target.querySelector<HTMLButtonElement>(`button[aria-label="${NOW_PLAYING_LABEL}"]`)?.click();
		await tick();
		expect(document.querySelector('.now-playing-sheet')?.textContent).toContain(
			NOW_PLAYING_NO_LYRICS
		);
	});
});
