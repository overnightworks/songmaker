import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import type {
	AlbumItem,
	GenerationItem,
	LibraryPoolQueue,
	LibraryPoolTakeItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	QueueStreamManifest,
	QueueStreamTrackItem,
	SongItem
} from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import {
	createQueueStreamSnapshot,
	fetchLastFailedGeneration,
	fetchLibraryPoolQueue,
	fetchSong,
	fetchSongs
} from '$lib/api/client';
import { toasts } from '$lib/stores/toast';
import {
	ALBUM_ROW_ARCHIVED_ONLY_TOAST,
	ALBUM_ROW_NO_TAKE_TOAST,
	LIBRARY_QUEUE_EMPTY_TITLE,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST
} from '$lib/constants';
import type { StreamFallbackState } from '$lib/services/audioPlayer.svelte';

vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));
vi.mock('$lib/api/fetch', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/fetch')>();
	return { ...actual, handleSessionLost: vi.fn() };
});
vi.mock('$lib/api/client', () => ({
	createQueueStreamSnapshot: vi.fn(),
	createLibraryQueueStreamSnapshot: vi.fn(),
	fetchLibraryPoolQueue: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	}),
	fetchLastFailedGeneration: vi.fn()
}));
vi.mock('$lib/api/songs', () => ({
	recordSongListen: vi.fn().mockResolvedValue(undefined)
}));
vi.mock('./libraryData', async (importOriginal) => ({
	...(await importOriginal<typeof import('./libraryData')>()),
	resetLibraryContinueItems: vi.fn()
}));
import { albumList, resetLibraryContinueItems, songList } from './libraryData';
import {
	buildQueueViewModel,
	canPlayNextSong,
	canPlayPrevSong,
	clearGenerationSelection,
	ensureGenerationsLoaded,
	filteredSongs,
	handlePlaybackEnded,
	idlePlayTarget,
	jumpToQueueIndex,
	closeNowPlaying,
	dockNowPlaying,
	escapeNowPlaying,
	expandNowPlaying,
	navigateToPlaying,
	nowPlayingDockable,
	nowPlayingOpen,
	nowPlayingPanel,
	nowPlayingSurface,
	openNowPlaying,
	playGeneration,
	playTake,
	playTakeAndShowNowPlaying,
	playPlaylistEntry,
	playPlaylistEntryAndShowNowPlaying,
	registerNowPlayingTrigger,
	toPlaybackInfo,
	chooseLibraryTakePool,
	playStartNotice,
	libraryQueueSkipped,
	libraryQueueSkippedComplete,
	curateAlbum,
	curationActive,
	playAlbum,
	playAlbumSong,
	playIdleStart,
	playLibrary,
	playLibraryFromGeneration,
	playAlbumFromGeneration,
	retryLastPlayIntent,
	playNextSong,
	playPrevSong,
	playPlaylistFrom,
	queueContext,
	type PlaylistQueueSource,
	type QueueContext,
	selectAlbum,
	selectSong,
	selectedAlbumId,
	selectedGeneration,
	selectedGenerationId,
	selectedSong,
	selectedSongId,
	setShuffle,
	shuffleEnabled,
	shuffleLabel,
	toggleShuffle,
	windowEnded
} from './player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { createLibraryQueueStreamSnapshot } from '$lib/api/client';
import { recordSongListen } from '$lib/api/songs';
import { SharePlayback } from '$lib/share/sharePlayback.svelte';
import { ApiError, handleSessionLost } from '$lib/api/fetch';
import {
	DEFAULT_DESKTOP_NOW_PLAYING_SURFACE,
	libraryTakePool,
	setDesktopNowPlayingSurface,
	setLibraryTakePool
} from '$lib/stores/playbackSettings';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import { openCollection } from '$lib/stores/collection';
import { RAIL_LIBRARY_LABEL } from '$lib/constants';

async function rebuildStream(state: StreamFallbackState): Promise<QueueStreamManifest | null> {
	const rebuild = audioPlayer.currentCallbacks.onStreamRebuild;
	if (!rebuild) {
		throw new Error('onStreamRebuild is not assigned');
	}
	return rebuild(state);
}

function makeAlbum(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '',
		is_archived: false,
		...overrides
	};
}

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'song',
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
		audio_duration_sec: null,
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
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'a1/song_v1.mp3',
		seed: 42,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

const QUEUE_PLAYLIST: PlaylistQueueSource = { id: 'p1', title: 'Night Drive' };

function makePlaylist(
	entries: PlaylistEntryItem[],
	overrides: Partial<PlaylistDetailItem> = {}
): PlaylistDetailItem {
	return {
		id: QUEUE_PLAYLIST.id,
		title: QUEUE_PLAYLIST.title,
		slug: QUEUE_PLAYLIST.title.toLowerCase().replace(/\s+/g, '-'),
		entry_count: entries.length,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '',
		entries,
		...overrides
	};
}

function playlistQueue(entries: PlaylistEntryItem[], index: number): QueueContext {
	return { type: 'playlist', playlist: QUEUE_PLAYLIST, entries, index };
}

function makePoolTake(overrides: Partial<LibraryPoolTakeItem> = {}): LibraryPoolTakeItem {
	return {
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Song',
		artist: 'Artist',
		album_title: 'Album',
		lyrics: null,
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		seed: 42,
		model_mode: 'sft',
		is_picked: true,
		is_kept: false,
		...overrides
	};
}

function makePoolQueue(overrides: Partial<LibraryPoolQueue> = {}): LibraryPoolQueue {
	return {
		pool: 'mix',
		takes: [makePoolTake()],
		skipped: [],
		skipped_complete: true,
		...overrides
	};
}

function makePlayback(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return toPlaybackInfo(gen, song);
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
	vi.mocked(fetchLastFailedGeneration).mockResolvedValue({ job: null });
	vi.spyOn(audioPlayer, 'load').mockImplementation((info) => {
		audioPlayer.current = info;
	});
});

