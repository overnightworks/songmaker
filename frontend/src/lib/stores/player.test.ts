import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import type {
	GenerationItem,
	PaginatedResponse,
	PlaylistEntryItem,
	QueueStreamManifest,
	QueueStreamTrackItem,
	SongItem
} from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import { createQueueStreamSnapshot, fetchSong, fetchSongs } from '$lib/api/client';
import { toasts } from '$lib/stores/toast';
import { QUEUE_STREAM_UNPLAYABLE_START_DETAIL, QUEUE_TAKE_MISSING_TOAST } from '$lib/constants';
import type { StreamFallbackState } from '$lib/services/audioPlayer.svelte';

vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));
vi.mock('$lib/api/client', () => ({
	createQueueStreamSnapshot: vi.fn(),
	createLibraryQueueStreamSnapshot: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	})
}));
import {
	canPlayNextGen,
	canPlayNextSong,
	canPlayPrevGen,
	canPlayPrevSong,
	clearGenerationSelection,
	ensureGenerationsLoaded,
	albumSongsLoad,
	loadSongsForAlbum,
	cancelAlbumSongLoads,
	replaceSongInList,
	upsertSongInList,
	overlaySongList,
	retainRicherSong,
	filteredSongs,
	handlePlaybackEnded,
	navigateToPlaying,
	playGeneration,
	toPlaybackInfo,
	chooseLibraryTakePool,
	libraryQueueNotice,
	libraryQueueSkipped,
	libraryQueueSkippedComplete,
	playLibrary,
	playLibraryFromGeneration,
	playAlbumFromGeneration,
	retryLastPlayIntent,
	playNextSong,
	playPrevSong,
	playPlaylistEntries,
	queueContext,
	selectAlbum,
	selectGenerationInSidebar,
	selectSong,
	selectedAlbumId,
	selectedGeneration,
	selectedGenerationId,
	selectedSong,
	selectedSongId,
	setShuffle,
	shuffleEnabled,
	songList,
	toggleShuffle,
	updateGenerationScores,
	windowEnded
} from './player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { createLibraryQueueStreamSnapshot } from '$lib/api/client';
import { ApiError } from '$lib/api/fetch';
import { libraryTakePool, setLibraryTakePool } from '$lib/stores/playbackSettings';

async function rebuildStream(state: StreamFallbackState): Promise<QueueStreamManifest | null> {
	const rebuild = audioPlayer.onStreamRebuild;
	if (!rebuild) {
		throw new Error('onStreamRebuild is not assigned');
	}
	return rebuild(state);
}

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Song',
		album_id: 'a1',
		album_title: 'Album',
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
		generations: [makeGen()],
		created_at: '',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function makeGen(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		wav_path: 'a1/song_v1.wav',
		seed: 42,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function makePlaylistEntry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Playlist Song',
		album_title: 'Album',
		artist: 'Artist',
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		seed: 42,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

beforeEach(() => {
	// These tests pin the classic per-track queue path; stream is now the
	// product default, so classic must be an explicit choice here.
	setQueuePlaybackMode('classic');
	vi.mocked(fetchSongs).mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	});
	vi.mocked(fetchSong).mockReset();
	vi.spyOn(audioPlayer, 'load').mockImplementation((info) => {
		audioPlayer.current = info;
	});
});

