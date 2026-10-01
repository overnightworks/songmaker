import {
	makeAlbum,
	makeGeneration as makeGen,
	makePlaylistDetail as makeDetail,
	makePlaylistEntry,
	makeSong
} from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { get } from 'svelte/store';
import { sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import type {
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
	fetchPlaylist,
	fetchSong,
	fetchSongs
} from '$lib/api/client';
import { toasts } from '$lib/stores/toast';
import {
	LIBRARY_QUEUE_EMPTY_TITLE,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST
} from '$lib/constants';
import type { StreamFallbackState } from '$lib/services/audioPlayer.svelte';

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$lib/api/fetch', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/fetch')>();
	return { ...actual, handleSessionLost: vi.fn() };
});
vi.mock('$lib/api/client', () => ({
	createQueueStreamSnapshot: vi.fn(),
	createLibraryQueueStreamSnapshot: vi.fn(),
	fetchLibraryPoolQueue: vi.fn(),
	fetchPlaylist: vi.fn(),
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
import { albumList, songList } from './libraryData';
import {
	buildQueueViewModel,
	canPlayNextSong,
	canPlayPrevSong,
	clearGenerationSelection,
	ensureGenerationsLoaded,
	idlePlayTarget,
	jumpToQueueIndex,
	closeNowPlaying,
	dockNowPlaying,
	escapeNowPlaying,
	expandNowPlaying,
	navigateToPlaying,
	nowPlayingDockable,
	nowPlayingFullChosen,
	nowPlayingOpen,
	nowPlayingPanel,
	nowPlayingSurface,
	openNowPlaying,
	playTake,
	playTakeAndShowNowPlaying,
	playPlaylistEntryAndShowNowPlaying,
	registerNowPlayingTrigger,
	chooseLibraryTakePool,
	playStartNotice,
	libraryQueueSkipped,
	libraryQueueSkippedComplete,
	curateAlbum,
	curationActive,
	isPlaylistEntryCurrent,
	playAlbum,
	playIdleStart,
	retryLastPlayIntent,
	playNextSong,
	playPrevSong,
	playbackSource,
	queueContext,
	selectSong,
	selectedAlbumId,
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
import { currentUser } from '$lib/stores/auth';
import type { ResumeQueueSource } from '$lib/stores/playbackResume';
import { ApiError, handleSessionLost, NetworkError } from '$lib/api/fetch';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import {
	libraryTakePool,
	setDesktopNowPlayingSurface,
	setLibraryTakePool
} from '$lib/stores/playbackSettings';
import { loadPlaylistDetail, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';
import { openCollection } from '$lib/stores/collection';
import { PLAYLIST_LOADING_LABEL, RAIL_LIBRARY_LABEL } from '$lib/constants';

const genDefaults = {
	mp3_path: 'a1/song_v1.mp3',
	wav_path: 'a1/song_v1.wav',
	seed: 42,
	model_mode: 'sft',
	created_at: ''
} satisfies Partial<GenerationItem>;

const playlistEntryDefaults = {
	album_title: 'Album',
	mp3_path: 'a1/song_v1.mp3',
	seed: 42
} satisfies Partial<PlaylistEntryItem>;

function queuedSongDefaults(): Partial<SongItem> {
	return { slug: 'song', title: 'Song', generations: [makeGen(genDefaults)], created_at: '' };
}

async function rebuildStream(state: StreamFallbackState): Promise<QueueStreamManifest | null> {
	const rebuild = audioPlayer.currentCallbacks.onStreamRebuild;
	if (!rebuild) {
		throw new Error('onStreamRebuild is not assigned');
	}
	return rebuild(state);
}

type PlaylistQueueSource = Pick<PlaylistDetailItem, 'id' | 'title'>;
type QueueContext = Parameters<typeof queueContext.set>[0];

const QUEUE_PLAYLIST: PlaylistQueueSource = { id: 'p1', title: 'Night Drive' };

const playlistDefaults = {
	id: QUEUE_PLAYLIST.id,
	title: QUEUE_PLAYLIST.title,
	slug: QUEUE_PLAYLIST.title.toLowerCase().replace(/\s+/g, '-'),
	share_slug: null,
	created_at: ''
} satisfies Partial<PlaylistDetailItem>;

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
	return {
		generation: gen,
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		albumTitle: song.album_title,
		lyrics: gen.version_lyrics
	};
}

beforeEach(() => {
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
	vi.spyOn(audioPlayer, 'preload').mockImplementation(() => {});
});

afterEach(() => {
	resetConnectivityForTests();
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
	setDesktopNowPlayingSurface('docked');
	localStorage.removeItem('nowPlayingDesktopSurface');
	sidebarOpen.set(false);
	localStorage.removeItem('queueShuffleEnabled');
	localStorage.removeItem('libraryTakePool');
});

describe('browsing state', () => {
	it('selectSong sets song and clears gen', () => {
		selectedGenerationId.set('g1');
		selectSong('s2');
		expect(get(selectedSongId)).toBe('s2');
		expect(get(selectedGenerationId)).toBeNull();
	});

	it('selectedSong derives from songList', () => {
		songList.set([makeSong(queuedSongDefaults())]);
		selectedSongId.set('s1');
		expect(get(selectedSong)?.title).toBe('Song');
	});

	it('selectedSong returns null for unknown id', () => {
		songList.set([makeSong(queuedSongDefaults())]);
		selectedSongId.set('unknown');
		expect(get(selectedSong)).toBeNull();
	});

	it('ensureGenerationsLoaded refetches when loaded takes are fewer than generation_count', async () => {
		songList.set([
			makeSong({
				...queuedSongDefaults(),
				id: 's-partial',
				generation_count: 2,
				generations: [makeGen(genDefaults)]
			})
		]);
		const full = makeSong({
			...queuedSongDefaults(),
			id: 's-partial',
			generation_count: 2,
			generations: [makeGen(genDefaults), makeGen({ ...genDefaults, id: 'g2' })]
		});
		vi.mocked(fetchSong).mockResolvedValueOnce(full);
		await ensureGenerationsLoaded('s-partial');
		expect(get(songList).find((item) => item.id === 's-partial')?.generations).toHaveLength(2);
	});

	it('ensureGenerationsLoaded fetches and adds a song opened directly, not yet in the list', async () => {
		// Felix, 2026-07-18: clicking a song directly (from a playlist) loaded nothing — only
		// opening its album did. The song was absent from the list, so the old guard bailed.
		songList.set([]);
		const directlyOpened = makeSong({
			...queuedSongDefaults(),
			id: 's-direct',
			title: 'Direct',
			generations: [makeGen(genDefaults)]
		});
		vi.mocked(fetchSong).mockResolvedValueOnce(directlyOpened);

		await ensureGenerationsLoaded('s-direct');

		expect(get(songList).map((s) => s.id)).toContain('s-direct');
		selectedSongId.set('s-direct');
		expect(get(selectedSong)?.generations.length).toBe(1);
	});

	it('allows a later generation load to retry after an earlier request fails', async () => {
		const full = makeSong({ ...queuedSongDefaults(), id: 's-retry' });
		vi.mocked(fetchSong).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(full);

		await expect(ensureGenerationsLoaded('s-retry')).rejects.toThrow('offline');
		await ensureGenerationsLoaded('s-retry');

		expect(fetchSong).toHaveBeenCalledTimes(2);
		expect(get(songList)).toEqual([full]);
	});

	it('dedupes concurrent generation loads for the same song', async () => {
		songList.set([]);
		vi.mocked(fetchSong).mockResolvedValueOnce(
			makeSong({ ...queuedSongDefaults(), id: 's-direct' })
		);

		await Promise.all([ensureGenerationsLoaded('s-direct'), ensureGenerationsLoaded('s-direct')]);

		expect(fetchSong).toHaveBeenCalledTimes(1);
	});

	it('clearGenerationSelection clears gen id', () => {
		selectedGenerationId.set('g1');
		clearGenerationSelection();
		expect(get(selectedGenerationId)).toBeNull();
	});
});

describe('playback dispatch', () => {
	it('playing a take uses its version lyrics, never the song draft', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [makePoolTake({ lyrics: 'old verse', album_title: 'Nachtstrom' })] })
		);
		const gen = makeGen({ ...genDefaults, version_lyrics: 'old verse' });
		const song = makeSong({
			...queuedSongDefaults(),
			lyrics: 'latest draft',
			album_title: 'Nachtstrom'
		});
		await playTake(gen, song);
		expect(audioPlayer.current).toMatchObject({
			songId: 's1',
			songTitle: 'Song',
			artist: 'Artist',
			albumTitle: 'Nachtstrom',
			lyrics: 'old verse'
		});
	});

	it('navigateToPlaying selects the playing song', async () => {
		const song = makeSong(queuedSongDefaults());
		songList.set([song]);
		audioPlayer.current = makePlayback(makeGen(genDefaults), song);
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
		const hidden = makeSong({
			...queuedSongDefaults(),
			id: 's-hidden',
			album_id: 'a-hidden',
			title: 'Hidden'
		});
		vi.mocked(fetchSong).mockResolvedValueOnce(hidden);
		audioPlayer.current = makePlayback(makeGen({ ...genDefaults, song_id: 's-hidden' }), hidden);
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
		audioPlayer.current = makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		vi.mocked(fetchSong).mockRejectedValueOnce(new Error('offline'));
		selectedSongId.set('keep');
		await navigateToPlaying();
		expect(get(selectedSongId)).toBe('keep');
	});

	it('playback completion advances album playback to the next song', async () => {
		const firstGen = makeGen(genDefaults);
		const secondGen = makeGen({
			...genDefaults,
			id: 'g2',
			song_id: 's2',
			mp3_path: 'a1/song2.mp3'
		});
		const firstSong = makeSong({
			...queuedSongDefaults(),
			title: 'First',
			generations: [firstGen]
		});
		const secondSong = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Second',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		audioPlayer.current = makePlayback(firstGen, firstSong);

		audioPlayer.currentCallbacks.onEnded?.('normal');
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

	it('playback completion advances playlist playback to the next entry', async () => {
		const entries = [
			makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);

		audioPlayer.currentCallbacks.onEnded?.('normal');

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('records window-end without starting another track', () => {
		audioPlayer.currentCallbacks.onEnded?.('window-end');

		expect(get(windowEnded)).toBe(true);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('clears window-end when playback starts again', () => {
		windowEnded.set(true);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(get(windowEnded)).toBe(false);
	});

	it('records the first playing transition for each app take once', () => {
		const song = makeSong({ ...queuedSongDefaults(), id: 's-listen' });
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-listen-1', song_id: song.id }),
			song
		);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.status = 'paused';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-listen-2', song_id: song.id }),
			song
		);
		audioPlayer.status = 'playing';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledTimes(2);
		expect(recordSongListen).toHaveBeenNthCalledWith(1, song.id, null);
		expect(recordSongListen).toHaveBeenNthCalledWith(2, song.id, null);
	});

	it('records a stream take when playback crosses into it', () => {
		const firstSong = makeSong({ ...queuedSongDefaults(), id: 's-stream-listen-1' });
		const secondSong = makeSong({ ...queuedSongDefaults(), id: 's-stream-listen-2' });
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-stream-listen-1', song_id: firstSong.id }),
			firstSong
		);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-stream-listen-2', song_id: secondSong.id }),
			secondSong
		);
		audioPlayer.currentCallbacks.onCurrentChange?.(audioPlayer.current);

		expect(recordSongListen).toHaveBeenCalledTimes(2);
		expect(recordSongListen).toHaveBeenNthCalledWith(1, firstSong.id, null);
		expect(recordSongListen).toHaveBeenNthCalledWith(2, secondSong.id, null);
	});

	it('does not record a replacement take until it starts playing', () => {
		const firstSong = makeSong({ ...queuedSongDefaults(), id: 's-replacement-listen-1' });
		const secondSong = makeSong({ ...queuedSongDefaults(), id: 's-replacement-listen-2' });
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-replacement-listen-1', song_id: firstSong.id }),
			firstSong
		);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		vi.mocked(recordSongListen).mockClear();

		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-replacement-listen-2', song_id: secondSong.id }),
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
		expect(recordSongListen).toHaveBeenCalledWith(secondSong.id, null);
	});

	it('names the playlist when its queue plays the current entry', async () => {
		const entry = makePlaylistEntry({
			...playlistEntryDefaults,
			id: 'pe-listen',
			generation_id: 'g-playlist-listen',
			song_id: 's-playlist-listen'
		});
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: 1, entries: [entry] }),
			0
		);
		vi.mocked(recordSongListen).mockClear();
		audioPlayer.status = 'playing';

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledOnce();
		expect(recordSongListen).toHaveBeenCalledWith('s-playlist-listen', QUEUE_PLAYLIST.id);
	});

	it('records a take heard from its album and later from a playlist both times', async () => {
		const song = makeSong({ ...queuedSongDefaults(), id: 's-album-then-playlist' });
		const take = makeGen({
			...genDefaults,
			id: 'g-album-then-playlist',
			song_id: song.id,
			mp3_path: 'a1/album-then-playlist.mp3'
		});
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(take, song);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({
				...playlistDefaults,
				entry_count: 1,
				entries: [
					makePlaylistEntry({
						...playlistEntryDefaults,
						id: 'pe-album-then-playlist',
						generation_id: take.id,
						song_id: song.id,
						mp3_path: take.mp3_path
					})
				]
			}),
			0
		);
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledTimes(2);
		expect(recordSongListen).toHaveBeenNthCalledWith(1, song.id, null);
		expect(recordSongListen).toHaveBeenNthCalledWith(2, song.id, QUEUE_PLAYLIST.id);
	});

	it('does not name the playlist for a take played from outside its queue', async () => {
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({
				...playlistDefaults,
				entry_count: 1,
				entries: [makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe-outside' })]
			}),
			0
		);
		expect(get(queueContext).type).toBe('playlist');
		const song = makeSong({ ...queuedSongDefaults(), id: 's-outside-queue' });
		vi.mocked(recordSongListen).mockClear();
		audioPlayer.status = 'playing';
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-outside-queue', song_id: song.id }),
			song
		);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).toHaveBeenCalledOnce();
		expect(recordSongListen).toHaveBeenCalledWith(song.id, null);
	});

	it('logs a reporting failure without interrupting playback', async () => {
		const song = makeSong({ ...queuedSongDefaults(), id: 's-listen-error' });
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-listen-error', song_id: song.id }),
			song
		);
		const reportingError = new Error('offline');
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		vi.mocked(recordSongListen).mockRejectedValueOnce(reportingError);
		audioPlayer.status = 'playing';
		audioPlayer.currentCallbacks.onPlaybackStarted?.();
		await Promise.resolve();
		await Promise.resolve();

		expect(recordSongListen).toHaveBeenCalledWith(song.id, null);
		expect(logged).toHaveBeenCalledWith('Could not record song listen:', reportingError);
	});

	it('does not record while share playback owns the audio callback', () => {
		const song = makeSong({ ...queuedSongDefaults(), id: 's-share-listen' });
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
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-share-listen', song_id: song.id }),
			song
		);

		audioPlayer.currentCallbacks.onPlaybackStarted?.();

		expect(recordSongListen).not.toHaveBeenCalled();
		sharePlayback.stop();
	});

	it('clears library feedback when playback switches to a playlist', async () => {
		libraryQueueSkipped.set([{ song_id: 's1', generation_id: 'g1', reason: 'missing_file' }]);
		windowEnded.set(true);

		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entries: [makePlaylistEntry(playlistEntryDefaults)] }),
			0
		);

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
			makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			})
		];
		shuffleEnabled.set(true);
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);

		await playNextSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('restores the playlist order when shuffle is turned off', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const entries = [
			makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				position: 1,
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			}),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe3',
				position: 2,
				generation_id: 'g3',
				song_title: 'Third',
				mp3_path: 'c.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			2
		);
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
			makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			1
		);

		await playNextSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'First' })
		);
	});

	it('playPrevSong wraps playlist playback at the start', async () => {
		const entries = [
			makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First', mp3_path: 'a.mp3' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				generation_id: 'g2',
				song_title: 'Second',
				mp3_path: 'b.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);

		await playPrevSong();

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenLastCalledWith(
			expect.objectContaining({ songTitle: 'Second' })
		);
	});

	it('playNextSong wraps album playback to the first playable song', async () => {
		const firstGen = makeGen(genDefaults);
		const secondGen = makeGen({
			...genDefaults,
			id: 'g2',
			song_id: 's2',
			mp3_path: 'a1/song2.mp3'
		});
		const firstSong = makeSong({
			...queuedSongDefaults(),
			title: 'First',
			generations: [firstGen]
		});
		const secondSong = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Second',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		audioPlayer.current = makePlayback(secondGen, secondSong);

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
		const firstGen = makeGen(genDefaults);
		const secondGen = makeGen({
			...genDefaults,
			id: 'g2',
			song_id: 's2',
			mp3_path: 'a1/song2.mp3'
		});
		const firstSong = makeSong({
			...queuedSongDefaults(),
			title: 'First',
			generations: [firstGen]
		});
		const secondSong = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Second',
			track_number: 2,
			generations: [secondGen]
		});
		songList.set([firstSong, secondSong]);
		queueContext.set({ type: 'album', albumId: 'a1' });
		audioPlayer.current = makePlayback(firstGen, firstSong);

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
		const s1 = makeSong(queuedSongDefaults());
		const s2 = makeSong({ ...queuedSongDefaults(), id: 's2', album_id: 'a2' });
		const cur = {
			generation: makeGen(genDefaults),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayNextSong true for next song in same album', () => {
		const s1 = makeSong(queuedSongDefaults());
		const s2 = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			generations: [makeGen({ ...genDefaults, id: 'g2' })]
		});
		const cur = {
			generation: makeGen(genDefaults),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(true);
	});

	it('canPlayNextSong skips songs with zero generations', () => {
		const s1 = makeSong(queuedSongDefaults());
		const s2 = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			generation_count: 0,
			generations: []
		});
		const cur = {
			generation: makeGen(genDefaults),
			songId: 's1',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong skips songs with zero generations', () => {
		const s1 = makeSong({ ...queuedSongDefaults(), generation_count: 0, generations: [] });
		const s2 = makeSong({ ...queuedSongDefaults(), id: 's2' });
		const cur = {
			generation: makeGen(genDefaults),
			songId: 's2',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong false for a single playable album song', () => {
		const s1 = makeSong(queuedSongDefaults());
		const cur = {
			generation: makeGen(genDefaults),
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
			makePlaylistEntry(playlistEntryDefaults),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				position: 1,
				generation_id: 'g2',
				mp3_path: 'b.mp3'
			})
		];
		const cur = {
			generation: makeGen(genDefaults),
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
			makePlaylistEntry(playlistEntryDefaults),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe2', position: 1 })
		];
		const cur = {
			generation: makeGen(genDefaults),
			songId: '',
			songTitle: '',
			artist: '',
			albumTitle: '',
			lyrics: null
		};
		expect(canPlayPrevSong(cur, [], playlistQueue(entries, 1))).toBe(true);
	});

	it('playlist context: canPlayNextSong false for a single-entry playlist', () => {
		const entries = [makePlaylistEntry(playlistEntryDefaults)];
		const cur = {
			generation: makeGen(genDefaults),
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
			makePlaylistEntry(playlistEntryDefaults),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				position: 1,
				generation_id: 'g2',
				mp3_path: 'b.mp3'
			})
		];
		const cur = {
			generation: makeGen({ ...genDefaults, id: 'g2', mp3_path: 'b.mp3' }),
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
			makePlaylistEntry({ ...playlistEntryDefaults, mp3_path: 'a.mp3' }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				position: 1,
				generation_id: 'g2',
				mp3_path: 'b.mp3'
			})
		];
		const cur = {
			generation: makeGen({ ...genDefaults, id: 'g2', mp3_path: 'b.mp3' }),
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

describe('starting a playlist from a row', () => {
	it('sets playlist context and triggers load', async () => {
		const entries = [
			makePlaylistEntry({
				...playlistEntryDefaults,
				song_title: 'First',
				generation_id: 'g10',
				mp3_path: 'x.mp3'
			}),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				song_title: 'Second',
				generation_id: 'g11',
				mp3_path: 'y.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
		expect(audioPlayer.load).toHaveBeenCalledWith(expect.objectContaining({ songTitle: 'First' }), {
			restart: true
		});
	});

	it('uses entry lyrics, not a later song draft', async () => {
		const entries = [
			makePlaylistEntry({
				...playlistEntryDefaults,
				song_title: 'First',
				lyrics: 'old verse',
				album_title: 'Nachtstrom'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				lyrics: 'old verse',
				albumTitle: 'Nachtstrom',
				generation: expect.objectContaining({ version_lyrics: 'old verse' })
			}),
			{ restart: true }
		);
	});

	it('can start playback from a requested playlist entry', async () => {
		const entries = [
			makePlaylistEntry({
				...playlistEntryDefaults,
				song_title: 'First',
				generation_id: 'g10',
				mp3_path: 'x.mp3'
			}),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'pe2',
				song_title: 'Second',
				generation_id: 'g11',
				mp3_path: 'y.mp3'
			})
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			1
		);
		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({
				songTitle: 'Second',
				generation: expect.objectContaining({ id: 'g11', mp3_path: 'y.mp3' })
			}),
			{ restart: true }
		);
	});

	it('does nothing for empty entries', async () => {
		audioPlayer.current = null;
		queueContext.set({ type: 'library' });
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: 0 }),
			0
		);
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(queueContext)).toEqual({ type: 'library' });
	});
});