afterEach(() => {
	// vitest 4: restoreAllMocks only rewinds vi.spyOn spies now: the
	// module-level vi.fn() stubs from the vi.mock('$lib/api/client', ...)
	// factory above need an explicit clear or their call history from one
	// test leaks a "was it called" assertion into the next.
	vi.clearAllMocks();
	vi.restoreAllMocks();
	audioPlayer.current = null;
	songList.set([]);
	albumList.set([]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	queueContext.set({ type: 'library' });
	curationActive.set(false);
	selectedPlaylistDetail.set(null);
	setShuffle(false);
	setLibraryTakePool('mix');
	playStartNotice.set('idle');
	libraryQueueSkipped.set([]);
	windowEnded.set(false);
	audioPlayer.mode = 'classic';
	audioPlayer.currentTime = 0;
	audioPlayer.status = 'idle';
	toasts.set([]);
	nowPlayingSurface.set('closed');
	nowPlayingPanel.set('queue');
	nowPlayingDockable.set(false);
	registerNowPlayingTrigger(null);
	setDesktopNowPlayingSurface(DEFAULT_DESKTOP_NOW_PLAYING_SURFACE);
	localStorage.removeItem('nowPlayingDesktopSurface');
	sidebarOpen.set(false);
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

	it('dedupes concurrent generation loads for the same song', async () => {
		songList.set([]);
		vi.mocked(fetchSong).mockResolvedValueOnce(makeSong({ id: 's-direct' }));

		await Promise.all([ensureGenerationsLoaded('s-direct'), ensureGenerationsLoaded('s-direct')]);

		expect(fetchSong).toHaveBeenCalledTimes(1);
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
		playPlaylistFrom(makePlaylist(entries), 0);

		handlePlaybackEnded();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
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

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(get(windowEnded)).toBe(false);
	});

	it('records the first playing transition for each app take once', () => {
		const song = makeSong({ id: 's-listen' });
		audioPlayer.current = makePlayback(makeGen({ id: 'g-listen-1', song_id: song.id }), song);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.status = 'paused';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		audioPlayer.current = makePlayback(makeGen({ id: 'g-listen-2', song_id: song.id }), song);
		audioPlayer.status = 'playing';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledTimes(2);
		expect(recordSongListen).toHaveBeenNthCalledWith(1, song.id);
		expect(recordSongListen).toHaveBeenNthCalledWith(2, song.id);
	});

	it('invalidates Continue after a successful listen so returning to the wall reloads it', async () => {
		const song = makeSong({ id: 's-listen-refresh' });
		audioPlayer.current = makePlayback(makeGen({ id: 'g-listen-refresh', song_id: song.id }), song);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		await Promise.resolve();
		await Promise.resolve();

		expect(resetLibraryContinueItems).toHaveBeenCalledOnce();
	});

	it('records a stream take when playback crosses into it', () => {
		const firstSong = makeSong({ id: 's-stream-listen-1' });
		const secondSong = makeSong({ id: 's-stream-listen-2' });
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(
			makeGen({ id: 'g-stream-listen-1', song_id: firstSong.id }),
			firstSong
		);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		audioPlayer.current = makePlayback(
			makeGen({ id: 'g-stream-listen-2', song_id: secondSong.id }),
			secondSong
		);
		audioPlayer.currentCallbacks.onCurrentChange?.(audioPlayer.current);

		expect(recordSongListen).toHaveBeenCalledTimes(2);
		expect(recordSongListen).toHaveBeenNthCalledWith(1, firstSong.id);
		expect(recordSongListen).toHaveBeenNthCalledWith(2, secondSong.id);
	});

	it('does not record a replacement take until it starts playing', () => {
		const firstSong = makeSong({ id: 's-replacement-listen-1' });
		const secondSong = makeSong({ id: 's-replacement-listen-2' });
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(
			makeGen({ id: 'g-replacement-listen-1', song_id: firstSong.id }),
			firstSong
		);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		vi.mocked(recordSongListen).mockClear();

		audioPlayer.current = makePlayback(
			makeGen({ id: 'g-replacement-listen-2', song_id: secondSong.id }),
			secondSong
		);
		audioPlayer.status = 'loading';
		audioPlayer.currentCallbacks.onCurrentChange?.(audioPlayer.current);
		audioPlayer.status = 'error';

		expect(recordSongListen).not.toHaveBeenCalled();

		audioPlayer.status = 'playing';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledOnce();
		expect(recordSongListen).toHaveBeenCalledWith(secondSong.id);
	});

	it('logs a reporting failure without interrupting playback', async () => {
		const song = makeSong({ id: 's-listen-error' });
		audioPlayer.current = makePlayback(makeGen({ id: 'g-listen-error', song_id: song.id }), song);
		const reportingError = new Error('offline');
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		vi.mocked(recordSongListen).mockRejectedValueOnce(reportingError);
		audioPlayer.status = 'playing';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		await Promise.resolve();
		await Promise.resolve();

		expect(recordSongListen).toHaveBeenCalledWith(song.id);
		expect(logged).toHaveBeenCalledWith('Could not record song listen:', reportingError);
		expect(resetLibraryContinueItems).not.toHaveBeenCalled();
	});

	it('does not record while share playback owns the audio callback', () => {
		const song = makeSong({ id: 's-share-listen' });
		const sharePlayback = new SharePlayback();
		sharePlayback.start(
			{
				kind: 'song',
				title: 'Shared song',
				artist: 'Artist',
				albumTitle: null,
				year: null,
				cover: null,
				tracks: []
			},
			null
		);
		audioPlayer.current = makePlayback(makeGen({ id: 'g-share-listen', song_id: song.id }), song);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).not.toHaveBeenCalled();
		sharePlayback.stop();
	});

	it('clears library feedback when playback switches to a playlist', () => {
		libraryQueueSkipped.set([{ song_id: 's1', generation_id: 'g1', reason: 'missing_file' }]);
		windowEnded.set(true);

		playPlaylistFrom(makePlaylist([makePlaylistEntry()]), 0);

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
		playPlaylistFrom(makePlaylist(entries), 0);

		await playNextSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('restores the playlist order when shuffle is turned off', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0, generation_id: 'g1', song_title: 'First' }),
			makePlaylistEntry({
				id: 'pe2',
				position: 1,
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			}),
			makePlaylistEntry({
				id: 'pe3',
				position: 2,
				generation_id: 'g3',
				song_title: 'Third',
				mp3_path: 'c.mp3'
			})
		];
		playPlaylistFrom(makePlaylist(entries), 2);
		const inOrder = get(queueContext);
		if (inOrder.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(inOrder.entries.map((entry) => entry.id)).toEqual(['pe1', 'pe2', 'pe3']);

		await toggleShuffle();
		const shuffled = get(queueContext);
		if (shuffled.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(shuffled.entries[0]?.id).toBe('pe3');
		expect(shuffled.entries.map((entry) => entry.id)).not.toEqual(['pe1', 'pe2', 'pe3']);

		await toggleShuffle();
		const restored = get(queueContext);
		if (restored.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(restored.entries.map((entry) => entry.id)).toEqual(['pe1', 'pe2', 'pe3']);
	});

	it('playNextSong wraps playlist playback at the end', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		playPlaylistFrom(makePlaylist(entries), 1);

		await playNextSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'First' })
		);
	});

	it('playPrevSong wraps playlist playback at the start', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1', song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2', song_title: 'Second', mp3_path: 'b.mp3' })
		];
		playPlaylistFrom(makePlaylist(entries), 0);

		await playPrevSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
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
		expect(canPlayNextSong(cur, [], playlistQueue(entries, 0))).toBe(true);
		expect(canPlayPrevSong(cur, [], playlistQueue(entries, 0))).toBe(true);
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
		expect(canPlayPrevSong(cur, [], playlistQueue(entries, 1))).toBe(true);
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
		expect(canPlayNextSong(cur, [], playlistQueue(entries, 0))).toBe(false);
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
		expect(canPlayNextSong(cur, [], playlistQueue(entries, 1), true)).toBe(true);
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
		expect(canPlayNextSong(cur, [], playlistQueue(entries, 0))).toBe(true);
		expect(canPlayPrevSong(cur, [], playlistQueue(entries, 0))).toBe(true);
	});
});

// jsdom gives the player no media element, so its own play/pause/toggle are
// no-ops and a stopped take would be indistinguishable from a running one.
// This puts the loaded take into the playing state and lets a toggle move it
// out again, the way a real element does — so a click that pauses is visible
// as a status, not as a spied call.
function startPlayingWithoutAnAudioElement(): void {
	audioPlayer.status = 'playing';
	vi.mocked(audioPlayer.load).mockClear();
	vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {
		audioPlayer.status = audioPlayer.status === 'playing' ? 'paused' : 'playing';
	});
}