afterEach(() => {
	vi.restoreAllMocks();
	audioPlayer.current = null;
	songList.set([]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	queueContext.set({ type: 'library' });
	setShuffle(false);
	setLibraryTakePool('mix');
	libraryQueueNotice.set('idle');
	libraryQueueSkipped.set([]);
	windowEnded.set(false);
	audioPlayer.mode = 'classic';
	audioPlayer.currentTime = 0;
	toasts.set([]);
	localStorage.removeItem('queueShuffleEnabled');
	localStorage.removeItem('libraryTakePool');
});

describe('browsing state', () => {
	it('selectAlbum sets album and clears song/gen', () => {
		selectedSongId.set('s1');
		selectedGenerationId.set('g1');
		selectAlbum('a2');
		expect(get(selectedAlbumId)).toBe('a2');
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedGenerationId)).toBeNull();
	});

	it('selectAlbum with null clears album', () => {
		selectAlbum(null);
		expect(get(selectedAlbumId)).toBeNull();
	});

	it('selectSong sets song and clears gen', () => {
		selectedGenerationId.set('g1');
		selectSong('s2');
		expect(get(selectedSongId)).toBe('s2');
		expect(get(selectedGenerationId)).toBeNull();
	});

	it('selectedSong derives from songList', () => {
		songList.set([makeSong()]);
		selectedSongId.set('s1');
		expect(get(selectedSong)?.title).toBe('Song');
	});

	it('selectedSong returns null for unknown id', () => {
		songList.set([makeSong()]);
		selectedSongId.set('unknown');
		expect(get(selectedSong)).toBeNull();
	});

	it('ensureGenerationsLoaded refetches when loaded takes are fewer than generation_count', async () => {
		songList.set([
			makeSong({
				id: 's-partial',
				generation_count: 2,
				generations: [makeGen()]
			})
		]);
		const full = makeSong({
			id: 's-partial',
			generation_count: 2,
			generations: [makeGen(), makeGen({ id: 'g2' })]
		});
		vi.mocked(fetchSong).mockResolvedValueOnce(full);
		await ensureGenerationsLoaded('s-partial');
		expect(get(songList).find((item) => item.id === 's-partial')?.generations).toHaveLength(2);
	});

	it('replaceSongInList applies an authoritative empty generation list', () => {
		songList.set([makeSong({ generation_count: 1, generations: [makeGen()] })]);
		replaceSongInList(makeSong({ generation_count: 0, generations: [] }));
		expect(get(songList)[0].generations).toEqual([]);
		expect(get(songList)[0].generation_count).toBe(0);
	});

	it('cancelAlbumSongLoads drops an in-flight album merge', async () => {
		let resolvePage: ((value: PaginatedResponse<SongItem>) => void) | undefined;
		vi.mocked(fetchSongs).mockImplementationOnce(
			() =>
				new Promise<PaginatedResponse<SongItem>>((resolve) => {
					resolvePage = resolve;
				})
		);
		const pending = loadSongsForAlbum('a1');
		cancelAlbumSongLoads();
		resolvePage?.({
			items: [makeSong({ id: 's-stale', album_id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 200,
			has_more: false
		});
		await pending;
		expect(get(songList).some((item) => item.id === 's-stale')).toBe(false);
	});

	it('ensureGenerationsLoaded fetches and adds a song opened directly, not yet in the list', async () => {
		// Felix, 2026-07-18: clicking a song directly (from a playlist) loaded nothing — only
		// opening its album did. The song was absent from the list, so the old guard bailed.
		songList.set([]);
		const directlyOpened = makeSong({ id: 's-direct', title: 'Direct', generations: [makeGen()] });
		vi.mocked(fetchSong).mockResolvedValueOnce(directlyOpened);

		await ensureGenerationsLoaded('s-direct');

		expect(get(songList).map((s) => s.id)).toContain('s-direct');
		selectedSongId.set('s-direct');
		expect(get(selectedSong)?.generations.length).toBe(1);
	});

	it('records a retryable error when album songs fail to load', async () => {
		vi.mocked(fetchSongs).mockRejectedValueOnce(new Error('offline'));
		await loadSongsForAlbum('a1');
		expect(get(albumSongsLoad).a1).toEqual({ status: 'error', error: 'offline' });
	});

	it('loadSongsForAlbum merges album tracks that were outside the browse slice', async () => {
		songList.set([makeSong({ id: 's-page', album_id: 'a1' })]);
		vi.mocked(fetchSongs).mockResolvedValueOnce({
			items: [
				makeSong({ id: 's-page', album_id: 'a1', title: 'Page' }),
				makeSong({ id: 's-hidden', album_id: 'a1', title: 'Hidden' })
			],
			total: 2,
			offset: 0,
			limit: 200,
			has_more: false
		});
		await loadSongsForAlbum('a1');
		expect(vi.mocked(fetchSongs)).toHaveBeenCalledWith('a1', 0, 200);
		expect(
			get(songList)
				.map((item) => item.id)
				.sort()
		).toEqual(['s-hidden', 's-page']);
	});

	it('retainRicherSong keeps loaded takes when a summary arrives later', () => {
		const loaded = makeSong({
			id: 's1',
			generation_count: 1,
			generations: [makeGen()]
		});
		const summary = makeSong({
			id: 's1',
			title: 'Updated title',
			generation_count: 0,
			generations: []
		});
		const merged = retainRicherSong(loaded, summary);
		expect(merged.title).toBe('Updated title');
		expect(merged.generation_count).toBe(1);
		expect(merged.generations).toHaveLength(1);
	});

	it('retainRicherSong raises generation_count without dropping loaded takes', () => {
		const loaded = makeSong({
			id: 's1',
			generation_count: 1,
			generations: [makeGen()]
		});
		const summary = makeSong({
			id: 's1',
			generation_count: 2,
			generations: []
		});
		const merged = retainRicherSong(loaded, summary);
		expect(merged.generation_count).toBe(2);
		expect(merged.generations).toHaveLength(1);
	});

	it('overlaySongList preserves loaded takes across a browse reset', () => {
		const existing = [
			makeSong({
				id: 's1',
				generation_count: 1,
				generations: [makeGen()]
			})
		];
		const incoming = [makeSong({ id: 's1', generation_count: 0, generations: [] })];
		expect(overlaySongList(existing, incoming)[0].generations).toHaveLength(1);
	});

	it('upsertSongInList appends an absent song and replaces a present one', () => {
		songList.set([makeSong({ id: 'a' })]);
		upsertSongInList(makeSong({ id: 'b', title: 'B' }));
		upsertSongInList(makeSong({ id: 'a', title: 'A2' }));
		const byId = new Map(get(songList).map((s) => [s.id, s.title]));
		expect([byId.get('a'), byId.get('b')]).toEqual(['A2', 'B']);
	});

	it('selectedGeneration derives from selectedSong', () => {
		songList.set([makeSong()]);
		selectedSongId.set('s1');
		selectedGenerationId.set('g1');
		expect(get(selectedGeneration)?.seed).toBe(42);
	});

	it('selectedGeneration null when no gen selected', () => {
		songList.set([makeSong()]);
		selectedSongId.set('s1');
		selectedGenerationId.set(null);
		expect(get(selectedGeneration)).toBeNull();
	});

	it('filteredSongs filters by album', () => {
		songList.set([makeSong({ album_id: 'a1' }), makeSong({ id: 's2', album_id: 'a2' })]);
		selectedAlbumId.set('a1');
		expect(get(filteredSongs)).toHaveLength(1);
	});

	it('filteredSongs returns all when no album selected', () => {
		songList.set([makeSong(), makeSong({ id: 's2', album_id: 'a2' })]);
		selectedAlbumId.set(null);
		expect(get(filteredSongs)).toHaveLength(2);
	});

	it('selectGenerationInSidebar sets song and gen', () => {
		const gen = makeGen();
		const song = makeSong();
		selectGenerationInSidebar(gen, song);
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
	});

	it('clearGenerationSelection clears gen id', () => {
		selectedGenerationId.set('g1');
		clearGenerationSelection();
		expect(get(selectedGenerationId)).toBeNull();
	});
});

describe('playback dispatch', () => {
	it('playGeneration delegates to audioPlayer.load', () => {
		const gen = makeGen();
		const song = makeSong();
		playGeneration(gen, song);
		expect(audioPlayer.load).toHaveBeenCalledWith({
			generation: gen,
			songId: 's1',
			songTitle: 'Song',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		});
	});

	it('playGeneration maps version lyrics, never the song draft', () => {
		const gen = makeGen({ version_lyrics: 'old verse' });
		const song = makeSong({ lyrics: 'latest draft', album_title: 'Nachtstrom' });
		expect(toPlaybackInfo(gen, song)).toEqual({
			generation: gen,
			songId: 's1',
			songTitle: 'Song',
			artist: 'Artist',
			albumTitle: 'Nachtstrom',
			lyrics: 'old verse'
		});
		playGeneration(gen, song);
		expect(audioPlayer.load).toHaveBeenCalledWith({
			generation: gen,
			songId: 's1',
			songTitle: 'Song',
			artist: 'Artist',
			albumTitle: 'Nachtstrom',
			lyrics: 'old verse'
		});
	});

	it('playGeneration can request a clean restart', () => {
		const gen = makeGen();
		const song = makeSong();
		playGeneration(gen, song, { restart: true });
		expect(audioPlayer.load).toHaveBeenCalledWith(
			{
				generation: gen,
				songId: 's1',
				songTitle: 'Song',
				artist: 'Artist',
				albumTitle: 'Album',
				lyrics: null
			},
			{ restart: true }
		);
	});

	it('navigateToPlaying selects the playing song', async () => {
		const song = makeSong();
		songList.set([song]);
		playGeneration(makeGen(), song);
		selectedAlbumId.set(null);
		selectedSongId.set(null);

		await navigateToPlaying();

		expect(get(selectedAlbumId)).toBe('a1');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
	});

	it('navigateToPlaying does nothing with no playback', () => {
		audioPlayer.current = null;
		selectedSongId.set('keep');
		navigateToPlaying();
		expect(get(selectedSongId)).toBe('keep');
	});

	it('navigateToPlaying fetches a song missing from the library page', async () => {
		songList.set([]);
		const hidden = makeSong({ id: 's-hidden', album_id: 'a-hidden', title: 'Hidden' });
		vi.mocked(fetchSong).mockResolvedValueOnce(hidden);
		playGeneration(makeGen({ song_id: 's-hidden' }), hidden);
		selectedAlbumId.set(null);
		selectedSongId.set('keep');

		await navigateToPlaying();

		expect(fetchSong).toHaveBeenCalledWith('s-hidden');
		expect(get(songList).map((s) => s.id)).toContain('s-hidden');
		expect(get(selectedAlbumId)).toBe('a-hidden');
		expect(get(selectedSongId)).toBe('s-hidden');
	});

	it('navigateToPlaying does nothing if playing song is not in list', async () => {
		songList.set([]);
		playGeneration(makeGen(), makeSong());
		vi.mocked(fetchSong).mockRejectedValueOnce(new Error('offline'));
		selectedSongId.set('keep');
		await navigateToPlaying();
		expect(get(selectedSongId)).toBe('keep');
	});

	it('handlePlaybackEnded advances album playback to the next song', async () => {
		const firstGen = makeGen({ id: 'g1', song_id: 's1' });
		const secondGen = makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/song2.mp3' });
		const firstSong = makeSong({
			id: 's1',
			title: 'First',
			album_id: 'a1',
			track_number: 1,
			generations: [firstGen]
		});
		const secondSong = makeSong({
			id: 's2',
			title: 'Second',
			album_id: 'a1',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		playGeneration(firstGen, firstSong);

		handlePlaybackEnded();
		await Promise.resolve();

		expect(audioPlayer.load).toHaveBeenLastCalledWith({
			generation: secondGen,
			songId: 's2',
			songTitle: 'Second',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		});
	});

	it('handlePlaybackEnded advances playlist playback to the next entry', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		playPlaylistEntries(entries);

		handlePlaybackEnded();

		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 1 });
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('records window-end without starting another track', () => {
		handlePlaybackEnded('window-end');

		expect(get(windowEnded)).toBe(true);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('clears window-end when playback starts again', () => {
		windowEnded.set(true);

		audioPlayer.onPlaybackStarted?.();

		expect(get(windowEnded)).toBe(false);
	});

	it('clears library feedback when playback switches to a playlist', () => {
		libraryQueueSkipped.set([{ song_id: 's1', generation_id: 'g1', reason: 'missing_file' }]);
		windowEnded.set(true);

		playPlaylistEntries([makePlaylistEntry()]);

		expect(get(libraryQueueSkipped)).toEqual([]);
		expect(get(windowEnded)).toBe(false);
		expect(get(queueContext).type).toBe('playlist');
	});

	it('toggleShuffle flips shuffle mode', async () => {
		expect(get(shuffleEnabled)).toBe(false);
		await toggleShuffle();
		expect(get(shuffleEnabled)).toBe(true);
		await toggleShuffle();
		expect(get(shuffleEnabled)).toBe(false);
	});

	it('persists shuffle in localStorage', async () => {
		await toggleShuffle();
		expect(localStorage.getItem('queueShuffleEnabled')).toBe('true');
		await toggleShuffle();
		expect(localStorage.getItem('queueShuffleEnabled')).toBe('false');
	});

	it('shuffle mode advances playlist playback to another entry', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		shuffleEnabled.set(true);
		playPlaylistEntries(entries);

		await playNextSong();

		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 1 });
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('playNextSong wraps playlist playback at the end', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		playPlaylistEntries(entries, 1);

		await playNextSong();

		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 0 });
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'First' })
		);
	});

	it('playPrevSong wraps playlist playback at the start', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		playPlaylistEntries(entries);

		await playPrevSong();

		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 1 });
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('playNextSong wraps album playback to the first playable song', async () => {
		const firstGen = makeGen({ id: 'g1', song_id: 's1' });
		const secondGen = makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/song2.mp3' });
		const firstSong = makeSong({
			id: 's1',
			title: 'First',
			album_id: 'a1',
			track_number: 1,
			generations: [firstGen]
		});
		const secondSong = makeSong({
			id: 's2',
			title: 'Second',
			album_id: 'a1',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		playGeneration(secondGen, secondSong);

		await playNextSong();

		expect(audioPlayer.load).toHaveBeenLastCalledWith({
			generation: firstGen,
			songId: 's1',
			songTitle: 'First',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		});
	});

	it('playPrevSong wraps album playback to the last playable song', async () => {
		const firstGen = makeGen({ id: 'g1', song_id: 's1' });
		const secondGen = makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/song2.mp3' });
		const firstSong = makeSong({
			id: 's1',
			title: 'First',
			album_id: 'a1',
			track_number: 1,
			generations: [firstGen]
		});
		const secondSong = makeSong({
			id: 's2',
			title: 'Second',
			album_id: 'a1',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		playGeneration(firstGen, firstSong);

		await playPrevSong();

		expect(audioPlayer.load).toHaveBeenLastCalledWith({
			generation: secondGen,
			songId: 's2',
			songTitle: 'Second',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		});
	});
});

describe('canPlay predicates', () => {
	it('canPlayPrevGen false when no current', () => {
		expect(canPlayPrevGen(null, [])).toBe(false);
	});

	it('canPlayPrevGen false when song not found', () => {
		const cur = {
			generation: makeGen(),
			songId: 'unknown',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevGen(cur, [makeSong()])).toBe(false);
	});

	it('canPlayPrevGen true when not at first generation', () => {
		const g1 = makeGen({ id: 'g1' });
		const g2 = makeGen({ id: 'g2' });
		const song = makeSong({ generations: [g1, g2] });
		const cur = {
			generation: g2,
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevGen(cur, [song])).toBe(true);
	});

	it('canPlayNextGen false at last generation', () => {
		const g1 = makeGen();
		const song = makeSong({ generations: [g1] });
		const cur = {
			generation: g1,
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextGen(cur, [song])).toBe(false);
	});

	it('canPlayNextGen false when generation not found in song', () => {
		const song = makeSong({ generations: [makeGen({ id: 'other' })] });
		const cur = {
			generation: makeGen({ id: 'gone' }),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextGen(cur, [song])).toBe(false);
	});

	it('canPlayPrevSong false when no current', () => {
		expect(canPlayPrevSong(null, [], { type: 'library' })).toBe(false);
	});

	it('canPlayNextSong scoped to album in album context', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a2' });
		const cur = {
			generation: makeGen({ id: 'g1' }),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayNextSong true for next song in same album', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a1', generations: [makeGen({ id: 'g2' })] });
		const cur = {
			generation: makeGen({ id: 'g1' }),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(true);
	});

	it('canPlayNextSong skips songs with zero generations', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a1', generation_count: 0, generations: [] });
		const cur = {
			generation: makeGen(),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong skips songs with zero generations', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1', generation_count: 0, generations: [] });
		const s2 = makeSong({ id: 's2', album_id: 'a1' });
		const cur = {
			generation: makeGen({ id: 'g1' }),
			songId: 's2',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong false for a single playable album song', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const cur = {
			generation: makeGen({ id: 'g1' }),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevSong(cur, [s1], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('playlist context: canPlayNextSong based on index', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1, generation_id: 'g2', mp3_path: 'b.mp3' })
		];
		const cur = {
			generation: makeGen(),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
	});

	it('playlist context: canPlayPrevSong true when not at start', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1 })
		];
		const cur = {
			generation: makeGen(),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 1 })).toBe(true);
	});

	it('playlist context: canPlayNextSong false for a single-entry playlist', () => {
		const entries = [makePlaylistEntry({ id: 'pe1', position: 0 })];
		const cur = {
			generation: makeGen(),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(false);
	});

	it('playlist context: canPlayNextSong true at last entry when shuffle is enabled', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1, generation_id: 'g2', mp3_path: 'b.mp3' })
		];
		const cur = {
			generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 1 }, true)).toBe(true);
	});

	it('playlist context derives position from current generation when context index is stale', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0, generation_id: 'g1', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', position: 1, generation_id: 'g2', mp3_path: 'b.mp3' })
		];
		const cur = {
			generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
	});
});