describe('a clicked playlist row', () => {
	const entries = [
		makePlaylistEntry({
			...playlistEntryDefaults,
			song_title: 'First',
			generation_id: 'g10',
			mp3_path: 'x.mp3'
		}),
		makePlaylistEntry({
			...playlistEntryDefaults,
			id: 'pe2',
			song_title: 'Second',
			generation_id: 'g11',
			mp3_path: 'y.mp3'
		})
	];

	it('plays from that entry and shows the take in Now Playing', async () => {
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			1
		);

		expect(get(queueContext)).toEqual(playlistQueue(entries, 1));
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('leaves the entry it is already playing playing, and does not start it over', async () => {
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			1
		);
		startPlayingWithoutAnAudioElement();
		closeNowPlaying();

		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			1
		);

		expect(audioPlayer.status).toBe('playing');
		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});

	describe('when the playlist holds one take twice', () => {
		const twice = [entries[0], makePlaylistEntry({ ...entries[0], id: 'pe-again', position: 1 })];
		const playlist = makeDetail({ ...playlistDefaults, entry_count: twice.length, entries: twice });

		function currentEntries(): boolean[] {
			return twice.map((entry) => isPlaylistEntryCurrent(entry, get(queueContext)));
		}

		it('plays the other entry from its own place, and only that entry is current', async () => {
			await playPlaylistEntryAndShowNowPlaying(playlist, 0);
			startPlayingWithoutAnAudioElement();

			await playPlaylistEntryAndShowNowPlaying(playlist, 1);

			expect(get(queueContext)).toEqual(playlistQueue(twice, 1));
			expect(currentEntries()).toEqual([false, true]);
		});

		it('marks neither entry once the same take plays outside the playlist', async () => {
			await playPlaylistEntryAndShowNowPlaying(playlist, 0);

			queueContext.set({ type: 'album', albumId: 'a1' });

			expect(currentEntries()).toEqual([false, false]);
		});
	});
});