describe('playPlaylistFrom', () => {
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
		playPlaylistFrom(makePlaylist(entries), 0);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ songTitle: 'First' }), {
			restart: true
		});
	});

	it('playPlaylistFrom uses entry lyrics, not a later song draft', () => {
		const entries = [
			makePlaylistEntry({
				id: 'pe1',
				song_title: 'First',
				lyrics: 'old verse',
				album_title: 'Nachtstrom'
			})
		];
		playPlaylistFrom(makePlaylist(entries), 0);
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				lyrics: 'old verse',
				albumTitle: 'Nachtstrom',
				generation: expect.objectContaining({ version_lyrics: 'old verse' })
			}),
			{ restart: true }
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
		playPlaylistFrom(makePlaylist(entries), 1);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				songTitle: 'Second',
				generation: expect.objectContaining({ id: 'g11', mp3_path: 'y.mp3' })
			}),
			{ restart: true }
		);
	});

	it('does nothing for empty entries', () => {
		audioPlayer.current = null;
		queueContext.set({ type: 'library' });
		playPlaylistFrom(makePlaylist([]), 0);
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(queueContext)).toEqual({ type: 'library' });
	});
});

describe('a clicked playlist row', () => {
	const entries = [
		makePlaylistEntry({ id: 'pe1', song_title: 'First', generation_id: 'g10', mp3_path: 'x.mp3' }),
		makePlaylistEntry({ id: 'pe2', song_title: 'Second', generation_id: 'g11', mp3_path: 'y.mp3' })
	];

	it('plays from that entry and shows the take in Now Playing', async () => {
		await playPlaylistEntryAndShowNowPlaying(makePlaylist(entries), 1);

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('leaves Now Playing alone when only the row play button was used', () => {
		playPlaylistEntry(makePlaylist(entries), 1);

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(get(nowPlayingOpen)).toBe(false);
	});

	it('toggles playback rather than restarting the entry that is already playing', () => {
		const toggle = vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {});
		playPlaylistEntry(makePlaylist(entries), 1);
		vi.mocked(audioPlayer.load).mockClear();

		playPlaylistEntry(makePlaylist(entries), 1);

		expect(toggle).toHaveBeenCalledTimes(1);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('leaves the entry it is already playing playing, and does not start it over', async () => {
		await playPlaylistEntryAndShowNowPlaying(makePlaylist(entries), 1);
		startPlayingWithoutAnAudioElement();
		closeNowPlaying();

		await playPlaylistEntryAndShowNowPlaying(makePlaylist(entries), 1);

		expect(audioPlayer.status).toBe('playing');
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});
});

describe('a playlist queue keeps its own identity', () => {
	const entries = () => [
		makePlaylistEntry({ id: 'pe1', position: 0, generation_id: 'g1', song_title: 'First' }),
		makePlaylistEntry({
			id: 'pe2',
			position: 1,
			generation_id: 'g2',
			song_title: 'Second',
			mp3_path: 'b.mp3'
		}),
		makePlaylistEntry({
			id: 'pe3',
			position: 2,
			generation_id: 'g3',
			song_title: 'Third',
			mp3_path: 'c.mp3'
		})
	];

	function playingPlaylist(): { playlist: PlaylistQueueSource; entries: PlaylistEntryItem[] } {
		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		return { playlist: ctx.playlist, entries: ctx.entries };
	}

	it('still names the playlist it plays after the listener opens an album', () => {
		const queued = entries();
		playPlaylistFrom(makePlaylist(queued), 0);

		openCollection.set({ kind: 'album', id: 'a1' });
		selectedPlaylistDetail.set(null);

		expect(playingPlaylist().playlist).toEqual(QUEUE_PLAYLIST);
		expect(playingPlaylist().entries.map((entry) => entry.song_title)).toEqual([
			'First',
			'Second',
			'Third'
		]);
	});

	it('still names the playlist it plays after a shuffle toggle reorders the queue', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		playPlaylistFrom(makePlaylist(entries()), 0);

		await toggleShuffle();

		expect(playingPlaylist().entries.map((entry) => entry.id)).toEqual(['pe1', 'pe3', 'pe2']);
		expect(playingPlaylist().playlist).toEqual(QUEUE_PLAYLIST);
		expect(get(shuffleLabel)).toBe('Disable shuffle (this playlist)');
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

describe('native first play ignores stream settings', () => {
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		toasts.set([]);
	});

	it('playPlaylistFrom loads the first take natively without concat', async () => {
		const entries = [makePlaylistEntry()];
		playPlaylistFrom(makePlaylist(entries), 0);
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ songTitle: 'Playlist Song' }),
			{ restart: true }
		);
	});

	it('playing an album without a playable take reports it like an empty pool', async () => {
		albumList.set([makeAlbum({ id: 'a1', title: 'Nachtstrom' })]);
		songList.set([makeSong({ generation_count: 0, generations: [] })]);
		await playAlbum('a1');
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('empty');
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: `${LIBRARY_QUEUE_EMPTY_TITLE} (Nachtstrom)`,
				type: 'error'
			})
		]);
	});

	it('idle play on an empty playlist reports it like an empty pool', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '',
			entries: []
		});
		await playIdleStart();
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('empty');
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: `${LIBRARY_QUEUE_EMPTY_TITLE} (Night Drive)`,
				type: 'error'
			})
		]);
	});

	it('playAlbum loads the first take natively without concat', async () => {
		const song = makeSong({ generations: [makeGen({ is_picked: true })] });
		songList.set([song]);
		await playAlbum('a1');
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g1', mp3_path: 'a1/song_v1.mp3' })
			}),
			{ restart: true }
		);
	});

	it('loads the first album take before later songs resolve', async () => {
		songList.set([
			makeSong({ id: 's1', track_number: 1, generation_count: 1, generations: [] }),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: []
			})
		]);
		let resolveSecond: ((song: SongItem) => void) | undefined;
		vi.mocked(fetchSong).mockImplementation((id: string) => {
			if (id === 's1') {
				return Promise.resolve(
					makeSong({
						id: 's1',
						generation_count: 1,
						generations: [makeGen({ id: 'g-first', is_picked: true })]
					})
				);
			}
			return new Promise((resolve) => {
				resolveSecond = resolve;
			});
		});
		const pending = playAlbum('a1');
		await vi.waitFor(() =>
			expect(audioPlayer.load).toHaveBeenCalledWith(
				expect.objectContaining({
					generation: expect.objectContaining({ id: 'g-first' })
				}),
				{ restart: true }
			)
		);
		await vi.waitFor(() => expect(resolveSecond).toEqual(expect.any(Function)));
		resolveSecond?.(
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g-second', song_id: 's2', is_picked: true })]
			})
		);
		await pending;
	});

	it('second playAlbum does not finish two full fetchSong walks', async () => {
		songList.set(
			[1, 2, 3].map((track) =>
				makeSong({
					id: `s${track}`,
					track_number: track,
					generation_count: 1,
					generations: []
				})
			)
		);
		const fetches: string[] = [];
		const waiters = new Map<string, (song: SongItem) => void>();
		vi.mocked(fetchSong).mockImplementation((id: string) => {
			fetches.push(id);
			return new Promise((resolve) => {
				waiters.set(id, resolve);
			});
		});
		const first = playAlbum('a1');
		await Promise.resolve();
		expect(fetches).toEqual(['s1']);
		const second = playAlbum('a1');
		waiters.get('s1')?.(
			makeSong({
				id: 's1',
				track_number: 1,
				generation_count: 1,
				generations: [makeGen({ id: 'g1', is_picked: true })]
			})
		);
		await vi.waitFor(() => expect(audioPlayer.load).toHaveBeenCalledTimes(1));
		await vi.waitFor(() => expect(fetches).toContain('s2'));
		waiters.get('s2')?.(
			makeSong({
				id: 's2',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', is_picked: true })]
			})
		);
		await vi.waitFor(() => expect(fetches).toContain('s3'));
		waiters.get('s3')?.(
			makeSong({
				id: 's3',
				track_number: 3,
				generation_count: 1,
				generations: [makeGen({ id: 'g3', song_id: 's3', is_picked: true })]
			})
		);
		await Promise.all([first, second]);
		expect(fetches).toEqual(['s1', 's2', 's3']);
	});
});