describe('playPlaylistEntries', () => {
	it('sets playlist context and triggers load', () => {
		const entries = [
			makePlaylistEntry({
				id: 'pe1',
				song_title: 'First',
				generation_id: 'g10',
				mp3_path: 'x.mp3'
			}),
			makePlaylistEntry({
				id: 'pe2',
				song_title: 'Second',
				generation_id: 'g11',
				mp3_path: 'y.mp3'
			})
		];
		playPlaylistEntries(entries);
		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 0 });
		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ songTitle: 'First' }));
	});

	it('playPlaylistEntries uses entry lyrics, not a later song draft', () => {
		const entries = [
			makePlaylistEntry({
				id: 'pe1',
				song_title: 'First',
				lyrics: 'old verse',
				album_title: 'Nachtstrom'
			})
		];
		playPlaylistEntries(entries);
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				lyrics: 'old verse',
				albumTitle: 'Nachtstrom',
				generation: expect.objectContaining({ version_lyrics: 'old verse' })
			})
		);
	});

	it('can start playback from a requested playlist entry', () => {
		const entries = [
			makePlaylistEntry({
				id: 'pe1',
				song_title: 'First',
				generation_id: 'g10',
				mp3_path: 'x.mp3'
			}),
			makePlaylistEntry({
				id: 'pe2',
				song_title: 'Second',
				generation_id: 'g11',
				mp3_path: 'y.mp3'
			})
		];
		playPlaylistEntries(entries, 1);
		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 1 });
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				songTitle: 'Second',
				generation: expect.objectContaining({ id: 'g11', mp3_path: 'y.mp3' })
			})
		);
	});

	it('can request a clean restart for a playlist entry', () => {
		const entries = [
			makePlaylistEntry({
				id: 'pe1',
				song_title: 'First',
				generation_id: 'g10',
				mp3_path: 'x.mp3'
			})
		];
		playPlaylistEntries(entries, 0, { restart: true });
		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ songTitle: 'First' }), {
			restart: true
		});
	});

	it('does nothing for empty entries', () => {
		audioPlayer.current = null;
		queueContext.set({ type: 'library' });
		playPlaylistEntries([]);
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(queueContext)).toEqual({ type: 'library' });
	});
});

