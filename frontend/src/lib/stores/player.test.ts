import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem, PlaylistEntryItem, SongItem } from '$lib/api/types';
import {
	canPlayNextGen,
	canPlayNextSong,
	canPlayPrevGen,
	canPlayPrevSong,
	clearGenerationSelection,
	filteredSongs,
	navigateToPlaying,
	playGeneration,
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
	songList,
	updateGenerationScores
} from './player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';

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

	it('canPlayPrevSong false at start of album', () => {
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
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(false);
	});

	it('playlist context: canPlayPrevSong true when not at start', () => {
		const entries = [
			makePlaylistEntry({ id: 'pe1', position: 0 }),
			makePlaylistEntry({ id: 'pe2', position: 1 })
		];
		const cur = { generation: makeGen(), songId: '', songTitle: '', artist: '' };
		expect(canPlayPrevSong(cur, [], { type: 'playlist', entries, index: 1 })).toBe(true);
	});

	it('playlist context: canPlayNextSong false at last entry', () => {
		const entries = [makePlaylistEntry({ id: 'pe1', position: 0 })];
		const cur = { generation: makeGen(), songId: '', songTitle: '', artist: '' };
		expect(canPlayNextSong(cur, [], { type: 'playlist', entries, index: 0 })).toBe(false);
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
