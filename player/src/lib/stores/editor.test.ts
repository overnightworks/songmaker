import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

import { editGenParams, isDirty, editLyrics, loadSongData } from './editor';
import type { SongItem } from '$lib/api/types';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Test',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		language: 'en',
		lyrics: 'hello',
		prompt: 'rock',
		bpm: 120,
		duration: 180,
		key: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: null,
		...overrides
	};
}

describe('editGenParams dirty tracking', () => {
	it('is not dirty after loading a song', () => {
		loadSongData(makeSong());
		expect(get(isDirty)).toBe(false);
	});

	it('is dirty when gen params change', () => {
		loadSongData(makeSong());
		editGenParams.set({ inference_steps: 50 });
		expect(get(isDirty)).toBe(true);
	});

	it('is not dirty when gen params are set back to null', () => {
		loadSongData(makeSong());
		editGenParams.set({ inference_steps: 50 });
		editGenParams.set(null);
		expect(get(isDirty)).toBe(false);
	});

	it('loads generation_params from song', () => {
		const params = { shift: 5.0, inference_steps: 25 };
		loadSongData(makeSong({ generation_params: params }));
		expect(get(editGenParams)).toEqual(params);
		expect(get(isDirty)).toBe(false);
	});

	it('order-independent comparison', () => {
		const params = { shift: 5.0, inference_steps: 25 };
		loadSongData(makeSong({ generation_params: params }));
		editGenParams.set({ inference_steps: 25, shift: 5.0 });
		expect(get(isDirty)).toBe(false);
	});

	it('detects dirty when only lyrics change with gen params present', () => {
		loadSongData(makeSong({ generation_params: { shift: 2.0 } }));
		editLyrics.set('changed');
		expect(get(isDirty)).toBe(true);
	});
});