describe('updateGenerationScores', () => {
	it('updates scores for matching generation', () => {
		songList.set([makeSong()]);
		updateGenerationScores('g1', { dynamics: 80 });
		const songs = get(songList);
		expect(songs[0].generations[0].scores).toEqual({ dynamics: 80 });
	});

	it('does not affect other generations', () => {
		const gen2 = makeGen({ id: 'g2', seed: 99 });
		songList.set([makeSong({ generations: [makeGen(), gen2] })]);
		updateGenerationScores('g1', { dynamics: 80 });
		const songs = get(songList);
		expect(songs[0].generations[1].scores).toBeNull();
	});
});

function makeTrack(overrides: Partial<QueueStreamTrackItem> = {}): QueueStreamTrackItem {
	return {
		key: 't1',
		index: 0,
		entry_id: null,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Song',
		artist: 'Artist',
		album_title: 'Album',
		lyrics: null,
		generation_number: 1,
		mp3_path: 'a.mp3',
		audio_url: '/audio/a.mp3',
		seed: null,
		model_mode: 'sft',
		duration: 180,
		start_offset: 0,
		end_offset: 180,
		...overrides
	};
}

function makeManifest(overrides: Partial<QueueStreamManifest> = {}): QueueStreamManifest {
	return {
		snapshot_id: 'snap1',
		stream_url: 'http://stream.example/queue.m3u8',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: 180,
		tracks: [],
		windowed: false,
		skipped: [],
		skipped_complete: true,
		...overrides
	};
}