describe('a playlist queue keeps its own identity', () => {
	const entries = () => [
		makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First' }),
		makePlaylistEntry({
			...playlistEntryDefaults,
			id: 'pe2',
			position: 1,
			generation_id: 'g2',
			song_title: 'Second',
			mp3_path: 'b.mp3'
		}),
		makePlaylistEntry({
			...playlistEntryDefaults,
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

	it('still names the playlist it plays after the listener opens an album', async () => {
		const queued = entries();
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: queued.length, entries: queued }),
			0
		);

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
		const queued = entries();
		vi.spyOn(Math, 'random').mockReturnValue(0);
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: queued.length, entries: queued }),
			0
		);

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

describe('starting a queue loads its first take on its own or reports an empty one', () => {
	beforeEach(() => {
		toasts.set([]);
	});

	it('loads the first take natively without concat', async () => {
		const entries = [makePlaylistEntry(playlistEntryDefaults)];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(audioPlayer.load).toHaveBeenCalledWith(
			expect.objectContaining({ songTitle: 'Playlist Song' }),
			{ restart: true }
		);
	});

	it('playing an album without a playable take reports it like an empty pool', async () => {
		albumList.set([makeAlbum({ created_at: '', title: 'Nachtstrom' })]);
		songList.set([makeSong({ ...queuedSongDefaults(), generation_count: 0, generations: [] })]);
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
		const song = makeSong({
			...queuedSongDefaults(),
			generations: [makeGen({ ...genDefaults, is_picked: true })]
		});
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
			makeSong({ ...queuedSongDefaults(), generations: [] }),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: []
			})
		]);
		let resolveSecond: ((song: SongItem) => void) | undefined;
		vi.mocked(fetchSong).mockImplementation((id: string) => {
			if (id === 's1') {
				return Promise.resolve(
					makeSong({
						...queuedSongDefaults(),
						generations: [makeGen({ ...genDefaults, id: 'g-first', is_picked: true })]
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
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g-second', song_id: 's2', is_picked: true })]
			})
		);
		await pending;
	});

	it('second playAlbum does not finish two full fetchSong walks', async () => {
		songList.set(
			[1, 2, 3].map((track) =>
				makeSong({
					...queuedSongDefaults(),
					id: `s${track}`,
					track_number: track,
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
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, is_picked: true })]
			})
		);
		await vi.waitFor(() => expect(audioPlayer.load).toHaveBeenCalledTimes(1));
		await vi.waitFor(() => expect(fetches).toContain('s2'));
		waiters.get('s2')?.(
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', is_picked: true })]
			})
		);
		await vi.waitFor(() => expect(fetches).toContain('s3'));
		waiters.get('s3')?.(
			makeSong({
				...queuedSongDefaults(),
				id: 's3',
				track_number: 3,
				generations: [makeGen({ ...genDefaults, id: 'g3', song_id: 's3', is_picked: true })]
			})
		);
		await Promise.all([first, second]);
		expect(fetches).toEqual(['s1', 's2', 's3']);
	});
});

