import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type {
	GenerationItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	SongItem
} from '$lib/api/types';
import { ALBUM_ADD_SONG_LABEL } from '$lib/constants';
import { openCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import {
	albumList,
	closeNowPlaying,
	nowPlayingOpen,
	nowPlayingPanel,
	queueContext,
	selectedSongId,
	setShuffle,
	shuffleEnabled,
	songList
} from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/client', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchPlaylist: vi.fn()
}));

import RailContext from './RailContext.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 1,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function playlistDetail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [],
		...overrides
	};
}

function entry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'e1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'First Track',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'g1.mp3',
		seed: 7,
		model_mode: 'turbo',
		lyrics: null,
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RailContext, { target });
	await tick();
	return target;
}

beforeEach(() => {
	resetPlaylists();
	resetLibraryContextForTests();
	albumList.set([
		{
			id: 'a1',
			title: 'Nachtstrom',
			artist: 'Artist',
			subtitle: '',
			year: '',
			colors: {},
			song_count: 2,
			picked_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	songList.set([
		song({ id: 's1', title: 'Tide', track_number: 1 }),
		song({ id: 's2', title: 'Ebb', track_number: 2 })
	]);
	selectedSongId.set(null);
	setShuffle(false);
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
	});
});

afterEach(async () => {
	audioPlayer.current = null;
	queueContext.set({ type: 'library' });
	setShuffle(false);
	closeNowPlaying();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	openCollection.set(null);
	resetPlaylists();
	resetLibraryContextForTests();
});

describe('RailContext', () => {
	it('shows a placeholder and no track rows when no collection is open', async () => {
		const target = await render();
		expect(target.querySelector('.rail-context')).toBeNull();
		expect(target.querySelector('.context-empty')?.textContent).toContain(
			'No album or playlist open'
		);
	});

	it('shows the open album title and its tracks in order, with the selected track marked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set('s2');
		const target = await render();
		const rows = target.querySelectorAll('.context-row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
		const selected = target.querySelector('.context-row.selected .context-row-title');
		expect(selected?.textContent).toBe('Ebb');
	});

	it('is navigation only — creating a song lives in the album header, not the rail', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		const target = await render();
		expect(target.textContent).not.toContain(ALBUM_ADD_SONG_LABEL);
	});

	it('shows a take/pick summary per track', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 0, generations: [] }),
			song({
				id: 's2',
				title: 'Ebb',
				track_number: 2,
				generation_count: 3,
				generations: [generation({ id: 'g1', is_picked: true })]
			})
		]);
		const target = await render();
		const meta = Array.from(target.querySelectorAll('.context-row-meta')).map(
			(el) => el.textContent
		);
		expect(meta).toEqual(['—', '3 takes · pick']);
	});

	it('shows the open playlist title and its entries', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(playlistDetail({ entries: [entry()] }));
		const target = await render();
		expect(target.textContent).toContain('Night Drive');
		expect(target.textContent).toContain('First Track');
		expect(target.querySelector('.context-add')).toBeNull();
	});

	it('plays a clicked entry in playlist order and shows the take in Now Playing', async () => {
		setShuffle(true);
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			playlistDetail({
				entry_count: 2,
				entries: [entry({ id: 'e1', position: 0 }), entry({ id: 'e2', position: 1 })]
			})
		);
		const target = await render();

		const rows = target.querySelectorAll<HTMLButtonElement>('.context-row');
		rows[1]?.click();
		await tick();

		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.playlist).toEqual({ id: 'p1', title: 'Night Drive' });
		expect(ctx.entries.map((queued) => queued.id)).toEqual(['e1', 'e2']);
		expect(ctx.index).toBe(1);
		expect(get(shuffleEnabled)).toBe(false);
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('opens the album interior from the header, replacing history, while a song inside it is open', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set('s1');
		librarySurface.set('detail');
		const target = await render();
		const header = target.querySelector<HTMLButtonElement>('.context-head');
		if (!header) throw new Error('Expected .context-head to be rendered');
		expect(header.getAttribute('aria-current')).toBeNull();

		const before = history.state?.index ?? 0;
		header.click();
		await tick();

		expect(get(selectedSongId)).toBeNull();
		expect(header.getAttribute('aria-current')).toBe('page');
		expect(history.state?.index ?? 0).toBe(before);
	});

	it('opens the album interior from the header, pushing history, when browsing elsewhere', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set(null);
		librarySurface.set('browse');
		const target = await render();
		const header = target.querySelector<HTMLButtonElement>('.context-head');
		if (!header) throw new Error('Expected .context-head to be rendered');

		const before = history.state?.index ?? 0;
		header.click();
		await tick();

		expect(header.getAttribute('aria-current')).toBe('page');
		expect(history.state?.index ?? 0).toBe(before + 1);
	});
});
