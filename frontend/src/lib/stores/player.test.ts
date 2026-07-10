import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import type {
	GenerationItem,
	PlaylistEntryItem,
	QueueStreamManifest,
	QueueStreamTrackItem,
	SongItem
} from '$lib/api/types';
import { createQueueStreamSnapshot } from '$lib/api/client';
import { toasts } from '$lib/stores/toast';
import type { StreamFallbackState } from '$lib/services/audioPlayer.svelte';

vi.mock('$lib/api/client', () => ({
	createQueueStreamSnapshot: vi.fn(),
	createLibraryQueueStreamSnapshot: vi.fn(),
	fetchSong: vi.fn()
}));
import {
	canPlayNextGen,
	canPlayNextSong,
	canPlayPrevGen,
	canPlayPrevSong,
	clearGenerationSelection,
	filteredSongs,
	handlePlaybackEnded,
	navigateToPlaying,
	playGeneration,
	playLibraryFromGeneration,
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
	shuffleEnabled,
	songList,
	toggleShuffle,
	updateGenerationScores
} from './player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { createLibraryQueueStreamSnapshot } from '$lib/api/client';

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
		song_title: 'Playlist Song',
		album_title: 'Album',
		artist: 'Artist',
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		seed: 42,
		model_mode: 'sft',
		...overrides
	};
}

beforeEach(() => {
	// These tests pin the classic per-track queue path; stream is now the
	// product default, so classic must be an explicit choice here.
	setQueuePlaybackMode('classic');
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
	shuffleEnabled.set(false);
	toasts.set([]);
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
			artist: 'Artist'
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
				artist: 'Artist'
			},
			{ restart: true }
		);
	});

	it('navigateToPlaying selects the playing song', () => {
		const song = makeSong();
		songList.set([song]);
		playGeneration(makeGen(), song);
		selectedAlbumId.set(null);
		selectedSongId.set(null);

		navigateToPlaying();

		expect(get(selectedAlbumId)).toBe('a1');
		expect(get(selectedSongId)).toBe('s1');
	});

	it('navigateToPlaying does nothing with no playback', () => {
		audioPlayer.current = null;
		selectedSongId.set('keep');
		navigateToPlaying();
		expect(get(selectedSongId)).toBe('keep');
	});

	it('navigateToPlaying does nothing if playing song is not in list', () => {
		songList.set([]);
		playGeneration(makeGen(), makeSong());
		selectedSongId.set('keep');
		navigateToPlaying();
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
			artist: 'Artist'
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

	it('toggleShuffle flips shuffle mode', () => {
		expect(get(shuffleEnabled)).toBe(false);
		toggleShuffle();
		expect(get(shuffleEnabled)).toBe(true);
		toggleShuffle();
		expect(get(shuffleEnabled)).toBe(false);
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
			artist: 'Artist'
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
			artist: 'Artist'
		});
	});
});