describe('playLibraryFromGeneration', () => {
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		toasts.set([]);
	});

	it('does not call createLibraryQueueStreamSnapshot and loads the start take natively', async () => {
		const gen = makeGen({ id: 'g2' });
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g2', song_id: 's2', song_title: 'Two' }),
					makePoolTake({ generation_id: 'g1', is_picked: false, is_kept: true })
				]
			})
		);

		await playLibraryFromGeneration(gen);

		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: 'g2',
			shuffle: false,
			pool: 'mix',
			signal: expect.any(AbortSignal)
		});
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g2' }),
				songTitle: 'Two'
			}),
			{ restart: true }
		);
	});

	it('does not load a substitute track when the requested generation is absent from the queue', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [makePoolTake({ generation_id: 'g1' })] })
		);

		await playLibraryFromGeneration(makeGen({ id: 'g-absent' }));

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: QUEUE_TAKE_MISSING_TOAST,
				type: 'error'
			})
		]);
	});

	it('unplayable start take is not labeled as an empty pool', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(
			new ApiError(422, QUEUE_STREAM_UNPLAYABLE_START_DETAIL, '/api/library/pool-queue')
		);

		await playLibraryFromGeneration(makeGen({ id: 'g-dead' }));

		expect(get(playStartNotice)).toBe('error');
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
				type: 'error'
			})
		]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('shows error toast and does not load when membership fetch fails', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('server error'));

		await playLibraryFromGeneration(makeGen());

		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: '+ Keeps queue failed. Press play to retry.',
				type: 'error'
			})
		]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('retries the same generation rotation after a failed membership fetch', async () => {
		const gen = makeGen({ id: 'g2' });
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('timeout'));
		await playLibraryFromGeneration(gen);
		expect(audioPlayer.load).not.toHaveBeenCalled();

		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g2' }),
					makePoolTake({ generation_id: 'g1', is_picked: false, is_kept: true })
				]
			})
		);

		await expect(retryLastPlayIntent()).resolves.toBe(true);
		expect(vi.mocked(fetchLibraryPoolQueue)).toHaveBeenLastCalledWith({
			startGenerationId: 'g2',
			shuffle: false,
			pool: 'mix',
			signal: expect.any(AbortSignal)
		});
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) }),
			{ restart: true }
		);
	});

	it('reports no retry intent once a native start has succeeded', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		await playLibraryFromGeneration(makeGen());
		await expect(retryLastPlayIntent()).resolves.toBe(false);
	});

	it('preserves whether the library skip report is complete', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ skipped_complete: false })
		);
		await playLibraryFromGeneration(makeGen());
		expect(get(libraryQueueSkippedComplete)).toBe(false);
	});

	it('sends the current shuffle flag with the membership request', async () => {
		setShuffle(true);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		await playLibraryFromGeneration(makeGen());
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: 'g1',
			shuffle: true,
			pool: 'mix',
			signal: expect.any(AbortSignal)
		});
	});

	it('does not wrap Mix next when the membership window is incomplete', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g1' }),
					makePoolTake({ generation_id: 'g2', song_id: 's2', song_title: 'Two' })
				],
				skipped_complete: false
			})
		);
		await playLibrary();
		await playNextSong();
		const lastLoad = vi.mocked(audioPlayer.load).mock.calls.at(-1);
		await playNextSong();
		expect(get(windowEnded)).toBe(true);
		expect(vi.mocked(audioPlayer.load).mock.calls.at(-1)).toBe(lastLoad);
		expect(canPlayNextSong(audioPlayer.current, get(songList), get(queueContext))).toBe(false);
	});

	it('wraps Mix next when the membership window is complete', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g1' }),
					makePoolTake({ generation_id: 'g2', song_id: 's2', song_title: 'Two' })
				],
				skipped_complete: true
			})
		);
		await playLibrary();
		await playNextSong();
		await playNextSong();
		expect(get(windowEnded)).toBe(false);
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g1' }) })
		);
	});

	it('next stays in Mix and does not fall through to All', async () => {
		const mixKept = makePoolTake({
			generation_id: 'g-keep',
			song_id: 's2',
			song_title: 'Keep',
			is_picked: false,
			is_kept: true,
			mp3_path: 'keep.mp3'
		});
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [makePoolTake({ generation_id: 'g-pick' }), mixKept]
			})
		);
		songList.set([
			makeSong({
				id: 's1',
				generations: [makeGen({ id: 'g-pick', is_picked: true })]
			}),
			makeSong({
				id: 's-plain',
				title: 'Plain',
				generations: [makeGen({ id: 'g-plain', is_picked: false, is_kept: false })]
			})
		]);
		await playLibraryFromGeneration(makeGen({ id: 'g-pick' }));
		await playNextSong();
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g-keep' }),
				songTitle: 'Keep'
			})
		);
	});

	it('a second play aborts the in-flight membership GET and loads only the later start', async () => {
		let firstSignal: AbortSignal | undefined;
		vi.mocked(fetchLibraryPoolQueue).mockImplementationOnce((opts) => {
			firstSignal = opts?.signal;
			return new Promise((_resolve, reject) => {
				opts?.signal?.addEventListener('abort', () => {
					reject(new DOMException('Aborted', 'AbortError'));
				});
			});
		});
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [makePoolTake({ generation_id: 'g-second', song_title: 'Second' })] })
		);

		const first = playLibraryFromGeneration(makeGen({ id: 'g-first' }));
		await playLibraryFromGeneration(makeGen({ id: 'g-second' }));
		await first;

		expect(firstSignal?.aborted).toBe(true);
		expect(audioPlayer.load).toHaveBeenCalledTimes(1);
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g-second' }),
				songTitle: 'Second'
			}),
			{ restart: true }
		);
		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
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
		queueContext.set(playlistQueue(entries, 0));
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
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		toasts.set([]);
	});

	it('keeps the version on an album queue row, which is built from playlist-shaped entries', async () => {
		// The album queue round-trips its takes through PlaylistEntryItem, and
		// that conversion used to drop version_number — leaving rows reading
		// "take 2" where every other take surface says "v3 · take 2".
		const gen = makeGen({
			id: 'g-v3',
			song_id: 's1',
			version_number: 3,
			generation_number: 2,
			is_picked: true
		});
		const song = makeSong({ id: 's1', track_number: 1, generations: [gen], generation_count: 1 });
		songList.set([song]);

		await playAlbumFromGeneration('a1', song, gen);

		const vm = buildQueueViewModel(get(queueContext), audioPlayer.current);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 3, generationNumber: 2 }));
	});

	it('loads the clicked take natively without concat', async () => {
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

		await playAlbumFromGeneration('a1', song1, clicked);

		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g-click', mp3_path: 'a1/click.mp3' })
			}),
			{ restart: true }
		);
		expect(get(queueContext)).toEqual(expect.objectContaining({ type: 'album', albumId: 'a1' }));
	});
});

