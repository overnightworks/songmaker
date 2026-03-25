import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem, SongItem } from '$lib/api/types';
import {
	clearGenerationSelection,
	expandedSongIds,
	filteredSongs,
	isAudioPlaying,
	navigateToPlaying,
	playGeneration,
	playback,
	playbackDuration,
	playbackTime,
	playingGeneration,
	requestTogglePlay,
	selectAlbum,
	selectGenerationInSidebar,
	selectSong,
	selectedAlbumId,
	selectedGeneration,
	selectedGenerationId,
	selectedSong,
	selectedSongId,
	songList,
	togglePlayPause,
	toggleSongExpanded,
	updateGenerationScores
} from './player';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Song',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		duration: 180,
		key: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [makeGen()],
		created_at: null,
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
		seed: 42,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		whisper_text: null,
		scores: null,
		generation_params: null,
		created_at: null,
		...overrides
	};
}

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

	it('toggleSongExpanded adds and removes', () => {
		expandedSongIds.set(new Set());
		toggleSongExpanded('s1');
		expect(get(expandedSongIds).has('s1')).toBe(true);
		toggleSongExpanded('s1');
		expect(get(expandedSongIds).has('s1')).toBe(false);
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

describe('playback', () => {
	it('playGeneration sets playback state', () => {
		playGeneration(makeGen(), makeSong());
		const pb = get(playback);
		expect(pb?.generation.id).toBe('g1');
		expect(pb?.songTitle).toBe('Song');
		expect(pb?.autoplay).toBe(true);
	});

	it('playingGeneration derives from playback', () => {
		playGeneration(makeGen(), makeSong());
		expect(get(playingGeneration)?.id).toBe('g1');
	});

	it('playingGeneration null when no playback', () => {
		playback.set(null);
		expect(get(playingGeneration)).toBeNull();
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
		playback.set(null);
		selectedSongId.set('keep');
		navigateToPlaying();
		expect(get(selectedSongId)).toBe('keep');
	});

	it('togglePlayPause increments counter', () => {
		const before = get(requestTogglePlay);
		togglePlayPause();
		expect(get(requestTogglePlay)).toBe(before + 1);
	});

	it('playbackTime and playbackDuration default to 0', () => {
		expect(get(playbackTime)).toBe(0);
		expect(get(playbackDuration)).toBe(0);
	});

	it('isAudioPlaying defaults to false', () => {
		expect(get(isAudioPlaying)).toBe(false);
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