describe('canPlay predicates', () => {
	it('canPlayPrevGen false when no current', () => {
		expect(canPlayPrevGen(null, [])).toBe(false);
	});

	it('canPlayPrevGen false when song not found', () => {
		const cur = { generation: makeGen(), songId: 'unknown', songTitle: '', artist: '' };
		expect(canPlayPrevGen(cur, [makeSong()])).toBe(false);
	});

	it('canPlayPrevGen true when not at first generation', () => {
		const g1 = makeGen({ id: 'g1' });
		const g2 = makeGen({ id: 'g2' });
		const song = makeSong({ generations: [g1, g2] });
		const cur = { generation: g2, songId: 's1', songTitle: '', artist: '' };
		expect(canPlayPrevGen(cur, [song])).toBe(true);
	});

	it('canPlayNextGen false at last generation', () => {
		const g1 = makeGen();
		const song = makeSong({ generations: [g1] });
		const cur = { generation: g1, songId: 's1', songTitle: '', artist: '' };
		expect(canPlayNextGen(cur, [song])).toBe(false);
	});

	it('canPlayNextGen false when generation not found in song', () => {
		const song = makeSong({ generations: [makeGen({ id: 'other' })] });
		const cur = { generation: makeGen({ id: 'gone' }), songId: 's1', songTitle: '', artist: '' };
		expect(canPlayNextGen(cur, [song])).toBe(false);
	});

	it('canPlayPrevSong false when no current', () => {
		expect(canPlayPrevSong(null, [], { type: 'library' })).toBe(false);
	});

	it('canPlayNextSong scoped to album in album context', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a2' });
		const cur = { generation: makeGen({ id: 'g1' }), songId: 's1', songTitle: '', artist: '' };
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayNextSong true for next song in same album', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a1', generations: [makeGen({ id: 'g2' })] });
		const cur = { generation: makeGen({ id: 'g1' }), songId: 's1', songTitle: '', artist: '' };
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(true);
	});

	it('canPlayNextSong skips songs with zero generations', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const s2 = makeSong({ id: 's2', album_id: 'a1', generation_count: 0, generations: [] });
		const cur = { generation: makeGen(), songId: 's1', songTitle: '', artist: '' };
		expect(canPlayNextSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong skips songs with zero generations', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1', generation_count: 0, generations: [] });
		const s2 = makeSong({ id: 's2', album_id: 'a1' });
		const cur = { generation: makeGen({ id: 'g1' }), songId: 's2', songTitle: '', artist: '' };
		expect(canPlayPrevSong(cur, [s1, s2], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('canPlayPrevSong false for a single playable album song', () => {
		const s1 = makeSong({ id: 's1', album_id: 'a1' });
		const cur = { generation: makeGen({ id: 'g1' }), songId: 's1', songTitle: '', artist: '' };
		expect(canPlayPrevSong(cur, [s1], { type: 'album', albumId: 'a1' })).toBe(false);
	});

	it('playlist context: canPlayNextSong based on index', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1, generation_id: 'g2', mp3_path: 'b.mp3' })
		];
		const cur = { generation: makeGen(), songId: '', songTitle: '', artist: '' };
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(true);
	});

	it('playlist context: canPlayPrevSong true when not at start', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1 })
		];
		const cur = { generation: makeGen(), songId: '', songTitle: '', artist: '' };
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 1 })).toBe(true);
	});

	it('playlist context: canPlayNextSong false for a single-entry playlist', () => {
		const entries = [makePlaylistEntry({ id: 'pe1', position: 0 })];
		const cur = { generation: makeGen(), songId: '', songTitle: '', artist: '' };
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
			artist: ''
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
			artist: ''
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
		const song = makeSong();
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

	it('falls back to index 0 when requested generation is absent from manifest', async () => {
		const gen = makeGen({ id: 'g-absent' });
		const song = makeSong();
		const manifest = makeManifest({ tracks: [makeTrack({ generation_id: 'g1' })] });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(manifest);

		await playLibraryFromGeneration(gen);

		expect(loadStreamSpy).toHaveBeenCalledWith(manifest, 0, { restart: true });
	});

	it('shows error toast and does not call loadStream when library stream build fails', async () => {
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(new Error('server error'));

		await playLibraryFromGeneration(makeGen());

		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Stream unavailable. Tap play to retry.', type: 'error' })
		]);
		expect(loadStreamSpy).not.toHaveBeenCalled();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('retries the same generation rotation after a failed build, not an unrotated default', async () => {
		const gen = makeGen({ id: 'g2' });
		vi.mocked(createLibraryQueueStreamSnapshot).mockRejectedValueOnce(new Error('cold build timeout'));
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

		expect(vi.mocked(createLibraryQueueStreamSnapshot)).toHaveBeenLastCalledWith('g2');
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
});

describe('rebuildQueueStream routing', () => {
	beforeEach(() => {
		setQueuePlaybackMode('stream');
		vi.spyOn(audioPlayer, 'loadStream').mockImplementation(() => {});
		toasts.set([]);
	});

	it('routes library context rebuild to the library endpoint', async () => {
		queueContext.set({ type: 'library' });
		const freshManifest = makeManifest({ snapshot_id: 'fresh' });
		vi.mocked(createLibraryQueueStreamSnapshot).mockResolvedValueOnce(freshManifest);

		const state: StreamFallbackState = {
			manifest: makeManifest({ tracks: [makeTrack({ generation_id: 'g-cur' })] }),
			trackIndex: 0,
			trackTime: 30
		};
		const result = await audioPlayer.onStreamRebuild!(state);

		expect(createLibraryQueueStreamSnapshot).toHaveBeenCalledWith('g-cur');
		expect(result).toBe(freshManifest);
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
		const result = await audioPlayer.onStreamRebuild!(state);

		expect(createQueueStreamSnapshot).toHaveBeenCalledWith([
			{ generation_id: 'g1', entry_id: 'pe1' }
		]);
		expect(result).toBe(freshManifest);
	});
});