describe('playAlbumSong', () => {
	beforeEach(() => {
		setQueuePlaybackMode('classic');
		toasts.set([]);
	});

	it('loads the takes of a song whose album was just switched to, then plays its pick', async () => {
		// #141/4: the album list only carries generation_count, so a row's play
		// button on a freshly opened album has no take to hand the player yet.
		const picked = makeGen({ id: 'g-pick', song_id: 's9', is_picked: true, mp3_path: 'b/p.mp3' });
		const listed = makeSong({ id: 's9', album_id: 'a2', generations: [], generation_count: 2 });
		songList.set([listed]);
		vi.mocked(fetchSong).mockResolvedValueOnce(
			makeSong({
				id: 's9',
				album_id: 'a2',
				generation_count: 2,
				generations: [makeGen({ id: 'g-first', song_id: 's9' }), picked]
			})
		);

		await playAlbumSong('a2', listed);

		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				generation: expect.objectContaining({ id: 'g-pick' })
			}),
			{ restart: true }
		);
		expect(get(queueContext)).toEqual(expect.objectContaining({ type: 'album', albumId: 'a2' }));
	});

	it('skips an archived take, which its row offers no way to play', async () => {
		const listed = makeSong({ id: 's-arch', album_id: 'a3', generations: [], generation_count: 2 });
		songList.set([listed]);
		vi.mocked(fetchSong).mockResolvedValueOnce(
			makeSong({
				id: 's-arch',
				album_id: 'a3',
				generation_count: 2,
				generations: [
					makeGen({ id: 'g-arch', song_id: 's-arch', is_picked: true, is_archived: true }),
					makeGen({ id: 'g-live', song_id: 's-arch', mp3_path: 'a3/live.mp3' })
				]
			})
		);

		await playAlbumSong('a3', listed);

		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g-live' }) }),
			{ restart: true }
		);
	});

	it('reports an all-archived song as archived, not as having no take', async () => {
		const listed = makeSong({ id: 's-arch-only', generations: [], generation_count: 1 });
		songList.set([listed]);
		vi.mocked(fetchSong).mockResolvedValueOnce(
			makeSong({
				id: 's-arch-only',
				generation_count: 1,
				generations: [makeGen({ id: 'g-a', song_id: 's-arch-only', is_archived: true })]
			})
		);

		await playAlbumSong('a1', listed);

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: ALBUM_ROW_ARCHIVED_ONLY_TOAST, type: 'error' })
		]);
	});

	it('says so instead of failing silently when the song has no take', async () => {
		const empty = makeSong({ id: 's-empty', generations: [], generation_count: 0 });
		songList.set([empty]);

		await playAlbumSong('a1', empty);

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: ALBUM_ROW_NO_TAKE_TOAST, type: 'error' })
		]);
	});
});

describe('playAlbum start track', () => {
	beforeEach(() => {
		setQueuePlaybackMode('classic');
		toasts.set([]);
	});

	it('starts on the first track that yields a playable take, skipping a fully archived one', async () => {
		// generation_count counts archived takes, so track 1 looks playable
		// from the list alone — the album must keep walking, not give up.
		const archivedOnly = makeSong({
			id: 's1',
			track_number: 1,
			generation_count: 2,
			generations: [
				makeGen({ id: 'g1a', song_id: 's1', is_picked: true, is_archived: true }),
				makeGen({ id: 'g1b', song_id: 's1', is_archived: true })
			]
		});
		const playable = makeSong({
			id: 's2',
			title: 'Two',
			track_number: 2,
			generation_count: 1,
			generations: [makeGen({ id: 'g2', song_id: 's2', is_picked: true, mp3_path: 'a1/s2.mp3' })]
		});
		songList.set([archivedOnly, playable]);

		await playAlbum('a1');

		expect(get(toasts)).toEqual([]);
		expect(get(playStartNotice)).toBe('idle');
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) }),
			expect.anything()
		);
	});

	it('reports nothing playable only when no track yields a take', async () => {
		songList.set([
			makeSong({
				id: 's1',
				track_number: 1,
				generation_count: 1,
				generations: [makeGen({ id: 'g1', song_id: 's1', is_archived: true })]
			}),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', is_archived: true })]
			})
		]);

		await playAlbum('a1');

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('empty');
	});

	it('toasts and returns the notice to idle when a take load is rejected', async () => {
		songList.set([makeSong({ id: 's1', track_number: 1, generation_count: 1, generations: [] })]);
		vi.mocked(fetchSong).mockRejectedValueOnce(
			new ApiError(429, 'Too many requests', '/api/songs/s1')
		);

		await playAlbum('a1');

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('idle');
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Too many requests', type: 'error' })
		]);
	});

	it('leaves a superseded start silent when its take load is rejected', async () => {
		songList.set([
			makeSong({ id: 's1', album_id: 'a1', track_number: 1, generation_count: 1, generations: [] }),
			makeSong({
				id: 's2',
				album_id: 'a2',
				title: 'Two',
				track_number: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', is_picked: true })]
			})
		]);
		let rejectFirst: ((err: unknown) => void) | undefined;
		vi.mocked(fetchSong).mockImplementationOnce(
			() =>
				new Promise((_resolve, reject) => {
					rejectFirst = reject;
				})
		);

		const first = playAlbum('a1');
		await vi.waitFor(() => expect(rejectFirst).toEqual(expect.any(Function)));

		await playAlbum('a2');
		rejectFirst?.(new ApiError(429, 'Too many requests', '/api/songs/s1'));
		await first;

		expect(get(toasts)).toEqual([]);
		expect(get(playStartNotice)).toBe('idle');
		expect(audioPlayer.load).toHaveBeenCalledTimes(1);
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) }),
			{ restart: true }
		);
	});
});