describe('starting library playback from a take', () => {
	beforeEach(() => {
		toasts.set([]);
	});

	it('does not call createLibraryQueueStreamSnapshot and loads the start take natively', async () => {
		const gen = makeGen({ ...genDefaults, id: 'g2' });
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g2', song_id: 's2', song_title: 'Two' }),
					makePoolTake({ generation_id: 'g1', is_picked: false, is_kept: true })
				]
			})
		);

		await playTake(gen, makeSong(queuedSongDefaults()));

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

		await playTake(makeGen({ ...genDefaults, id: 'g-absent' }), makeSong(queuedSongDefaults()));

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

		await playTake(makeGen({ ...genDefaults, id: 'g-dead' }), makeSong(queuedSongDefaults()));

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

		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));

		expect(get(toasts)).toEqual([
			expect.objectContaining({
				message: '+ Keeps queue failed. Press play to retry.',
				type: 'error'
			})
		]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('retries the same generation rotation after a failed membership fetch', async () => {
		const gen = makeGen({ ...genDefaults, id: 'g2' });
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('timeout'));
		await playTake(gen, makeSong(queuedSongDefaults()));
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
		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		await expect(retryLastPlayIntent()).resolves.toBe(false);
	});

	it('preserves whether the library skip report is complete', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [makePoolTake(), makePoolTake({ generation_id: 'g2', song_id: 's2' })],
				skipped_complete: false
			})
		);
		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		expect(get(libraryQueueSkippedComplete)).toBe(false);
	});

	it('sends the current shuffle flag with the membership request', async () => {
		setShuffle(true);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));
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
		await playIdleStart();
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
		await playIdleStart();
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
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, id: 'g-pick', is_picked: true })]
			}),
			makeSong({
				...queuedSongDefaults(),
				id: 's-plain',
				title: 'Plain',
				generations: [makeGen({ ...genDefaults, id: 'g-plain' })]
			})
		]);
		await playTake(makeGen({ ...genDefaults, id: 'g-pick' }), makeSong(queuedSongDefaults()));
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
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g-second', song_title: 'Second' }),
					makePoolTake({ generation_id: 'g-after', song_id: 's2' })
				]
			})
		);

		const first = playTake(
			makeGen({ ...genDefaults, id: 'g-first' }),
			makeSong(queuedSongDefaults())
		);
		await playTake(makeGen({ ...genDefaults, id: 'g-second' }), makeSong(queuedSongDefaults()));
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
		const entries = [makePlaylistEntry(playlistEntryDefaults)];
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

describe('starting album playback from a take', () => {
	beforeEach(() => {
		toasts.set([]);
	});

	it('keeps the version on an album queue row, which is built from playlist-shaped entries', async () => {
		// The album queue round-trips its takes through PlaylistEntryItem, and
		// that conversion used to drop version_number — leaving rows reading
		// "take 2" where every other take surface says "v3 · take 2".
		const gen = makeGen({
			...genDefaults,
			id: 'g-v3',
			version_number: 3,
			generation_number: 2,
			is_picked: true
		});
		const song = makeSong({ ...queuedSongDefaults(), generations: [gen] });
		songList.set([song]);

		selectedAlbumId.set('a1');
		await playTake(gen, song);

		const vm = buildQueueViewModel(get(queueContext), audioPlayer.current);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 3, generationNumber: 2 }));
	});

	it('loads the clicked take natively without concat', async () => {
		const picked = makeGen({ ...genDefaults, id: 'g-pick', is_picked: true });
		const clicked = makeGen({
			...genDefaults,
			id: 'g-click',
			generation_number: 2,
			mp3_path: 'a1/click.mp3'
		});
		const song1 = makeSong({
			...queuedSongDefaults(),
			generations: [picked, clicked],
			generation_count: 2
		});
		const song2Pick = makeGen({
			...genDefaults,
			id: 'g2',
			is_picked: true,
			song_id: 's2',
			mp3_path: 'a1/s2.mp3'
		});
		const song2 = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [song2Pick]
		});
		songList.set([song1, song2]);

		selectedAlbumId.set('a1');
		await playTake(clicked, song1);

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