describe('stream path', () => {
	let loadStreamSpy: ReturnType<typeof vi.spyOn>;

	beforeEach(() => {
		setQueuePlaybackMode('stream');
		loadStreamSpy = vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('shows error toast and does not call loadStream when stream build fails', async () => {
		vi.mocked(createQueueStreamSnapshot).mockRejectedValueOnce(new Error('network error'));
		const entries = [makePlaylistEntry()];

		playPlaylistEntries(entries);
		await Promise.resolve();

		const current = get(toasts);
		expect(current).toEqual([
			expect.objectContaining({ message: 'Stream unavailable. Tap play to retry.', type: 'error' })
		]);
		expect(loadStreamSpy).not.toHaveBeenCalled();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('shows windowed notice toast when manifest is windowed', async () => {
		const manifest = makeManifest({
			windowed: true,
			tracks: [
				{
					key: 't1',
					index: 0,
					entry_id: 'pe1',
					generation_id: 'g1',
					song_id: 's1',
					song_title: 'Song',
					artist: 'Artist',
					album_title: 'Album',
					lyrics: null,
					generation_number: 1,
					mp3_path: 'a.mp3',
					audio_url: '/audio/a.mp3',
					seed: null,
					model_mode: 'sft',
					duration: 180,
					start_offset: 0,
					end_offset: 180
				}
			]
		});
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(manifest);
		const entries = [makePlaylistEntry()];

		playPlaylistEntries(entries);
		await Promise.resolve();

		const infoToasts = get(toasts).filter((t) => t.type === 'info');
		expect(infoToasts).toHaveLength(1);
		expect(infoToasts[0].message).toMatch(/Streaming the first 1 tracks/);
	});

	it('does not show windowed notice when manifest is not windowed', async () => {
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(makeManifest({ windowed: false }));
		const entries = [makePlaylistEntry()];

		playPlaylistEntries(entries);
		await Promise.resolve();

		const infoToasts = get(toasts).filter((t) => t.type === 'info');
		expect(infoToasts).toHaveLength(0);
	});
});

describe('playLibraryFromGeneration', () => {
	let loadStreamSpy: ReturnType<typeof vi.spyOn>;

	beforeEach(() => {
		setQueuePlaybackMode('stream');
		loadStreamSpy = vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('loads stream at the index matching the requested generation', async () => {
		const gen = makeGen({ id: 'g2' });
		const manifest = makeManifest({
			tracks: [
				makeTrack({ generation_id: 'g1', index: 0 }),
				makeTrack({ generation_id: 'g2', index: 1 })
			]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(gen);

		expect(loadStreamSpy).toHaveBeenCalledWith(manifest, 1, { restart: true });
	});

	it('does not load a substitute track when the requested generation is absent from the manifest', async () => {
		const gen = makeGen({ id: 'g-absent' });
		const manifest = makeManifest({ tracks: [makeTrack({ generation_id: 'g1' })] });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(gen);

		expect(loadStreamSpy).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: QUEUE_TAKE_MISSING_TOAST,
				type: 'error'
			})
		]);
	});

	it('unplayable start take is not labeled as an empty pool', async () => {
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(
			new ApiError(422, QUEUE_STREAM_UNPLAYABLE_START_DETAIL, '/api/queue-streams/library')
		);

		await playLibraryFromGeneration(makeGen({ id: 'g-dead' }));

		expect(get(libraryQueueNotice)).toBe('error');
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
				type: 'error'
			})
		]);
		expect(loadStreamSpy).not.toHaveBeenCalled();
	});

	it('shows error toast and does not call loadStream when library stream build fails', async () => {
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(new Error('server error'));

		await playLibraryFromGeneration(makeGen());

		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: 'Mix queue failed. Tap play to retry.',
				type: 'error'
			})
		]);
		expect(loadStreamSpy).not.toHaveBeenCalled();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('retries the same generation rotation after a failed build, not an unrotated default', async () => {
		const gen = makeGen({ id: 'g2' });
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(
			new Error('cold build timeout')
		);
		await playLibraryFromGeneration(gen);
		expect(loadStreamSpy).not.toHaveBeenCalled();

		const manifest = makeManifest({
			tracks: [
				makeTrack({ generation_id: 'g2', index: 0 }),
				makeTrack({ generation_id: 'g1', index: 1 })
			]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await expect(retryLastPlayIntent()).resolves.toBe(true);

		expect(vi.mocked(createLibraryQueueStreamSnapshot)).toHaveBeenLastCalledWith('g2', {
			shuffle: false,
			pool: 'mix'
		});
		expect(loadStreamSpy).toHaveBeenCalledWith(manifest, 0, { restart: true });
	});

	it('reports no retry intent once a stream start has succeeded', async () => {
		const gen = makeGen({ id: 'g1' });
		const manifest = makeManifest({ tracks: [makeTrack({ generation_id: 'g1' })] });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(gen);

		await expect(retryLastPlayIntent()).resolves.toBe(false);
	});

	it('shows windowed notice for a windowed library manifest', async () => {
		const manifest = makeManifest({
			windowed: true,
			tracks: [makeTrack(), makeTrack({ generation_id: 'g2', index: 1 })]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(makeGen());

		const infoToasts = get(toasts).filter((t) => t.type === 'info');
		expect(infoToasts).toHaveLength(1);
		expect(infoToasts[0].message).toMatch(/Streaming the first 2 tracks/);
	});

	it('preserves whether the library skip report is complete', async () => {
		const manifest = makeManifest({
			skipped_complete: false,
			tracks: [makeTrack()]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(makeGen());

		expect(get(libraryQueueSkippedComplete)).toBe(false);
	});

	it('sends the current shuffle flag with the library snapshot request', async () => {
		setShuffle(true);
		const manifest = makeManifest({ tracks: [makeTrack({ generation_id: 'g1' })] });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(makeGen());

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g1', {
			shuffle: true,
			pool: 'mix'
		});
	});
});

describe('rebuildQueueStream routing', () => {
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('routes library context rebuild to the library endpoint', async () => {
		queueContext.set({ type: 'library' });
		libraryQueueSkipped.set([
			{ song_id: 'old-song', generation_id: 'old-generation', reason: 'missing_file' }
		]);
		libraryQueueSkippedComplete.set(true);
		const freshManifest = makeManifest({
			snapshot_id: 'fresh',
			skipped: [
				{ song_id: 'new-song', generation_id: 'new-generation', reason: 'unreadable_file' }
			],
			skipped_complete: false
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(freshManifest);

		const state: StreamFallbackState = {
			manifest: makeManifest({ tracks: [makeTrack({ generation_id: 'g-cur' })] }),
			trackIndex: 0,
			trackTime: 30
		};
		const result = await rebuildStream(state);

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur', {
			shuffle: false,
			pool: 'mix'
		});
		expect(result).toBe(freshManifest);
		expect(get(libraryQueueSkipped)).toEqual(freshManifest.skipped);
		expect(get(libraryQueueSkippedComplete)).toBe(false);
	});

	it('clears stale library skip feedback when rebuild fails', async () => {
		queueContext.set({ type: 'library' });
		libraryQueueSkipped.set([
			{ song_id: 'old-song', generation_id: 'old-generation', reason: 'missing_file' }
		]);
		libraryQueueSkippedComplete.set(false);
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(new Error('expired'));
		const state: StreamFallbackState = {
			manifest: makeManifest({ tracks: [makeTrack({ generation_id: 'g-cur' })] }),
			trackIndex: 0,
			trackTime: 30
		};

		const result = await rebuildStream(state);

		expect(result).toBeNull();
		expect(get(libraryQueueSkipped)).toEqual([]);
		expect(get(libraryQueueSkippedComplete)).toBe(true);
	});

	it('routes playlist context rebuild to the generic endpoint', async () => {
		const entries = [makePlaylistEntry()];
		queueContext.set({ type: 'playlist', entries, index: 0 });
		const freshManifest = makeManifest({ snapshot_id: 'fresh' });
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(freshManifest);

		const track = makeTrack({ generation_id: 'g1', entry_id: 'pe1' });
		const state: StreamFallbackState = {
			manifest: makeManifest({ tracks: [track] }),
			trackIndex: 0,
			trackTime: 10
		};
		const result = await rebuildStream(state);

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' }
		]);
		expect(result).toBe(freshManifest);
	});
});