describe('curateAlbum', () => {
	beforeEach(() => {
		setQueuePlaybackMode('classic');
		toasts.set([]);
	});

	it('starts at the first song without a pick, not track 1', async () => {
		songList.set([
			makeSong({
				id: 's1',
				track_number: 1,
				generation_count: 1,
				generations: [makeGen({ id: 'g1', song_id: 's1', is_picked: true })]
			}),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
			}),
			makeSong({
				id: 's3',
				title: 'Three',
				track_number: 3,
				generation_count: 1,
				generations: [makeGen({ id: 'g3', song_id: 's3', mp3_path: 'a1/s3.mp3' })]
			})
		]);

		await curateAlbum('a1');

		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) }),
			{ restart: true }
		);
		const ctx = get(queueContext);
		expect(ctx.type === 'album' && ctx.index).toBe(1);
	});

	it('starts at track 1 once every song already has a pick', async () => {
		songList.set([
			makeSong({
				id: 's1',
				track_number: 1,
				generation_count: 1,
				generations: [makeGen({ id: 'g1', song_id: 's1', is_picked: true })]
			}),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', is_picked: true, mp3_path: 'a1/s2.mp3' })]
			})
		]);

		await curateAlbum('a1');

		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g1' }) }),
			{ restart: true }
		);
	});

	it('skips a song with no generations, same as the album queue', async () => {
		songList.set([
			makeSong({ id: 's1', track_number: 1, generation_count: 0, generations: [] }),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
			})
		]);

		await curateAlbum('a1');

		const ctx = get(queueContext);
		expect(ctx.type === 'album' && ctx.takes?.length).toBe(1);
	});

	it('reports nothing playable for an album with no takes, and never enters curation mode', async () => {
		albumList.set([makeAlbum({ id: 'a1', title: 'Nachtstrom' })]);
		songList.set([makeSong({ generation_count: 0, generations: [] })]);

		await curateAlbum('a1');

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('empty');
		expect(get(curationActive)).toBe(false);
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: `${LIBRARY_QUEUE_EMPTY_TITLE} (Nachtstrom)`,
				type: 'error'
			})
		]);
	});

	it('turns on curation mode and opens Now Playing straight to the take panel', async () => {
		songList.set([makeSong({ generations: [makeGen({ is_picked: false })] })]);

		await curateAlbum('a1');

		expect(get(curationActive)).toBe(true);
		expect(get(nowPlayingSurface)).not.toBe('closed');
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('closing Now Playing exits curation mode', async () => {
		songList.set([makeSong({ generations: [makeGen({ is_picked: false })] })]);
		await curateAlbum('a1');

		closeNowPlaying();

		expect(get(curationActive)).toBe(false);
	});

	it('playing a different album while curating ends curation mode', async () => {
		songList.set([
			makeSong({ id: 's1', album_id: 'a1', generations: [makeGen({ id: 'g1', song_id: 's1' })] }),
			makeSong({
				id: 's2',
				album_id: 'a2',
				title: 'Two',
				track_number: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a2/s2.mp3' })]
			})
		]);
		await curateAlbum('a1');
		expect(get(curationActive)).toBe(true);

		await playAlbum('a2');

		expect(get(curationActive)).toBe(false);
	});

	it('clicking a take row in the same album while curating ends curation mode', async () => {
		// #251 REVISE: playTake's classic path rebuilds a thin { type: 'album',
		// albumId } context with no takes/index at all — before the fix this
		// left curationActive true, so the bar kept showing "Song 0 of 0" and
		// Skip acted on a queue that no longer existed.
		const gen = makeGen({ id: 'g1', song_id: 's1' });
		const song = makeSong({ id: 's1', album_id: 'a1', generations: [gen] });
		songList.set([song]);
		await curateAlbum('a1');
		expect(get(curationActive)).toBe(true);
		selectedAlbumId.set('a1');

		await playTake(gen, song);

		expect(get(curationActive)).toBe(false);
	});

	it('advancing within the curated queue keeps curation mode active', async () => {
		songList.set([
			makeSong({
				id: 's1',
				track_number: 1,
				generation_count: 1,
				generations: [makeGen({ id: 'g1', song_id: 's1' })]
			}),
			makeSong({
				id: 's2',
				title: 'Two',
				track_number: 2,
				generation_count: 1,
				generations: [makeGen({ id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
			})
		]);
		await curateAlbum('a1');
		expect(get(curationActive)).toBe(true);

		await playNextSong();

		expect(get(curationActive)).toBe(true);
		const ctx = get(queueContext);
		expect(ctx.type === 'album' && ctx.index).toBe(1);
	});
});

describe('shuffle rebuilds the playing queue', () => {
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		toasts.set([]);
	});

	it('toggling shuffle mid-library-play rebuilds at the current take and time', async () => {
		const gen = makeGen({ id: 'g-cur' });
		const song = makeSong({ generations: [gen] });
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.currentTime = 14;
		queueContext.set({ type: 'library' });
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g-cur' }),
					makePoolTake({ generation_id: 'g-other', song_id: 's2' })
				]
			})
		);

		await toggleShuffle();

		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: 'g-cur',
			shuffle: true,
			pool: 'mix',
			signal: expect.any(AbortSignal)
		});
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g-cur' }) }),
			{ restart: true, startAt: 14 }
		);
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

		await playAlbumFromGeneration('a1', song1, song1.generations[0]);

		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		const ctx = get(queueContext);
		expect(ctx.type).toBe('album');
		if (ctx.type !== 'album' || !ctx.takes) throw new Error('expected album takes');
		expect(ctx.takes.map((take) => take.generation.id)).toEqual(['g1', 'g3', 'g2']);
	});

	it('playlist play without shuffle keeps entry order', async () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		playPlaylistFrom(makePlaylist(entries), 0);
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
	});

	it('starting a playlist at a chosen entry clears shuffle and keeps playlist order', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		const entries = [
			makePlaylistEntry({ id: 'pe1', generation_id: 'g1' }),
			makePlaylistEntry({ id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ id: 'pe3', generation_id: 'g3' })
		];
		playPlaylistFrom(makePlaylist(entries), 0);
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(shuffleEnabled)).toBe(false);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
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
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		toasts.set([]);
	});

	it('library start sends the stored pool with shuffle', async () => {
		setLibraryTakePool('mix');
		setShuffle(true);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		await playLibraryFromGeneration(makeGen());
		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: 'g1',
			shuffle: true,
			pool: 'mix',
			signal: expect.any(AbortSignal)
		});
	});

	it('idle play starts the library membership at the chosen pool', async () => {
		setLibraryTakePool('picks');
		const skipped = [
			{ song_id: 's2', generation_id: 'g-missing', reason: 'missing_file' as const }
		];
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				pool: 'picks',
				takes: [makePoolTake({ generation_id: 'g-pick' })],
				skipped
			})
		);

		await playLibrary();

		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: null,
			shuffle: false,
			pool: 'picks',
			signal: expect.any(AbortSignal)
		});
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g-pick' }) }),
			{ restart: true }
		);
		expect(get(queueContext).type).toBe('library');
		expect(get(libraryQueueSkipped)).toEqual(skipped);
	});

	it('empty pool toast names the active pool', async () => {
		setLibraryTakePool('mix');
		libraryQueueSkipped.set([{ song_id: 'stale', generation_id: 'stale', reason: 'missing_file' }]);
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(
			new ApiError(422, "No playable takes in pool 'mix'", '/api/library/pool-queue')
		);

		await playLibrary();

		expect(get(playStartNotice)).toBe('empty');
		expect(get(libraryQueueSkipped)).toEqual([]);
		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: `${LIBRARY_QUEUE_EMPTY_TITLE} (+ Keeps)`,
				type: 'error'
			})
		]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('changing pool mid-play rebuilds the library at the current take and time', async () => {
		const gen = makeGen({ id: 'g-cur' });
		const song = makeSong({ generations: [gen] });
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.currentTime = 17;
		queueContext.set({ type: 'library' });
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [makePoolTake({ generation_id: 'g-cur' })] })
		);

		await chooseLibraryTakePool('all');

		expect(get(libraryTakePool)).toBe('all');
		expect(localStorage.getItem('libraryTakePool')).toBe('all');
		expect(fetchLibraryPoolQueue).toHaveBeenCalledWith({
			startGenerationId: 'g-cur',
			shuffle: false,
			pool: 'all',
			signal: expect.any(AbortSignal)
		});
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g-cur' }) }),
			{ restart: true, startAt: 17 }
		);
	});

	it('changing pool during album play does not rebuild', async () => {
		audioPlayer.current = makePlayback(makeGen(), makeSong());
		queueContext.set({ type: 'album', albumId: 'a1' });

		await chooseLibraryTakePool('picks');

		expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(libraryTakePool)).toBe('picks');
	});
});