describe('the queue names its next take', () => {
	function albumSong(track: number): SongItem {
		const gen = makeGen({
			...genDefaults,
			id: `g${track}`,
			song_id: `s${track}`,
			is_picked: true,
			mp3_path: `a1/s${track}.mp3`
		});
		return makeSong({
			...queuedSongDefaults(),
			id: `s${track}`,
			title: `Song ${track}`,
			track_number: track,
			generations: [gen]
		});
	}

	function poolTake(n: number): LibraryPoolTakeItem {
		return makePoolTake({ generation_id: `g${n}`, song_id: `s${n}`, mp3_path: `a1/s${n}.mp3` });
	}

	function playlistOf(count: number): PlaylistDetailItem {
		const entries = Array.from({ length: count }, (_, i) =>
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: `pe${i + 1}`,
				position: i,
				generation_id: `g${i + 1}`,
				song_id: `s${i + 1}`,
				mp3_path: `a1/s${i + 1}.mp3`
			})
		);
		return makeDetail({ ...playlistDefaults, entry_count: entries.length, entries });
	}

	function nativeQueue(takeCount: number, index: number): QueueContext {
		const songs = Array.from({ length: takeCount }, (_, i) => albumSong(i + 1));
		const takes = songs.map((song) => makePlayback(song.generations[0], song));
		audioPlayer.current = takes[index];
		return { type: 'album', albumId: 'a1', takes, index };
	}

	function preloadedGenerationId(): string | null | undefined {
		const lastCall = vi.mocked(audioPlayer.preload).mock.lastCall;
		if (lastCall === undefined) return undefined;
		return lastCall[0]?.generation.id ?? null;
	}

	it.each([
		[
			'album',
			'g2',
			async () => {
				songList.set([albumSong(1), albumSong(2), albumSong(3)]);
				await playAlbum('a1');
			}
		],
		['playlist', 'g2', () => playPlaylistEntryAndShowNowPlaying(playlistOf(3), 0)],
		[
			'shuffled library',
			'g3',
			async () => {
				setShuffle(true);
				vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
					makePoolQueue({ takes: [poolTake(1), poolTake(3), poolTake(2)] })
				);
				await playTake(albumSong(1).generations[0], albumSong(1));
			}
		]
	])(
		'the next take is preloaded before the current one ends (%s)',
		async (_queue, nextGenerationId, start) => {
			await start();

			expect(audioPlayer.current?.generation.id).toBe('g1');
			expect(preloadedGenerationId()).toBe(nextGenerationId);
		}
	);

	it('playback end starts the preloaded take without a network wait', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [poolTake(1), poolTake(2), poolTake(3)] })
		);
		await playTake(albumSong(1).generations[0], albumSong(1));
		const preloaded = vi.mocked(audioPlayer.preload).mock.lastCall?.[0];
		vi.mocked(fetchLibraryPoolQueue).mockClear();

		audioPlayer.currentCallbacks.onEnded?.('normal');

		expect(audioPlayer.load).toHaveBeenLastCalledWith(preloaded);
		expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
	});

	it.each([
		['skip or pick advance', () => playNextSong()],
		['queue row jump', () => jumpToQueueIndex(1)]
	])('a pick or skip mid-queue re-aims the preload (%s)', async (_move, go) => {
		queueContext.set(nativeQueue(3, 0));

		await go();

		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(preloadedGenerationId()).toBe('g3');
	});

	it.each([
		['shuffle toggle', () => toggleShuffle()],
		['pool switch', () => chooseLibraryTakePool('picks')]
	])('a %s re-aims the preload', async (_change, rebuild) => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [poolTake(1), poolTake(2), poolTake(3)] })
		);
		await playTake(albumSong(1).generations[0], albumSong(1));
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [poolTake(1), poolTake(3), poolTake(2)] })
		);

		await rebuild();

		expect(preloadedGenerationId()).toBe('g3');
	});

	it('the last library take before window end preloads nothing', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({ takes: [poolTake(1), poolTake(2)], skipped_complete: false })
		);

		await playTake(albumSong(2).generations[0], albumSong(2));

		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(preloadedGenerationId()).toBeNull();
	});

	it('a queue of one take preloads nothing', async () => {
		await playPlaylistEntryAndShowNowPlaying(playlistOf(1), 0);

		expect(preloadedGenerationId()).toBeNull();
	});

	it('a take row whose pool holds only that take continues through its album', async () => {
		songList.set([albumSong(1), albumSong(2), albumSong(3)]);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue({ takes: [poolTake(2)] }));

		await playTake(albumSong(2).generations[0], albumSong(2));

		const ctx = get(queueContext);
		expect(ctx).toEqual(expect.objectContaining({ type: 'album', albumId: 'a1' }));
		expect(ctx.type === 'album' && ctx.takes?.map((take) => take.generation.id)).toEqual([
			'g1',
			'g2',
			'g3'
		]);
		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(preloadedGenerationId()).toBe('g3');
	});
});

