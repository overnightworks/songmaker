import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

vi.mock('$lib/stores/player', async () => {
	const { writable } = await import('svelte/store');
	return {
		replaceSongInList: vi.fn(),
		selectedSongId: writable('s1')
	};
});

import {
	editGenParams,
	editLyrics,
	editPrompt,
	editBpm,
	editAudioDuration,
	editKeyScale,
	setDraftGenParams,
	setDraftLyrics,
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
	handleApply,
	dismissAppliedDiff
} from './editor';
import { selectedSongId } from '$lib/stores/player';
import type { SongItem, VersionItem } from '$lib/api/types';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Test',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: 'hello',
		prompt: 'rock',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '',
		is_shared: false,
		share_slug: null,
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
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		created_at: '',
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
		setDraftGenParams({ inference_steps: 50 });
		expect(get(isDirty)).toBe(true);
	});

	it('is not dirty when gen params are set back to null', () => {
		loadSongData(makeSong());
		setDraftGenParams({ inference_steps: 50 });
		setDraftGenParams(null);
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
		setDraftGenParams({ inference_steps: 25, shift: 5.0 });
		expect(get(isDirty)).toBe(false);
	});

	it('detects dirty when only lyrics change with gen params present', () => {
		loadSongData(makeSong({ generation_params: { shift: 2.0 } }));
		setDraftLyrics('changed');
		expect(get(isDirty)).toBe(true);
	});
});

describe('loadSongData', () => {
	it('sets all edit fields', () => {
		loadSongData(
			makeSong({ lyrics: 'L', prompt: 'P', bpm: 99, audio_duration: 200, key_scale: 'C' })
		);
		expect(get(editLyrics)).toBe('L');
		expect(get(editPrompt)).toBe('P');
		expect(get(editBpm)).toBe(99);
		expect(get(editAudioDuration)).toBe(200);
		expect(get(editKeyScale)).toBe('C');
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
		setDraftLyrics('new lyrics');
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
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		loadSongData(makeSong({ lyrics: 'deleted version' }));
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(makeSong({ lyrics: 'remaining lyrics' }));
		vi.mocked(fetchVersions).mockResolvedValueOnce([
			makeVersion({ lyrics: 'remaining lyrics', prompt: 'rock' })
		]);

		await handleDeleteVersion('s1', 'v1', false);

		expect(deleteVersion).toHaveBeenCalledWith('v1', false);
		expect(get(editLyrics)).toBe('remaining lyrics');
	});

	it('does not overwrite another song editor if the user navigates away', async () => {
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		loadSongData(makeSong({ lyrics: 'keep me' }));
		setDraftLyrics('unsaved on s2');
		selectedSongId.set('s2');
		const delayed = new Promise<SongItem>((resolve) => {
			setTimeout(() => resolve(makeSong({ lyrics: 'deleted leftover' })), 0);
		});
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockReturnValueOnce(delayed);
		vi.mocked(fetchVersions).mockResolvedValueOnce([makeVersion({ lyrics: 'should not apply' })]);

		await handleDeleteVersion('s1', 'v1', false);

		expect(get(editLyrics)).toBe('unsaved on s2');
	});

	it('shows error on failure', async () => {
		const { deleteVersion } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockRejectedValueOnce(new Error('fail'));

		await handleDeleteVersion('s1', 'v1', false);

		expect(get(status)).toBe('Delete failed');
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