describe('idlePlayTarget', () => {
	const albums = [makeAlbum({ id: 'a1', title: 'Nachtstrom' })];
	const playlist = {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '',
		entries: []
	};

	it.each([
		[
			'none: falls back to the named library target',
			null,
			playlist,
			{ type: 'library', label: RAIL_LIBRARY_LABEL }
		],
		[
			'album: names the open album',
			{ kind: 'album' as const, id: 'a1' },
			playlist,
			{ type: 'album', label: 'Nachtstrom', albumId: 'a1' }
		],
		[
			'playlist: names the open playlist',
			{ kind: 'playlist' as const, id: 'p1' },
			playlist,
			{ type: 'playlist', label: 'Night Drive' }
		],
		[
			// A playlist whose detail failed to load (or hasn't loaded yet)
			// has no title and nothing to natively play — fall back to the
			// named library target instead of an empty label and dead Play.
			'playlist: falls back to the library target when the detail failed to load',
			{ kind: 'playlist' as const, id: 'p1' },
			null,
			{ type: 'library', label: RAIL_LIBRARY_LABEL }
		]
	])('%s', (_name, collection, playlistDetail, expected) => {
		const target = idlePlayTarget({ collection, albums, playlist: playlistDetail });
		expect(target).toEqual(expected);
	});
});

describe('playIdleStart', () => {
	beforeEach(() => {
		selectedAlbumId.set(null);
		selectedSongId.set(null);
		selectedPlaylistDetail.set(null);
		openCollection.set(null);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValue(makePoolQueue());
	});

	it('starts the chosen pool when no collection interior is open', async () => {
		await playIdleStart();
		expect(fetchLibraryPoolQueue).toHaveBeenCalled();
		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
	});

	it('starts the open album natively when album interior is selected with no song', async () => {
		const song = makeSong({ generations: [makeGen({ is_picked: true })] });
		songList.set([song]);
		openCollection.set({ kind: 'album', id: 'a1' });
		await playIdleStart();
		expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g1' }) }),
			{ restart: true }
		);
	});

	it('starts the open playlist natively when playlist interior is selected', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '',
			entries: [makePlaylistEntry({ song_title: 'Listed' })]
		});
		await playIdleStart();
		expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ songTitle: 'Listed' }),
			{ restart: true }
		);
	});

	it('keeps shuffle on when Play starts the open playlist, unlike picking an entry', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			makePlaylist([
				makePlaylistEntry({ id: 'pe1', position: 0, generation_id: 'g1', song_title: 'First' }),
				makePlaylistEntry({
					id: 'pe2',
					position: 1,
					generation_id: 'g2',
					song_title: 'Second',
					mp3_path: 'b.mp3'
				}),
				makePlaylistEntry({
					id: 'pe3',
					position: 2,
					generation_id: 'g3',
					song_title: 'Third',
					mp3_path: 'c.mp3'
				})
			])
		);

		await playIdleStart();

		expect(get(shuffleEnabled)).toBe(true);
		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.entries.map((entry) => entry.id)).toEqual(['pe1', 'pe3', 'pe2']);
	});

	it('falls back to the library pool when the open playlist detail failed to load', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(null);
		await playIdleStart();
		expect(fetchLibraryPoolQueue).toHaveBeenCalled();
	});
});

describe('buildQueueViewModel', () => {
	it('classic-mode contexts without takes render current only, with no up next', () => {
		const vm = buildQueueViewModel({ type: 'library' }, makePlayback(makeGen(), makeSong()));
		expect(vm.items).toEqual([]);
		expect(vm.currentIndex).toBe(-1);
		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a native library/album queue', () => {
		const songs = [makeSong({ id: 's1' }), makeSong({ id: 's2' })];
		const current = makePlayback(
			makeGen({ id: 'g1', version_number: 3, generation_number: 2, audio_duration_sec: 200 }),
			songs[0]
		);
		const next = makePlayback(makeGen({ id: 'g2' }), songs[1]);
		const ctx = { type: 'library' as const, takes: [current, next], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.items.map((item) => item.generationId)).toEqual(['g1', 'g2']);
		expect(vm.items[0]?.durationSec).toBe(200);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 3, generationNumber: 2 }));
		expect(vm.currentIndex).toBe(0);
		expect(vm.upNext).toEqual(expect.objectContaining({ generationId: 'g2' }));
	});

	it("reads only a native row's own measured duration, never the song's requested one", () => {
		// A song requested with "auto" (0) duration is the exact shape that
		// used to leak a false 0:00 through the song-level fallback (#258).
		const song = makeSong({ id: 's1', audio_duration: 0 });
		const ownDuration = makePlayback(makeGen({ id: 'g1', audio_duration_sec: 141 }), song);
		const unmeasured = makePlayback(makeGen({ id: 'g2', audio_duration_sec: null }), song);
		const ctx = { type: 'library' as const, takes: [ownDuration, unmeasured], index: 0 };

		const vm = buildQueueViewModel(ctx, ownDuration);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('shows a native row\'s own measured length, not the "auto" (0) duration it was requested with', () => {
		const song = makeSong({ id: 's1', audio_duration: 200 });
		const requestedAuto = makePlayback(
			makeGen({ id: 'g1', generation_params: { audio_duration: 0 }, audio_duration_sec: 188 }),
			song
		);
		const ctx = { type: 'library' as const, takes: [requestedAuto], index: 0 };

		const vm = buildQueueViewModel(ctx, requestedAuto);

		expect(vm.items.map((item) => item.durationSec)).toEqual([188]);
	});

	it("reads a playlist row's own measured duration, showing none for an unmeasured entry", () => {
		const entries = [
			makePlaylistEntry({ id: 'e1', generation_id: 'g1', audio_duration: 141 }),
			makePlaylistEntry({ id: 'e2', generation_id: 'g2', audio_duration: null })
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('carries no version number for a native take with no version (library pool)', () => {
		const song = makeSong();
		const current = makePlayback(makeGen({ version_number: null, generation_number: 5 }), song);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.items[0]).toEqual(
			expect.objectContaining({ versionNumber: null, generationNumber: 5 })
		);
	});

	it('has no up next for a single-item native queue', () => {
		const song = makeSong();
		const current = makePlayback(makeGen(), song);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a playlist queue', () => {
		const entries = [
			makePlaylistEntry({
				id: 'e1',
				generation_id: 'g1',
				song_title: 'First',
				version_number: 4,
				generation_number: 1
			}),
			makePlaylistEntry({ id: 'e2', generation_id: 'g2', song_title: 'Second' })
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.currentIndex).toBe(0);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 4, generationNumber: 1 }));
		expect(vm.upNext).toEqual(expect.objectContaining({ generationId: 'g2' }));
	});
});