describe('playAlbumFromGeneration', () => {
	let loadStreamSpy: ReturnType<typeof vi.spyOn>;

	beforeEach(() => {
		setQueuePlaybackMode('stream');
		loadStreamSpy = vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('streams the clicked take for that song and the pick for the rest', async () => {
		const picked = makeGen({ id: 'g-pick', is_picked: true, song_id: 's1' });
		const clicked = makeGen({
			id: 'g-click',
			is_picked: false,
			song_id: 's1',
			generation_number: 2,
			mp3_path: 'a1/click.mp3'
		});
		const song1 = makeSong({
			id: 's1',
			track_number: 1,
			generations: [picked, clicked],
			generation_count: 2
		});
		const song2Pick = makeGen({ id: 'g2', is_picked: true, song_id: 's2', mp3_path: 'a1/s2.mp3' });
		const song2 = makeSong({
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [song2Pick],
			generation_count: 1
		});
		songList.set([song1, song2]);
		vi.mocked(createQueueStreamSnapshot).mockImplementation(async (tracks) =>
			makeManifest({
				tracks: tracks.map((track, index) =>
					makeTrack({
						generation_id: track.generation_id,
						entry_id: track.entry_id ?? null,
						index,
						key: track.generation_id
					})
				)
			})
		);

		await playAlbumFromGeneration('a1', song1, clicked);
		await Promise.resolve();

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g-click', entry_id: 'album:s1:g-click' },
			{ generation_id: 'g2', entry_id: 'album:s2:g2' }
		]);
		expect(loadStreamSpy).toHaveBeenCalledWith(
			expect.objectContaining({
				tracks: [
					expect.objectContaining({ generation_id: 'g-click' }),
					expect.objectContaining({ generation_id: 'g2' })
				]
			}),
			0,
			expect.objectContaining({ restart: true })
		);
		expect(get(queueContext)).toEqual({ type: 'album', albumId: 'a1' });
	});
});

function makePlayback(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return toPlaybackInfo(gen, song);
}