describe('playAlbum start track', () => {
	beforeEach(() => {
		toasts.set([]);
	});

	it('starts on the first track that yields a playable take, skipping a fully archived one', async () => {
		// generation_count counts archived takes, so track 1 looks playable
		// from the list alone — the album must keep walking, not give up.
		const archivedOnly = makeSong({
			...queuedSongDefaults(),
			generation_count: 2,
			generations: [
				makeGen({ ...genDefaults, id: 'g1a', is_picked: true, is_archived: true }),
				makeGen({ ...genDefaults, id: 'g1b', is_archived: true })
			]
		});
		const playable = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [
				makeGen({ ...genDefaults, id: 'g2', song_id: 's2', is_picked: true, mp3_path: 'a1/s2.mp3' })
			]
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
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, is_archived: true })]
			}),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', is_archived: true })]
			})
		]);

		await playAlbum('a1');

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('empty');
	});

	it('leaves the running queue in place when the album has nothing playable', async () => {
		const running: QueueContext = { type: 'album', albumId: 'a2' };
		queueContext.set(running);
		songList.set([
			makeSong({
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, is_archived: true })]
			})
		]);

		await playAlbum('a1');

		expect(get(playStartNotice)).toBe('empty');
		expect(get(queueContext)).toEqual(running);
	});

	it('toasts and returns the notice to idle when a take load is rejected', async () => {
		songList.set([makeSong({ ...queuedSongDefaults(), generations: [] })]);
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

	it('offline, leaves a rejected take load to the strip instead of a toast', async () => {
		songList.set([makeSong({ ...queuedSongDefaults(), generations: [] })]);
		reportResourceStreamReachable(false);
		vi.mocked(fetchSong).mockRejectedValueOnce(
			new NetworkError('/api/songs/s1', new TypeError('Failed to fetch'))
		);

		await playAlbum('a1');

		expect(audioPlayer.load).not.toHaveBeenCalled();
		expect(get(playStartNotice)).toBe('idle');
		expect(get(toasts)).toEqual([]);
	});

	it('leaves a superseded start silent when its take load is rejected', async () => {
		songList.set([
			makeSong({ ...queuedSongDefaults(), generations: [] }),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				album_id: 'a2',
				title: 'Two',
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', is_picked: true })]
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
		toasts.set([]);
	});

	it('starts at the first song without a pick, not track 1', async () => {
		songList.set([
			makeSong({
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, is_picked: true })]
			}),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
			}),
			makeSong({
				...queuedSongDefaults(),
				id: 's3',
				title: 'Three',
				track_number: 3,
				generations: [makeGen({ ...genDefaults, id: 'g3', song_id: 's3', mp3_path: 'a1/s3.mp3' })]
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
				...queuedSongDefaults(),
				generations: [makeGen({ ...genDefaults, is_picked: true })]
			}),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [
					makeGen({
						...genDefaults,
						id: 'g2',
						song_id: 's2',
						is_picked: true,
						mp3_path: 'a1/s2.mp3'
					})
				]
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
			makeSong({ ...queuedSongDefaults(), generation_count: 0, generations: [] }),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
			})
		]);

		await curateAlbum('a1');

		const ctx = get(queueContext);
		expect(ctx.type === 'album' && ctx.takes?.length).toBe(1);
	});

	it('reports nothing playable for an album with no takes, and never enters curation mode', async () => {
		albumList.set([makeAlbum({ created_at: '', title: 'Nachtstrom' })]);
		songList.set([makeSong({ ...queuedSongDefaults(), generation_count: 0, generations: [] })]);

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
		songList.set([makeSong({ ...queuedSongDefaults(), generations: [makeGen(genDefaults)] })]);

		await curateAlbum('a1');

		expect(get(curationActive)).toBe(true);
		expect(get(nowPlayingSurface)).not.toBe('closed');
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('closing Now Playing exits curation mode', async () => {
		songList.set([makeSong({ ...queuedSongDefaults(), generations: [makeGen(genDefaults)] })]);
		await curateAlbum('a1');

		closeNowPlaying();

		expect(get(curationActive)).toBe(false);
	});

	it('playing a different album while curating ends curation mode', async () => {
		songList.set([
			makeSong({ ...queuedSongDefaults(), generations: [makeGen(genDefaults)] }),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				album_id: 'a2',
				title: 'Two',
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', mp3_path: 'a2/s2.mp3' })]
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
		const gen = makeGen(genDefaults);
		const song = makeSong({ ...queuedSongDefaults(), generations: [gen] });
		songList.set([song]);
		await curateAlbum('a1');
		expect(get(curationActive)).toBe(true);
		selectedAlbumId.set('a1');

		await playTake(gen, song);

		expect(get(curationActive)).toBe(false);
	});

	it('advancing within the curated queue keeps curation mode active', async () => {
		songList.set([
			makeSong({ ...queuedSongDefaults(), generations: [makeGen(genDefaults)] }),
			makeSong({
				...queuedSongDefaults(),
				id: 's2',
				title: 'Two',
				track_number: 2,
				generations: [makeGen({ ...genDefaults, id: 'g2', song_id: 's2', mp3_path: 'a1/s2.mp3' })]
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
		toasts.set([]);
	});

	it('toggling shuffle mid-library-play rebuilds at the current take and time', async () => {
		const gen = makeGen({ ...genDefaults, id: 'g-cur' });
		const song = makeSong({ ...queuedSongDefaults(), generations: [gen] });
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
			...queuedSongDefaults(),
			generations: [makeGen({ ...genDefaults, is_picked: true })]
		});
		const song2 = makeSong({
			...queuedSongDefaults(),
			id: 's2',
			title: 'Two',
			track_number: 2,
			generations: [
				makeGen({ ...genDefaults, id: 'g2', is_picked: true, song_id: 's2', mp3_path: 'a1/s2.mp3' })
			]
		});
		const song3 = makeSong({
			...queuedSongDefaults(),
			id: 's3',
			title: 'Three',
			track_number: 3,
			generations: [
				makeGen({ ...genDefaults, id: 'g3', is_picked: true, song_id: 's3', mp3_path: 'a1/s3.mp3' })
			]
		});
		songList.set([song1, song2, song3]);

		selectedAlbumId.set('a1');
		await playTake(song1.generations[0], song1);

		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		const ctx = get(queueContext);
		expect(ctx.type).toBe('album');
		if (ctx.type !== 'album' || !ctx.takes) throw new Error('expected album takes');
		expect(ctx.takes.map((take) => take.generation.id)).toEqual(['g1', 'g3', 'g2']);
	});

	it('playlist play without shuffle keeps entry order', async () => {
		const entries = [
			makePlaylistEntry(playlistEntryDefaults),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe3', generation_id: 'g3' })
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);
		expect(createQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(queueContext)).toEqual(playlistQueue(entries, 0));
	});

	it('starting a playlist at a chosen entry clears shuffle and keeps playlist order', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		setShuffle(true);
		const entries = [
			makePlaylistEntry(playlistEntryDefaults),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe2', generation_id: 'g2' }),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'pe3', generation_id: 'g3' })
		];
		await playPlaylistEntryAndShowNowPlaying(
			makeDetail({ ...playlistDefaults, entry_count: entries.length, entries }),
			0
		);
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
		toasts.set([]);
	});

	it('library start sends the stored pool with shuffle', async () => {
		setLibraryTakePool('mix');
		setShuffle(true);
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));
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

		await playIdleStart();

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

		await playIdleStart();

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
		const gen = makeGen({ ...genDefaults, id: 'g-cur' });
		const song = makeSong({ ...queuedSongDefaults(), generations: [gen] });
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
		audioPlayer.current = makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		queueContext.set({ type: 'album', albumId: 'a1' });

		await chooseLibraryTakePool('picks');

		expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
		expect(createLibraryQueueStreamSnapshot).not.toHaveBeenCalled();
		expect(get(libraryTakePool)).toBe('picks');
	});
});

describe('idlePlayTarget', () => {
	const albums = [makeAlbum({ created_at: '', title: 'Nachtstrom' })];
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

	const listedPlaylist = { ...playlist, entries: undefined };
	const loaded = { playlist, listedPlaylist, playlistLoading: false };

	it.each([
		[
			'none: falls back to the named library target',
			null,
			loaded,
			{ type: 'library', label: RAIL_LIBRARY_LABEL }
		],
		[
			'album: names the open album',
			{ kind: 'album' as const, id: 'a1' },
			loaded,
			{ type: 'album', label: 'Nachtstrom', albumId: 'a1' }
		],
		[
			'playlist: names the open playlist',
			{ kind: 'playlist' as const, id: 'p1' },
			loaded,
			{ type: 'playlist', label: 'Night Drive', playlistId: 'p1' }
		],
		[
			'playlist: names the opened playlist, not the one left, while it loads',
			{ kind: 'playlist' as const, id: 'p2' },
			{
				playlist,
				listedPlaylist: { ...listedPlaylist, id: 'p2', title: 'Late Drives' },
				playlistLoading: true
			},
			{ type: 'playlist', label: 'Late Drives', playlistId: 'p2' }
		],
		[
			'playlist: says it is loading when the opened playlist is not listed yet',
			{ kind: 'playlist' as const, id: 'p2' },
			{ playlist: null, listedPlaylist: null, playlistLoading: true },
			{ type: 'playlist', label: PLAYLIST_LOADING_LABEL, playlistId: 'p2' }
		],
		[
			// A playlist whose detail failed to load has nothing to natively
			// play — fall back to the named library target instead of a dead
			// Play button.
			'playlist: falls back to the library target when the detail failed to load',
			{ kind: 'playlist' as const, id: 'p1' },
			{ playlist: null, listedPlaylist, playlistLoading: false },
			{ type: 'library', label: RAIL_LIBRARY_LABEL }
		]
	])('%s', (_name, collection, playlistState, expected) => {
		const target = idlePlayTarget({ collection, albums, ...playlistState });
		expect(target).toEqual(expected);
	});
});

describe('playbackSource', () => {
	beforeEach(() => {
		albumList.set([makeAlbum({ created_at: '', title: 'Nightdrive' })]);
		openCollection.set({ kind: 'playlist', id: 'p9' });
	});

	it.each([
		[
			'an album queue names its album',
			{ type: 'album' as const, albumId: 'a1' },
			{ kind: 'album', id: 'a1', title: 'Nightdrive' }
		],
		[
			'a playlist queue names its playlist',
			{
				type: 'playlist' as const,
				playlist: { id: 'p1', title: 'Late Drives' },
				entries: [],
				index: 0
			},
			{ kind: 'playlist', id: 'p1', title: 'Late Drives' }
		],
		['a library queue names no source', { type: 'library' as const }, null],
		[
			'an album queue whose album is not loaded names no source',
			{ type: 'album' as const, albumId: 'a-missing' },
			null
		]
	])('%s, whatever collection is open', (_name, ctx, expected) => {
		queueContext.set(ctx);
		expect(get(playbackSource)).toEqual(expected);
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
		const song = makeSong({
			...queuedSongDefaults(),
			generations: [makeGen({ ...genDefaults, is_picked: true })]
		});
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
			entries: [makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'Listed' })]
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
			makeDetail({
				...playlistDefaults,
				entry_count: 3,
				entries: [
					makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'First' }),
					makePlaylistEntry({
						...playlistEntryDefaults,
						id: 'pe2',
						position: 1,
						generation_id: 'g2',
						song_title: 'Second',
						mp3_path: 'b.mp3'
					}),
					makePlaylistEntry({
						...playlistEntryDefaults,
						id: 'pe3',
						position: 2,
						generation_id: 'g3',
						song_title: 'Third',
						mp3_path: 'c.mp3'
					})
				]
			})
		);

		await playIdleStart();

		expect(get(shuffleEnabled)).toBe(true);
		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.entries.map((entry) => entry.id)).toEqual(['pe1', 'pe3', 'pe2']);
	});

	describe('while a newly opened playlist is still loading', () => {
		const left = makeDetail({
			...playlistDefaults,
			entries: [makePlaylistEntry({ ...playlistEntryDefaults, song_title: 'Previous list' })]
		});
		const opened = makeDetail({
			...playlistDefaults,
			id: 'p2',
			title: 'Late Drives',
			slug: 'late-drives',
			entries: [
				makePlaylistEntry({
					...playlistEntryDefaults,
					id: 'pe-b',
					song_title: 'Opened list'
				})
			]
		});
		let answerOpened: { resolve: (d: PlaylistDetailItem) => void; reject: (e: unknown) => void };

		beforeEach(async () => {
			resetPlaylists();
			vi.mocked(fetchPlaylist).mockResolvedValueOnce(left);
			await loadPlaylistDetail(left.id);
			vi.mocked(fetchPlaylist).mockReturnValueOnce(
				new Promise<PlaylistDetailItem>((resolve, reject) => {
					answerOpened = { resolve, reject };
				})
			);
			void loadPlaylistDetail(opened.id);
		});

		afterEach(() => {
			resetPlaylists();
		});

		it('waits for it and then plays it, never the library or the list just left', async () => {
			const started = playIdleStart();
			await Promise.resolve();

			expect(get(playStartNotice)).toBe('building');
			expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
			expect(get(queueContext).type).not.toBe('playlist');

			answerOpened.resolve(opened);
			await started;

			expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
			const ctx = get(queueContext);
			if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
			expect(ctx.playlist.id).toBe(opened.id);
			expect(audioPlayer.load).toHaveBeenCalledWith(
				expect.objectContaining({ songTitle: 'Opened list' }),
				{ restart: true }
			);
		});

		it('plays nothing when it fails to load', async () => {
			const started = playIdleStart();
			answerOpened.reject(new Error('offline'));
			await started;

			expect(fetchLibraryPoolQueue).not.toHaveBeenCalled();
			expect(get(queueContext).type).not.toBe('playlist');
			expect(get(playStartNotice)).toBe('idle');
		});

		it('plays nothing when the listener opens an album before it arrives', async () => {
			const started = playIdleStart();
			openCollection.set({ kind: 'album', id: 'a1' });
			answerOpened.resolve(opened);
			await started;

			expect(get(queueContext).type).not.toBe('playlist');
			expect(audioPlayer.load).not.toHaveBeenCalled();
			expect(get(playStartNotice)).toBe('idle');
		});

		it('never replaces a play the listener started after pressing Play', async () => {
			songList.set([
				makeSong({
					...queuedSongDefaults(),
					title: 'Album song',
					generations: [makeGen({ ...genDefaults, is_picked: true })]
				})
			]);
			const started = playIdleStart();
			openCollection.set({ kind: 'album', id: 'a1' });
			await playAlbum('a1');
			void loadPlaylistDetail(opened.id);
			answerOpened.resolve(opened);
			await started;

			expect(get(queueContext)).toMatchObject({ type: 'album', albumId: 'a1' });
			expect(audioPlayer.load).not.toHaveBeenCalledWith(
				expect.objectContaining({ songTitle: 'Opened list' }),
				expect.anything()
			);
		});

		it('keeps a newer failed start visible when it arrives', async () => {
			const started = playIdleStart();
			openCollection.set(null);
			vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('server error'));
			await playIdleStart();
			expect(get(playStartNotice)).toBe('error');

			answerOpened.resolve(opened);
			await started;

			expect(get(playStartNotice)).toBe('error');
		});
	});

	it('falls back to the library pool when the open playlist detail failed to load', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(null);
		await playIdleStart();
		expect(fetchLibraryPoolQueue).toHaveBeenCalled();
	});
});

