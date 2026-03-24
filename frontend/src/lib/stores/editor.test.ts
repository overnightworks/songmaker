import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

vi.mock('$lib/stores/player', () => {
	const { writable } = require('svelte/store');
	return { songList: writable([]) };
});

import {
	editGenParams,
	editLyrics,
	editPrompt,
	editBpm,
	editDuration,
	editKey,
	isDirty,
	saving,
	versions,
	currentVersionIndex,
	activeDiff,
	status,
	loadSongData,
	loadVersion,
	handleSave,
	handleDeleteVersion,
	handleDiffChange,
	handleApply,
	dismissAppliedDiff
} from './editor';
import type { SongItem, VersionItem } from '$lib/api/types';

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

function makeVersion(overrides: Partial<VersionItem> = {}): VersionItem {
	return {
		id: 'v1',
		version_number: 1,
		lyrics: 'verse one',
		prompt: 'rock style',
		bpm: 120,
		duration: 180,
		key: 'Am',
		generation_params: null,
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

describe('loadSongData', () => {
	it('sets all edit fields', () => {
		loadSongData(makeSong({ lyrics: 'L', prompt: 'P', bpm: 99, duration: 200, key: 'C' }));
		expect(get(editLyrics)).toBe('L');
		expect(get(editPrompt)).toBe('P');
		expect(get(editBpm)).toBe(99);
		expect(get(editDuration)).toBe(200);
		expect(get(editKey)).toBe('C');
	});
});

describe('loadVersion', () => {
	it('loads version data into edit fields', () => {
		versions.set([
			makeVersion({ lyrics: 'v1 lyrics', prompt: 'v1 prompt', bpm: 100 }),
			makeVersion({ id: 'v2', version_number: 2, lyrics: 'v2 lyrics' })
		]);
		loadVersion(1);
		expect(get(editLyrics)).toBe('v2 lyrics');
		expect(get(currentVersionIndex)).toBe(1);
		expect(get(isDirty)).toBe(false);
	});

	it('does nothing for out-of-bounds index', () => {
		versions.set([makeVersion()]);
		loadSongData(makeSong());
		loadVersion(99);
		expect(get(editLyrics)).toBe('hello');
	});
});

describe('handleSave', () => {
	it('calls updateSong and resets dirty state', async () => {
		const { updateSong } = await import('$lib/api/client');
		const mockUpdate = vi.mocked(updateSong);
		mockUpdate.mockResolvedValueOnce(makeSong({ version_count: 2 }));

		loadSongData(makeSong());
		editLyrics.set('new lyrics');
		expect(get(isDirty)).toBe(true);

		await handleSave('s1');

		expect(mockUpdate).toHaveBeenCalled();
		expect(get(isDirty)).toBe(false);
		expect(get(saving)).toBe(false);
	});

	it('shows error on failure', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockRejectedValueOnce(new Error('Network error'));

		loadSongData(makeSong());
		await handleSave('s1');

		expect(get(status)).toBe('Network error');
		expect(get(saving)).toBe(false);
	});
});

describe('handleDeleteVersion', () => {
	it('calls deleteVersion and refreshes', async () => {
		const { deleteVersion, fetchSong } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(makeSong());

		await handleDeleteVersion('s1', 'v1', false);

		expect(deleteVersion).toHaveBeenCalledWith('v1', false);
	});

	it('shows error on failure', async () => {
		const { deleteVersion } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockRejectedValueOnce(new Error('fail'));

		await handleDeleteVersion('s1', 'v1', false);

		expect(get(status)).toBe('Delete failed');
	});
});

describe('handleDiffChange', () => {
	it('sets diff when pair provided', () => {
		const v1 = makeVersion();
		const v2 = makeVersion({ id: 'v2', version_number: 2 });
		handleDiffChange([v1, v2]);
		const diff = get(activeDiff);
		expect(diff?.old.id).toBe('v1');
		expect(diff?.new.id).toBe('v2');
	});

	it('clears diff when null', () => {
		handleDiffChange(null);
		expect(get(activeDiff)).toBeNull();
	});
});

describe('handleApply', () => {
	it('sets applied diff and updates fields', () => {
		loadSongData(makeSong());
		handleApply({ lyrics: 'new lyrics', prompt: 'new prompt' });
		expect(get(editLyrics)).toBe('new lyrics');
		expect(get(editPrompt)).toBe('new prompt');
		const diff = get(activeDiff);
		expect(diff).not.toBeNull();
		expect(diff?.old.lyrics).toBe('hello');
		expect(diff?.new.lyrics).toBe('new lyrics');
	});

	it('only updates provided fields', () => {
		loadSongData(makeSong({ bpm: 120 }));
		handleApply({ bpm: 140 });
		expect(get(editBpm)).toBe(140);
		expect(get(editLyrics)).toBe('hello');
	});
});

describe('dismissAppliedDiff', () => {
	it('clears applied diff', () => {
		loadSongData(makeSong());
		handleApply({ lyrics: 'changed' });
		expect(get(activeDiff)).not.toBeNull();
		dismissAppliedDiff();
		expect(get(activeDiff)).toBeNull();
	});
});