describe('shuffle rebuilds the playing queue', () => {
	let loadStreamSpy: ReturnType<typeof vi.spyOn>;

	beforeEach(() => {
		setQueuePlaybackMode('stream');
		loadStreamSpy = vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('toggling shuffle mid-library-play rebuilds at the current take and time', async () => {
		const gen = makeGen({ id: 'g-cur' });
		const song = makeSong({ generations: [gen] });
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.currentTime = 14;
		queueContext.set({ type: 'library' });
		const shuffled = makeManifest({
			tracks: [
				makeTrack({ generation_id: 'g-cur', start_offset: 0 }),
				makeTrack({ generation_id: 'g-other', index: 1, start_offset: 180 })
			]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(shuffled);

		await toggleShuffle();

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur', {
			shuffle: true,
			pool: 'mix'
		});
		expect(loadStreamSpy).toHaveBeenCalledWith(shuffled, 0, { restart: true, resumeAt: 14 });
	});

	it('turning shuffle off rebuilds the library in deterministic order', async () => {
		setShuffle(true);
		const gen = makeGen({ id: 'g-cur' });
		const song = makeSong({ generations: [gen] });
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.currentTime = 8;
		queueContext.set({ type: 'library' });
		const sequential = makeManifest({
			tracks: [
				makeTrack({ generation_id: 'g-cur', start_offset: 0 }),
				makeTrack({ generation_id: 'g-other', index: 1, start_offset: 180 })
			]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(sequential);

		await toggleShuffle();

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur', {
			shuffle: false,
			pool: 'mix'
		});
		expect(loadStreamSpy).toHaveBeenCalledWith(sequential, 0, { restart: true, resumeAt: 8 });
	});

	it('album shuffle keeps the current take first and mixes the rest', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		const song1 = makeSong({
			id: 's1',
			track_number: 1,
			generations: [makeGen({ id: 'g1', is_picked: true, song_id: 's1' })]
		});
		const song2 = makeSong({
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [makeGen({ id: 'g2', is_picked: true, song_id: 's2', mp3_path: 'a1/s2.mp3' })]
		});
		const song3 = makeSong({
			id: 's3',
			title: 'Three',
			track_number: 3,
			generations: [makeGen({ id: 'g3', is_picked: true, song_id: 's3', mp3_path: 'a1/s3.mp3' })]
		});
		songList.set([song1, song2, song3]);
		vi.mocked(createQueueStreamSnapshot).mockImplementation(async (tracks) =>
			makeManifest({
				tracks: tracks.map((track, index) =>
					makeTrack({
						generation_id: track.generation_id,
						entry_id: track.entry_id ?? null,
						index,
						key: track.generation_id,
						start_offset: index * 180
					})
				)
			})
		);

		await playAlbumFromGeneration('a1', song1, song1.generations[0]);
		await Promise.resolve();

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'album:s1:g1' },
			{ generation_id: 'g3', entry_id: 'album:s3:g3' },
			{ generation_id: 'g2', entry_id: 'album:s2:g2' }
		]);
	});

	it('cleared shuffle keeps playlist snapshot in original order', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		setShuffle(false);
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(
			makeManifest({
				tracks: entries.map((entry, index) =>
					makeTrack({ generation_id: entry.generation_id, entry_id: entry.id, index })
				)
			})
		);

		await playPlaylistEntries(entries, 0, { restart: true });

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' },
			{ generation_id: 'g2', entry_id: 'pe2' },
			{ generation_id: 'g3', entry_id: 'pe3' }
		]);
	});

	it('turning shuffle off mid-playlist resumes the current entry in original order', async () => {
		setShuffle(true);
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', mp3_path: 'b.mp3' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		audioPlayer.mode = 'stream';
		audioPlayer.current = {
			generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }),
			songId: '',
			songTitle: 'Playlist Song',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		};
		audioPlayer.currentTime = 5;
		queueContext.set({ type: 'playlist', entries, index: 1 });
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(
			makeManifest({
				tracks: [
					makeTrack({ generation_id: 'g1', entry_id: 'pe1', index: 0, start_offset: 0 }),
					makeTrack({
						generation_id: 'g2',
						entry_id: 'pe2',
						index: 1,
						start_offset: 180,
						mp3_path: 'b.mp3'
					}),
					makeTrack({ generation_id: 'g3', entry_id: 'pe3', index: 2, start_offset: 360 })
				]
			})
		);

		await toggleShuffle();

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' },
			{ generation_id: 'g2', entry_id: 'pe2' },
			{ generation_id: 'g3', entry_id: 'pe3' }
		]);
		expect(loadStreamSpy).toHaveBeenCalledWith(expect.anything(), 1, {
			restart: true,
			resumeAt: 185
		});
	});

	it('turning shuffle off mid-album resumes the current take in album order', async () => {
		setShuffle(true);
		const song1 = makeSong({
			id: 's1',
			track_number: 1,
			generations: [makeGen({ id: 'g1', is_picked: true, song_id: 's1' })]
		});
		const song2 = makeSong({
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [makeGen({ id: 'g2', is_picked: true, song_id: 's2', mp3_path: 'a1/s2.mp3' })]
		});
		const song3 = makeSong({
			id: 's3',
			title: 'Three',
			track_number: 3,
			generations: [makeGen({ id: 'g3', is_picked: true, song_id: 's3', mp3_path: 'a1/s3.mp3' })]
		});
		songList.set([song1, song2, song3]);
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(song2.generations[0], song2);
		audioPlayer.currentTime = 6;
		queueContext.set({ type: 'album', albumId: 'a1' });
		vi.mocked(createQueueStreamSnapshot).mockImplementation(async (tracks) =>
			makeManifest({
				tracks: tracks.map((track, index) =>
					makeTrack({
						generation_id: track.generation_id,
						entry_id: track.entry_id ?? null,
						index,
						key: track.generation_id,
						start_offset: index * 180
					})
				)
			})
		);

		await toggleShuffle();

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'album:s1:g1' },
			{ generation_id: 'g2', entry_id: 'album:s2:g2' },
			{ generation_id: 'g3', entry_id: 'album:s3:g3' }
		]);
		expect(loadStreamSpy).toHaveBeenCalledWith(expect.anything(), 1, {
			restart: true,
			resumeAt: 186
		});
	});

	it('playlist play without shuffle keeps entry order', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(
			makeManifest({
				tracks: entries.map((entry, index) =>
					makeTrack({ generation_id: entry.generation_id, entry_id: entry.id, index })
				)
			})
		);

		await playPlaylistEntries(entries, 0, { restart: true });

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' },
			{ generation_id: 'g2', entry_id: 'pe2' },
			{ generation_id: 'g3', entry_id: 'pe3' }
		]);
		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 0 });
	});

	it('playlist shuffle keeps the current entry first and mixes the rest', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(
			makeManifest({
				tracks: [
					makeTrack({ generation_id: 'g1', entry_id: 'pe1', index: 0 }),
					makeTrack({ generation_id: 'g3', entry_id: 'pe3', index: 1 }),
					makeTrack({ generation_id: 'g2', entry_id: 'pe2', index: 2 })
				]
			})
		);

		await playPlaylistEntries(entries, 0, { restart: true });

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' },
			{ generation_id: 'g3', entry_id: 'pe3' },
			{ generation_id: 'g2', entry_id: 'pe2' }
		]);
		expect(get(queueContext)).toEqual({ type: 'playlist', entries, index: 0 });
	});

	it('toggling shuffle mid-playlist-play resumes the current take', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		const currentGen = makeGen({ id: 'g1', mp3_path: 'a1/song_v1.mp3' });
		audioPlayer.mode = 'stream';
		audioPlayer.current = {
			generation: currentGen,
			songId: '',
			songTitle: 'Playlist Song',
			artist: 'Artist',
			albumTitle: 'Album',
			lyrics: null
		};
		audioPlayer.currentTime = 11;
		queueContext.set({ type: 'playlist', entries, index: 0 });
		vi.mocked(createQueueStreamSnapshot).mockResolvedValueOnce(
			makeManifest({
				tracks: [
					makeTrack({ generation_id: 'g1', entry_id: 'pe1', index: 0, start_offset: 0 }),
					makeTrack({ generation_id: 'g3', entry_id: 'pe3', index: 1, start_offset: 180 }),
					makeTrack({ generation_id: 'g2', entry_id: 'pe2', index: 2, start_offset: 360 })
				]
			})
		);

		await toggleShuffle();

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' },
			{ generation_id: 'g3', entry_id: 'pe3' },
			{ generation_id: 'g2', entry_id: 'pe2' }
		]);
		expect(loadStreamSpy).toHaveBeenCalledWith(expect.anything(), 0, {
			restart: true,
			resumeAt: 11
		});
	});

	it('expired library rebuild keeps the shuffle flag', async () => {
		setShuffle(true);
		queueContext.set({ type: 'library' });
		const freshManifest = makeManifest({ snapshot_id: 'fresh' });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(freshManifest);

		const result = await rebuildStream({
			manifest: makeManifest({ tracks: [makeTrack({ generation_id: 'g-cur' })] }),
			trackIndex: 0,
			trackTime: 30
		});

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur', {
			shuffle: true,
			pool: 'mix'
		});
		expect(result).toBe(freshManifest);
	});
});