describe('playAlbum', () => {
	it('starts on a drawn song, not on track 1, when asked for a random start', async () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		songList.set(
			['s1', 's2', 's3'].map((id, index) =>
				makeSong({
					...queuedSongDefaults(),
					id,
					title: id,
					track_number: index + 1,
					generations: [
						makeGen({
							...genDefaults,
							id: `g-${id}`,
							song_id: id,
							is_picked: true,
							mp3_path: `a1/${id}.mp3`
						})
					]
				})
			)
		);

		await playAlbum('a1', 'random');

		expect(audioPlayer.load).toHaveBeenNthCalledWith(1, expect.objectContaining({ songId: 's2' }), {
			restart: true
		});
		const ctx = get(queueContext);
		if (ctx.type !== 'album' || !ctx.takes) throw new Error('expected an album queue');
		expect(ctx.takes[ctx.index ?? 0].songId).toBe('s2');
	});
});

describe('buildQueueViewModel', () => {
	it('uses the native queue position when no playback is current', () => {
		const first = makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		const second = makePlayback(
			makeGen({ ...genDefaults, id: 'g2' }),
			makeSong({ ...queuedSongDefaults(), id: 's2' })
		);

		const vm = buildQueueViewModel({ type: 'library', takes: [first, second], index: 1 }, null);

		expect(vm.currentIndex).toBe(1);
		expect(vm.upNext?.generationId).toBe('g1');
	});

	it('classic-mode contexts without takes render current only, with no up next', () => {
		const vm = buildQueueViewModel(
			{ type: 'library' },
			makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()))
		);
		expect(vm.items).toEqual([]);
		expect(vm.currentIndex).toBe(-1);
		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a native library/album queue', () => {
		const songs = [makeSong(queuedSongDefaults()), makeSong({ ...queuedSongDefaults(), id: 's2' })];
		const current = makePlayback(
			makeGen({ ...genDefaults, version_number: 3, generation_number: 2, audio_duration_sec: 200 }),
			songs[0]
		);
		const next = makePlayback(makeGen({ ...genDefaults, id: 'g2' }), songs[1]);
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
		const song = makeSong({ ...queuedSongDefaults(), audio_duration: 0 });
		const ownDuration = makePlayback(makeGen({ ...genDefaults, audio_duration_sec: 141 }), song);
		const unmeasured = makePlayback(makeGen({ ...genDefaults, id: 'g2' }), song);
		const ctx = { type: 'library' as const, takes: [ownDuration, unmeasured], index: 0 };

		const vm = buildQueueViewModel(ctx, ownDuration);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('shows a native row\'s own measured length, not the "auto" (0) duration it was requested with', () => {
		const song = makeSong({ ...queuedSongDefaults(), audio_duration: 200 });
		const requestedAuto = makePlayback(
			makeGen({
				...genDefaults,
				generation_params: { audio_duration: 0 },
				audio_duration_sec: 188
			}),
			song
		);
		const ctx = { type: 'library' as const, takes: [requestedAuto], index: 0 };

		const vm = buildQueueViewModel(ctx, requestedAuto);

		expect(vm.items.map((item) => item.durationSec)).toEqual([188]);
	});

	it("reads a playlist row's own measured duration, showing none for an unmeasured entry", () => {
		const entries = [
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'e1', audio_duration: 141 }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e2',
				generation_id: 'g2',
				audio_duration: null
			})
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('carries no version number for a native take with no version (library pool)', () => {
		const song = makeSong(queuedSongDefaults());
		const current = makePlayback(
			makeGen({ ...genDefaults, version_number: null, generation_number: 5 }),
			song
		);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.items[0]).toEqual(
			expect.objectContaining({ versionNumber: null, generationNumber: 5 })
		);
	});

	it('has no up next for a single-item native queue', () => {
		const song = makeSong(queuedSongDefaults());
		const current = makePlayback(makeGen(genDefaults), song);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a playlist queue', () => {
		const entries = [
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e1',
				song_title: 'First',
				version_number: 4
			}),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e2',
				generation_id: 'g2',
				song_title: 'Second'
			})
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.currentIndex).toBe(0);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 4, generationNumber: 1 }));
		expect(vm.upNext).toEqual(expect.objectContaining({ generationId: 'g2' }));
	});
});

describe('stream transport direction', () => {
	it.each([
		['next', () => playNextSong(), 'next'],
		['previous', () => playPrevSong(), 'previous']
	])('moves to the %s stream track', async (_caseName, move, expectedSongId) => {
		audioPlayer.mode = 'stream';
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: 'g-current' }),
			makeSong({ ...queuedSongDefaults(), id: 's-current' })
		);
		vi.spyOn(audioPlayer, 'nextStreamTrack').mockImplementation(() => {
			audioPlayer.current = makePlayback(
				makeGen({ ...genDefaults, id: 'g-next' }),
				makeSong({ ...queuedSongDefaults(), id: 'next' })
			);
			return true;
		});
		vi.spyOn(audioPlayer, 'prevStreamTrack').mockImplementation(() => {
			audioPlayer.current = makePlayback(
				makeGen({ ...genDefaults, id: 'g-previous' }),
				makeSong({ ...queuedSongDefaults(), id: 'previous' })
			);
			return true;
		});

		await move();

		expect(audioPlayer.current?.songId).toBe(expectedSongId);
	});
});