describe('jumpToQueueIndex', () => {
	it('plays the take at the requested index in a native queue', () => {
		const songA = makeSong({ id: 's1' });
		const songB = makeSong({ id: 's2' });
		const takes = [
			makePlayback(makeGen({ id: 'g1' }), songA),
			makePlayback(makeGen({ id: 'g2' }), songB)
		];
		queueContext.set({ type: 'library', takes, index: 0 });

		jumpToQueueIndex(1);

		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) })
		);
		expect(get(queueContext)).toEqual({ type: 'library', takes, index: 1 });
	});

	it('plays the entry at the requested index in a playlist queue', () => {
		const entries = [
			makePlaylistEntry({ id: 'e1' }),
			makePlaylistEntry({ id: 'e2', generation_id: 'g2' })
		];
		queueContext.set(playlistQueue(entries, 0));

		jumpToQueueIndex(1);

		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) }),
			{ restart: true }
		);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
	});

	it('seeks the stream engine to the requested track when a shared-link stream is playing', () => {
		const seekToStreamTrack = vi.spyOn(audioPlayer, 'seekToStreamTrack').mockReturnValue(true);
		audioPlayer.mode = 'stream';
		queueContext.set(playlistQueue([makePlaylistEntry({ id: 'e1' })], 0));

		jumpToQueueIndex(2);

		expect(seekToStreamTrack).toHaveBeenCalledWith(2);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});
});

describe('playTake', () => {
	it('plays the take through the classic queue path', async () => {
		const gen = makeGen();
		const song = makeSong();

		await playTake(gen, song);

		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ generation: gen }), {
			restart: true
		});
		expect(get(queueContext)).toEqual({ type: 'library' });
	});

	it('toggles pause instead of restarting when the row take is already playing', async () => {
		const gen = makeGen();
		const song = makeSong();
		audioPlayer.current = toPlaybackInfo(gen, song);
		audioPlayer.status = 'playing';
		const toggle = vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {});

		await playTake(gen, song);

		expect(toggle).toHaveBeenCalledOnce();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('reports a toast instead of throwing when the queue-stream path fails', async () => {
		setQueuePlaybackMode('stream');
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('offline'));

		await playTake(makeGen(), makeSong());

		expect(get(toasts)).toEqual([expect.objectContaining({ type: 'error' })]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});
});

describe('playTakeAndShowNowPlaying', () => {
	it('plays the take and opens Now Playing on the judging panel', async () => {
		const gen = makeGen();
		const song = makeSong();

		await playTakeAndShowNowPlaying(gen, song);

		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ generation: gen }), {
			restart: true
		});
		expect(get(nowPlayingPanel)).toBe('take');
		expect(get(nowPlayingOpen)).toBe(true);
	});

	it('leaves the take it is already playing playing, and does not start it over', async () => {
		const gen = makeGen();
		const song = makeSong();
		await playTakeAndShowNowPlaying(gen, song);
		startPlayingWithoutAnAudioElement();
		closeNowPlaying();

		await playTakeAndShowNowPlaying(gen, song);

		expect(audioPlayer.status).toBe('playing');
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(nowPlayingOpen)).toBe(true);
	});
});

describe('openNowPlaying / closeNowPlaying', () => {
	it('openNowPlaying closes the sidebar and opens on the requested panel', () => {
		toggleSidebar();
		expect(get(sidebarOpen)).toBe(true);

		openNowPlaying('take');

		expect(get(sidebarOpen)).toBe(false);
		expect(get(nowPlayingPanel)).toBe('take');
		expect(get(nowPlayingOpen)).toBe(true);
	});

	it('closeNowPlaying closes and restores focus to the registered trigger', async () => {
		const trigger = document.createElement('button');
		document.body.append(trigger);
		registerNowPlayingTrigger(trigger);
		openNowPlaying('queue');

		closeNowPlaying();
		await Promise.resolve();

		expect(get(nowPlayingOpen)).toBe(false);
		expect(document.activeElement).toBe(trigger);
		trigger.remove();
	});

	it('closeNowPlaying is a no-op while Now Playing is already closed', () => {
		const trigger = document.createElement('button');
		registerNowPlayingTrigger(trigger);
		const focusSpy = vi.spyOn(trigger, 'focus');

		closeNowPlaying();

		expect(focusSpy).not.toHaveBeenCalled();
	});

	it('restores focus to the transport bar trigger that remounts after the full surface', () => {
		const trigger = document.createElement('button');
		document.body.append(trigger);
		registerNowPlayingTrigger(trigger);
		openNowPlaying('queue');
		// The full surface hides the bar, which unregisters its button.
		registerNowPlayingTrigger(null);

		closeNowPlaying();
		registerNowPlayingTrigger(trigger);

		expect(document.activeElement).toBe(trigger);
		trigger.remove();
	});
});

describe('Now Playing surface', () => {
	it('opens full screen where no docked panel fits', () => {
		nowPlayingDockable.set(false);

		openNowPlaying('queue');

		expect(get(nowPlayingSurface)).toBe('full');
	});

	it('opens docked by default where a docked panel fits', () => {
		nowPlayingDockable.set(true);

		openNowPlaying('queue');

		expect(get(nowPlayingSurface)).toBe('docked');
	});

	it('opens on the desktop surface the listener last chose', () => {
		nowPlayingDockable.set(true);
		openNowPlaying('queue');
		expandNowPlaying();
		closeNowPlaying();

		openNowPlaying('queue');

		expect(get(nowPlayingSurface)).toBe('full');
	});

	it('leaves the remembered desktop choice alone when a compact viewport forces full screen', () => {
		nowPlayingDockable.set(false);
		openNowPlaying('queue');
		closeNowPlaying();
		nowPlayingDockable.set(true);

		openNowPlaying('queue');

		expect(get(nowPlayingSurface)).toBe('docked');
	});

	it('Escape steps from full screen back to the docked panel where one fits', () => {
		nowPlayingDockable.set(true);
		openNowPlaying('queue');
		expandNowPlaying();

		escapeNowPlaying();

		expect(get(nowPlayingSurface)).toBe('docked');
	});

	it('Escape closes the docked panel', () => {
		nowPlayingDockable.set(true);
		openNowPlaying('queue');

		escapeNowPlaying();

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('Escape closes a full surface that has no docked panel to fall back to', () => {
		nowPlayingDockable.set(false);
		openNowPlaying('queue');

		escapeNowPlaying();

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('turns a docked panel into the full surface when the viewport loses room for it', () => {
		nowPlayingDockable.set(true);
		openNowPlaying('queue');
		expect(get(nowPlayingSurface)).toBe('docked');

		nowPlayingDockable.set(false);

		expect(get(nowPlayingSurface)).toBe('full');
	});

	it('leaves a closed Now Playing closed when the viewport loses room for the panel', () => {
		nowPlayingDockable.set(true);

		nowPlayingDockable.set(false);

		expect(get(nowPlayingSurface)).toBe('closed');
	});

	it('dockNowPlaying returns to the panel and remembers it', () => {
		nowPlayingDockable.set(true);
		openNowPlaying('queue');
		expandNowPlaying();

		dockNowPlaying();

		expect(get(nowPlayingSurface)).toBe('docked');
		expect(localStorage.getItem('nowPlayingDesktopSurface')).toBe('docked');
	});
});

describe('audioPlayer onAuthLost wiring', () => {
	it('hands a lost stream/media session to the one shared session-lost reaction', async () => {
		const onAuthLost = audioPlayer.currentCallbacks.onAuthLost;
		if (!onAuthLost) throw new Error('onAuthLost is not assigned');

		await onAuthLost();

		expect(handleSessionLost).toHaveBeenCalledOnce();
	});
});