describe('library take pool', () => {
	let loadStreamSpy: ReturnType<typeof vi.spyOn>;

	beforeEach(() => {
		setQueuePlaybackMode('stream');
		loadStreamSpy = vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('library start sends the stored pool with shuffle', async () => {
		setLibraryTakePool('keeps');
		setShuffle(true);
		const manifest = makeManifest({ tracks: [makeTrack({ generation_id: 'g1' })] });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(makeGen());

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g1', {
			shuffle: true,
			pool: 'keeps'
		});
	});

	it('idle play starts the library snapshot at the chosen pool', async () => {
		setLibraryTakePool('picks');
		const skipped = [
			{ song_id: 's2', generation_id: 'g-missing', reason: 'missing_file' as const }
		];
		const manifest = makeManifest({
			tracks: [makeTrack({ generation_id: 'g-pick' })],
			skipped
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibrary();

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith(null, {
			shuffle: false,
			pool: 'picks'
		});
		expect(loadStreamSpy).toHaveBeenCalledWith(manifest, 0, { restart: true });
		expect(get(queueContext)).toEqual({ type: 'library' });
		expect(get(libraryQueueSkipped)).toEqual(skipped);
	});

	it('empty pool toast names the active pool', async () => {
		setLibraryTakePool('keeps');
		libraryQueueSkipped.set([{ song_id: 'stale', generation_id: 'stale', reason: 'missing_file' }]);
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(
			new ApiError(422, "No playable takes in pool 'keeps'", '/api/queue-streams/library')
		);

		await playLibrary();

		expect(get(libraryQueueNotice)).toBe('empty');
		expect(get(libraryQueueSkipped)).toEqual([]);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Keine Takes (Keeps)', type: 'error' })
		]);
		expect(loadStreamSpy).not.toHaveBeenCalled();
	});

	it('changing pool mid-play rebuilds the library at the current take and time', async () => {
		const gen = makeGen({ id: 'g-cur' });
		const song = makeSong({ generations: [gen] });
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.currentTime = 17;
		queueContext.set({ type: 'library' });
		const next = makeManifest({
			tracks: [makeTrack({ generation_id: 'g-cur', start_offset: 0 })]
		});
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(next);

		await chooseLibraryTakePool('all');

		expect(get(libraryTakePool)).toBe('all');
		expect(localStorage.getItem('libraryTakePool')).toBe('all');
		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur', {
			shuffle: false,
			pool: 'all'
		});
		expect(loadStreamSpy).toHaveBeenCalledWith(next, 0, { restart: true, resumeAt: 17 });
	});

	it('changing pool during album play does not rebuild', async () => {
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(makeGen(), makeSong());
		queueContext.set({ type: 'album', albumId: 'a1' });

		await chooseLibraryTakePool('picks');

		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(libraryTakePool)).toBe('picks');
	});
});
