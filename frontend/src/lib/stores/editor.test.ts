import { makeGeneration, makeSong, makeVersion } from '$lib/test-utils/factories';
import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

vi.mock('$lib/stores/libraryData', () => ({
	replaceSongInList: vi.fn(),
	resetLibraryContinueItems: vi.fn()
}));
vi.mock('$lib/stores/player', async () => {
	const { writable } = await import('svelte/store');
	return {
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
	versions,
	currentVersionIndex,
	loadSongData,
	loadVersion,
	handleSave,
	handleDeleteVersion,
	discardDraft,
	computeDraftVersionNumber
} from './editor';
import { selectedSongId } from '$lib/stores/player';
import { resetLibraryContinueItems } from '$lib/stores/libraryData';
import type { GenerationItem, SongItem } from '$lib/api/types';

const songDefaults = {
	slug: 'test',
	title: 'Test',
	lyrics: 'hello',
	prompt: 'rock',
	generation_count: 0,
	created_at: ''
} satisfies Partial<SongItem>;

describe('editGenParams dirty tracking', () => {
	it('is not dirty after loading a song', () => {
		loadSongData(makeSong(songDefaults));
		expect(get(isDirty)).toBe(false);
	});

	it('is dirty when gen params change', () => {
		loadSongData(makeSong(songDefaults));
		setDraftGenParams({ inference_steps: 50 });
		expect(get(isDirty)).toBe(true);
	});

	it('is not dirty when gen params are set back to null', () => {
		loadSongData(makeSong(songDefaults));
		setDraftGenParams({ inference_steps: 50 });
		setDraftGenParams(null);
		expect(get(isDirty)).toBe(false);
	});

	it('loads generation_params from song', () => {
		const params = { shift: 5.0, inference_steps: 25 };
		loadSongData(makeSong({ ...songDefaults, generation_params: params }));
		expect(get(editGenParams)).toEqual(params);
		expect(get(isDirty)).toBe(false);
	});

	it('order-independent comparison', () => {
		const params = { shift: 5.0, inference_steps: 25 };
		loadSongData(makeSong({ ...songDefaults, generation_params: params }));
		setDraftGenParams({ inference_steps: 25, shift: 5.0 });
		expect(get(isDirty)).toBe(false);
	});

	it('detects dirty when only lyrics change with gen params present', () => {
		loadSongData(makeSong({ ...songDefaults, generation_params: { shift: 2.0 } }));
		setDraftLyrics('changed');
		expect(get(isDirty)).toBe(true);
	});
});

describe('loadSongData', () => {
	it('sets all edit fields', () => {
		loadSongData(
			makeSong({
				...songDefaults,
				lyrics: 'L',
				prompt: 'P',
				bpm: 99,
				audio_duration: 200,
				key_scale: 'C'
			})
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
		loadSongData(makeSong(songDefaults));
		loadVersion(99);
		expect(get(editLyrics)).toBe('hello');
	});
});

describe('handleSave', () => {
	it('calls updateSong, resets dirty state, and returns the saved song', async () => {
		vi.clearAllMocks();
		const { updateSong } = await import('$lib/api/client');
		const mockUpdate = vi.mocked(updateSong);
		const saved = makeSong({ ...songDefaults, version_count: 2 });
		mockUpdate.mockResolvedValueOnce(saved);

		loadSongData(makeSong(songDefaults));
		setDraftLyrics('new lyrics');
		expect(get(isDirty)).toBe(true);

		const result = await handleSave('s1');

		expect(mockUpdate).toHaveBeenCalled();
		expect(resetLibraryContinueItems).toHaveBeenCalledOnce();
		expect(get(isDirty)).toBe(false);
		expect(result).toBe(saved);
	});

	it('fails loud: rejects instead of swallowing the error', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockRejectedValueOnce(new Error('Network error'));

		loadSongData(makeSong(songDefaults));
		setDraftLyrics('new lyrics');

		await expect(handleSave('s1')).rejects.toThrow('Network error');
		expect(get(isDirty)).toBe(true);
	});
});

describe('discardDraft', () => {
	it('resets the draft to the last-saved values', () => {
		loadSongData(makeSong({ ...songDefaults, lyrics: 'saved lyrics' }));
		setDraftLyrics('unsaved edit');
		expect(get(isDirty)).toBe(true);

		discardDraft();

		expect(get(editLyrics)).toBe('saved lyrics');
		expect(get(isDirty)).toBe(false);
	});
});

describe('computeDraftVersionNumber', () => {
	it('predicts version_number + 1 for a normal save onto a version that already has takes', () => {
		const versions = [makeVersion({ id: 'v2', version_number: 2 }), makeVersion()];
		const generations = [makeGeneration({ seed: null, created_at: '', version_number: 2 })];

		expect(computeDraftVersionNumber(versions, generations)).toBe(3);
	});

	it('predicts the current version number when the take-less latest version will be overwritten in place', () => {
		// v1 has never been generated into — handleSave() overwrites it rather
		// than creating v2.
		const versions = [makeVersion()];
		const generations: GenerationItem[] = [];

		expect(computeDraftVersionNumber(versions, generations)).toBe(1);
	});

	it('predicts from the highest surviving version_number, not the count, after a middle version was deleted', () => {
		// v2 was deleted; v1 and v3 remain, both with takes. song.version_count
		// would now read 2, but the next save must land on v4.
		const versions = [makeVersion({ id: 'v3', version_number: 3 }), makeVersion()];
		const generations = [
			makeGeneration({ seed: null, created_at: '', version_number: 3 }),
			makeGeneration({ seed: null, created_at: '', id: 'g2' })
		];

		expect(computeDraftVersionNumber(versions, generations)).toBe(4);
	});

	it('returns 1 when the song has no versions yet', () => {
		expect(computeDraftVersionNumber([], [])).toBe(1);
	});
});

describe('handleDeleteVersion', () => {
	it('calls deleteVersion and refreshes', async () => {
		vi.clearAllMocks();
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		loadSongData(makeSong({ ...songDefaults, lyrics: 'deleted version' }));
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(
			makeSong({ ...songDefaults, lyrics: 'remaining lyrics' })
		);
		vi.mocked(fetchVersions).mockResolvedValueOnce([
			makeVersion({ lyrics: 'remaining lyrics', prompt: 'rock' })
		]);

		await handleDeleteVersion('s1', 'v1', false);

		expect(deleteVersion).toHaveBeenCalledWith('v1', false);
		expect(resetLibraryContinueItems).toHaveBeenCalledOnce();
		expect(get(editLyrics)).toBe('remaining lyrics');
	});

	it('does not overwrite another song editor if the user navigates away', async () => {
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		loadSongData(makeSong({ ...songDefaults, lyrics: 'keep me' }));
		setDraftLyrics('unsaved on s2');
		selectedSongId.set('s2');
		const delayed = new Promise<SongItem>((resolve) => {
			setTimeout(() => resolve(makeSong({ ...songDefaults, lyrics: 'deleted leftover' })), 0);
		});
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockReturnValueOnce(delayed);
		vi.mocked(fetchVersions).mockResolvedValueOnce([makeVersion({ lyrics: 'should not apply' })]);

		await handleDeleteVersion('s1', 'v1', false);

		expect(get(editLyrics)).toBe('unsaved on s2');
	});

	it('fails loud on failure', async () => {
		const { deleteVersion } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockRejectedValueOnce(new Error('fail'));

		await expect(handleDeleteVersion('s1', 'v1', false)).rejects.toThrow('fail');
	});
});
