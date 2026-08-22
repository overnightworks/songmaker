import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem, SongItem } from '$lib/api/types';

vi.mock('$lib/api/client', () => ({
	fetchSong: vi.fn(),
	pickGeneration: vi.fn(),
	unpickGeneration: vi.fn(),
	keepGeneration: vi.fn(),
	unkeepGeneration: vi.fn(),
	rateGeneration: vi.fn()
}));

import {
	fetchSong,
	keepGeneration,
	pickGeneration,
	rateGeneration,
	unkeepGeneration,
	unpickGeneration
} from '$lib/api/client';
import { pinnedSeed } from '$lib/stores/editor';
import { songList } from '$lib/stores/player';
import { toasts } from '$lib/stores/toast';
import { pinSeed, rate, setKeep, setPick } from './takeActions';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'a.mp3',
		wav_path: null,
		seed: 42,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: 'la la',
		scores: null,
		generation_params: null,
		created_at: '',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'la la',
		prompt: 'dreamy',
		version_count: 1,
		generation_count: 1,
		is_shared: false,
		created_at: '',
		generations: [generation()],
		...overrides
	};
}

beforeEach(() => {
	songList.set([]);
	toasts.set([]);
	pinnedSeed.set(null);
	vi.clearAllMocks();
});

afterEach(() => {
	songList.set([]);
	pinnedSeed.set(null);
});

describe('setPick', () => {
	it('picks a generation and refreshes the song into songList', async () => {
		vi.mocked(fetchSong).mockResolvedValue(
			song({ generations: [generation({ is_picked: true })] })
		);

		await setPick('s1', 'g1', true);

		expect(pickGeneration).toHaveBeenCalledWith('g1');
		expect(unpickGeneration).not.toHaveBeenCalled();
		expect(get(songList)[0]?.generations[0]?.is_picked).toBe(true);
	});

	it('unpicks a generation', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song());

		await setPick('s1', 'g1', false);

		expect(unpickGeneration).toHaveBeenCalledWith('g1');
		expect(pickGeneration).not.toHaveBeenCalled();
	});

	it('toasts and leaves songList unchanged when the API call fails', async () => {
		vi.mocked(pickGeneration).mockRejectedValue(new Error('boom'));
		songList.set([song()]);

		await setPick('s1', 'g1', true);

		expect(fetchSong).not.toHaveBeenCalled();
		expect(get(songList)).toEqual([song()]);
		expect(get(toasts)).toEqual([expect.objectContaining({ message: 'boom', type: 'error' })]);
	});
});

describe('setKeep', () => {
	it('keeps a generation and refreshes the song into songList', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song({ generations: [generation({ is_kept: true })] }));

		await setKeep('s1', 'g1', true);

		expect(keepGeneration).toHaveBeenCalledWith('g1');
		expect(get(songList)[0]?.generations[0]?.is_kept).toBe(true);
	});

	it('unkeeps a generation', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song());

		await setKeep('s1', 'g1', false);

		expect(unkeepGeneration).toHaveBeenCalledWith('g1');
	});

	it('toasts on failure', async () => {
		vi.mocked(keepGeneration).mockRejectedValue(new Error('nope'));

		await setKeep('s1', 'g1', true);

		expect(get(toasts)).toEqual([expect.objectContaining({ message: 'nope', type: 'error' })]);
	});
});

describe('rate', () => {
	it('rates a generation, refreshes songList, and confirms via toast', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song());

		await rate('s1', 'g1', 80, 'great take');

		expect(rateGeneration).toHaveBeenCalledWith('g1', 80, 'great take');
		expect(get(songList)).toEqual([song()]);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Rating saved', type: 'success' })
		]);
	});

	it('defaults notes to an empty string', async () => {
		vi.mocked(fetchSong).mockResolvedValue(song());

		await rate('s1', 'g1', 50);

		expect(rateGeneration).toHaveBeenCalledWith('g1', 50, '');
	});

	it('toasts on failure and leaves songList unchanged', async () => {
		vi.mocked(rateGeneration).mockRejectedValue(new Error('rating failed'));
		songList.set([song()]);

		await rate('s1', 'g1', 80);

		expect(fetchSong).not.toHaveBeenCalled();
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'rating failed', type: 'error' })
		]);
	});
});

describe('pinSeed', () => {
	it('pins the seed for the next generation and confirms via toast', () => {
		pinSeed(48113);

		expect(get(pinnedSeed)).toBe(48113);
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Seed 48113 pinned for next generation', type: 'success' })
		]);
	});
});