describe('jumpToQueueIndex', () => {
	it('plays the take at the requested index in a native queue', () => {
		const songA = makeSong(queuedSongDefaults());
		const songB = makeSong({ ...queuedSongDefaults(), id: 's2' });
		const takes = [
			makePlayback(makeGen(genDefaults), songA),
			makePlayback(makeGen({ ...genDefaults, id: 'g2' }), songB)
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
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'e1' }),
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'e2', generation_id: 'g2' })
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
		queueContext.set(playlistQueue([makePlaylistEntry({ ...playlistEntryDefaults, id: 'e1' })], 0));

		jumpToQueueIndex(2);

		expect(seekToStreamTrack).toHaveBeenCalledWith(2);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});
});

describe('playTake', () => {
	it('a take row always starts a queue from that take', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(
			makePoolQueue({
				takes: [
					makePoolTake({ generation_id: 'g1' }),
					makePoolTake({ generation_id: 'g2', song_id: 's2', song_title: 'Two' })
				]
			})
		);

		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));

		expect(audioPlayer.current?.generation.id).toBe('g1');
		const ctx = get(queueContext);
		expect(ctx.type).toBe('library');
		expect(ctx.type === 'library' && ctx.takes?.map((take) => take.generation.id)).toEqual([
			'g1',
			'g2'
		]);
	});

	it('toggles pause instead of restarting when the row take is already playing', async () => {
		const gen = makeGen(genDefaults);
		const song = makeSong(queuedSongDefaults());
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.status = 'playing';
		const toggle = vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {});

		await playTake(gen, song);

		expect(toggle).toHaveBeenCalledOnce();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('reports a toast instead of throwing when the queue-stream path fails', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockRejectedValueOnce(new Error('offline'));

		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));

		expect(get(toasts)).toEqual([expect.objectContaining({ type: 'error' })]);
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it.each([
		{ failure: 'a non-Error value', thrown: 'offline', toast: 'Playback failed' },
		{
			failure: 'a browser error',
			thrown: new TypeError('Failed to fetch'),
			toast: 'Playback failed'
		},
		{
			failure: 'a refusal with a reason',
			thrown: new ApiError(409, 'Take is still rendering', '/api/generations/g1'),
			toast: 'Take is still rendering'
		}
	])('names $failure as $toast, never browser text', async ({ thrown, toast }) => {
		vi.mocked(audioPlayer.load).mockImplementationOnce(() => {
			throw thrown;
		});

		await playTake(makeGen(genDefaults), makeSong(queuedSongDefaults()));

		expect(get(toasts)).toEqual([expect.objectContaining({ type: 'error', message: toast })]);
	});
});

describe('playTakeAndShowNowPlaying', () => {
	it('plays the take and opens Now Playing on the judging panel', async () => {
		vi.mocked(fetchLibraryPoolQueue).mockResolvedValueOnce(makePoolQueue());
		const gen = makeGen(genDefaults);
		const song = makeSong(queuedSongDefaults());

		await playTakeAndShowNowPlaying(gen, song);

		expect(audioPlayer.current?.generation.id).toBe(gen.id);
		expect(get(nowPlayingPanel)).toBe('take');
		expect(get(nowPlayingOpen)).toBe(true);
	});

	it('leaves the take it is already playing playing, and does not start it over', async () => {
		const gen = makeGen(genDefaults);
		const song = makeSong(queuedSongDefaults());
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

	it.each([
		{
			way: 'opened where no docked panel fits',
			reach: () => openNowPlaying('queue'),
			chosen: true
		},
		{
			way: 'expanded from the docked panel',
			reach: () => {
				nowPlayingDockable.set(true);
				openNowPlaying('queue');
				expandNowPlaying();
			},
			chosen: true
		},
		{
			way: 'opened straight onto the remembered full surface',
			reach: () => {
				nowPlayingDockable.set(true);
				openNowPlaying('queue');
				expandNowPlaying();
				closeNowPlaying();
				openNowPlaying('queue');
			},
			chosen: true
		},
		{
			way: 'kept full while the window grows room for the panel',
			reach: () => {
				openNowPlaying('queue');
				nowPlayingDockable.set(true);
			},
			chosen: true
		},
		{
			way: 'forced full by a window losing room for the docked panel',
			reach: () => {
				nowPlayingDockable.set(true);
				openNowPlaying('queue');
				nowPlayingDockable.set(false);
			},
			chosen: false
		},
		{
			way: 'docked again',
			reach: () => {
				nowPlayingDockable.set(true);
				openNowPlaying('queue');
				expandNowPlaying();
				dockNowPlaying();
			},
			chosen: false
		},
		{
			way: 'closed',
			reach: () => {
				openNowPlaying('queue');
				closeNowPlaying();
			},
			chosen: false
		}
	])(
		'counts the full surface as the listener’s own step when $way: $chosen',
		({ reach, chosen }) => {
			reach();

			expect(get(nowPlayingFullChosen)).toBe(chosen);
		}
	);

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

describe('audioPlayer offline announcement wiring', () => {
	it.each([
		{ connection: 'offline', reachable: false, announced: true },
		{ connection: 'online', reachable: true, announced: false }
	])('leaves a lost network to the strip only while $connection', ({ reachable, announced }) => {
		reportResourceStreamReachable(reachable);

		expect(audioPlayer.currentCallbacks.networkFailureIsAnnounced()).toBe(announced);
	});

	it('lets playback the lost network stopped go on once the connection is back', () => {
		const resume = vi.spyOn(audioPlayer, 'resumeAfterNetworkReturn').mockImplementation(() => {});
		reportResourceStreamReachable(false);
		expect(audioPlayer.currentCallbacks.networkFailureIsAnnounced()).toBe(true);
		expect(resume).not.toHaveBeenCalled();

		reportResourceStreamReachable(true);
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);

		expect(resume).toHaveBeenCalledOnce();
	});
});

describe('remembering what the app plays', () => {
	const LISTENER = { id: 'u-resume', username: 'listener', role: 'user' as const };
	const song = makeSong({ ...queuedSongDefaults(), id: 's-resume' });

	function storedRecord(): unknown {
		return JSON.parse(localStorage.getItem(`playbackResume:${LISTENER.id}`) ?? 'null');
	}

	function playAndHide(generationId: string): void {
		audioPlayer.current = makePlayback(
			makeGen({ ...genDefaults, id: generationId, song_id: song.id }),
			song
		);
		audioPlayer.status = 'playing';
		flushSync();
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
		document.dispatchEvent(new Event('visibilitychange'));
	}

	beforeEach(() => {
		currentUser.set(LISTENER);
	});

	afterEach(() => {
		currentUser.set(null);
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		localStorage.clear();
	});

	it.each<{ kind: string; queue: QueueContext; source: ResumeQueueSource }>([
		{
			kind: 'album',
			queue: { type: 'album', albumId: 'a-resume' },
			source: { type: 'album', albumId: 'a-resume' }
		},
		{
			kind: 'playlist',
			queue: playlistQueue([], 0),
			source: { type: 'playlist', playlistId: QUEUE_PLAYLIST.id }
		},
		{
			kind: 'library',
			queue: { type: 'library' },
			source: { type: 'library', pool: 'all', shuffle: true }
		}
	])('saves the $kind queue the take plays from', ({ queue, source }) => {
		setShuffle(true);
		setLibraryTakePool('all');
		queueContext.set(queue);

		playAndHide('g-resume-queue');

		expect(storedRecord()).toMatchObject({ source, generationId: 'g-resume-queue' });
	});

	it('share playback is never saved', () => {
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

		playAndHide('g-resume-share');
		sharePlayback.stop();

		expect(storedRecord()).toBeNull();
	});
});
