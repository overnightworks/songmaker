import { makeSong, makeVersion } from '#lib/test-utils/factories.ts';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('#lib/api/client.ts', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

vi.mock('#lib/stores/libraryData.ts', () => ({
	replaceSongInList: vi.fn()
}));
vi.mock('#lib/stores/player.ts', async () => {
	const { writable } = await import('svelte/store');
	return {
		selectedSongId: writable('s1'),
		selectedSong: writable(null)
	};
});

import {
	draftLoadedFrom,
	discardDraft,
	editLyrics,
	handleSave,
	isDirty,
	loadSongData,
	loadVersionAsDraft,
	setDraftLyrics,
	versions
} from './editor';
import { selectedSongId } from '#lib/stores/player.ts';
import type { SongItem } from '#lib/api/types.ts';

const savedSongFields = {
	slug: 'test',
	title: 'Test',
	lyrics: 'hello',
	prompt: 'rock',
	generation_count: 0,
	created_at: ''
} satisfies Partial<SongItem>;

beforeEach(discardDraft);

describe('handleSave', () => {
	const version = (number: number) =>
		makeVersion({ id: 'v' + number, version_number: number, lyrics: 'loaded version' });

	const saveScenarios = [
		{
			scenario: 'no intervening edit',
			from: null,
			editBefore: true,
			action: 'none',
			nextFrom: null,
			expectedLyrics: 'sent draft',
			dirty: false
		},
		{
			scenario: 'typing during save',
			from: null,
			editBefore: true,
			action: 'type',
			nextFrom: null,
			expectedLyrics: 'typed during save',
			dirty: true
		},
		{
			scenario: 'typing after loaded version',
			from: 1,
			editBefore: true,
			action: 'type',
			nextFrom: null,
			expectedLyrics: 'typed during save',
			dirty: true
		},
		{
			scenario: 'another version loaded during save',
			from: 1,
			editBefore: true,
			action: 'load v2',
			nextFrom: 2,
			expectedLyrics: 'loaded version',
			dirty: true
		},
		{
			scenario: 'same version reloaded during save',
			from: 1,
			editBefore: true,
			action: 'load v1',
			nextFrom: 1,
			expectedLyrics: 'loaded version',
			dirty: true
		},
		{
			scenario: 'unchanged-version no-op load',
			from: 1,
			editBefore: false,
			action: 'load v1',
			nextFrom: null,
			expectedLyrics: 'loaded version',
			dirty: false
		},
		{
			scenario: 'load latest then Undo during save',
			from: 1,
			editBefore: true,
			action: 'undo latest',
			nextFrom: null,
			expectedLyrics: 'sent draft',
			dirty: false
		},
		{
			scenario: 'load v2, load v3, Save, then Undo',
			from: 2,
			editBefore: false,
			action: 'undo v3',
			nextFrom: 2,
			expectedLyrics: 'loaded version',
			dirty: true
		}
	];

	async function saveWithIntervention({
		from,
		editBefore,
		action
	}: Pick<(typeof saveScenarios)[number], 'from' | 'editBefore' | 'action'>): Promise<string> {
		const { updateSong } = await import('#lib/api/client.ts');
		let finishSave!: (song: SongItem) => void;
		vi.mocked(updateSong).mockReturnValueOnce(
			new Promise((resolve) => {
				finishSave = resolve;
			})
		);
		selectedSongId.set('s1');
		loadSongData(makeSong({ ...savedSongFields, id: 's1' }));
		await Promise.resolve();
		const latest = version(4);
		versions.set([latest, version(3), version(2), version(1)]);
		if (from !== null) loadVersionAsDraft(version(from));
		if (editBefore) setDraftLyrics('sent draft');
		const undo = action === 'undo v3' ? loadVersionAsDraft(version(3)) : null;
		const sentLyrics = get(editLyrics);
		const saving = handleSave('s1');
		if (action === 'type') setDraftLyrics('typed during save');
		if (action === 'load v1') loadVersionAsDraft(version(1));
		if (action === 'load v2') loadVersionAsDraft(version(2));
		if (action === 'undo latest') loadVersionAsDraft(latest)?.undo();
		if (action === 'undo v3') undo?.undo();
		finishSave(makeSong({ ...savedSongFields, id: 's1', lyrics: sentLyrics }));
		await saving;
		return sentLyrics;
	}

	it.each(saveScenarios)(
		'defect:#1598 save records the sent draft as saved: $scenario',
		async (scenario) => {
			const sentLyrics = await saveWithIntervention(scenario);
			discardDraft();
			expect(get(editLyrics)).toBe(sentLyrics);
		}
	);

	it.each(saveScenarios)(
		'defect:#1598 save records only the sent draft and provenance: $scenario',
		async (scenario) => {
			const { updateSong } = await import('#lib/api/client.ts');
			const { nextFrom, expectedLyrics, dirty } = scenario;
			await saveWithIntervention(scenario);
			expect(get(editLyrics)).toBe(expectedLyrics);
			expect(get(draftLoadedFrom)).toBe(nextFrom);
			expect(get(isDirty)).toBe(dirty);
			vi.mocked(updateSong).mockResolvedValueOnce(
				makeSong({ ...savedSongFields, lyrics: expectedLyrics })
			);
			await handleSave('s1');
			expect(updateSong).toHaveBeenLastCalledWith(
				's1',
				expect.objectContaining({ new_version: nextFrom !== null })
			);
			expect(get(isDirty)).toBe(false);
			discardDraft();
			expect(get(editLyrics)).toBe(expectedLyrics);
		}
	);

	it('calls updateSong, resets dirty state, and returns the saved song', async () => {
		vi.clearAllMocks();
		const { updateSong } = await import('#lib/api/client.ts');
		const mockUpdate = vi.mocked(updateSong);
		const saved = makeSong({ ...savedSongFields, version_count: 2 });
		mockUpdate.mockResolvedValueOnce(saved);

		loadSongData(makeSong(savedSongFields));
		setDraftLyrics('new lyrics');
		expect(get(isDirty)).toBe(true);

		const result = await handleSave('s1');

		expect(mockUpdate).toHaveBeenCalled();
		expect(get(isDirty)).toBe(false);
		expect(result).toBe(saved);
	});

	it('fails loud: rejects instead of swallowing the error', async () => {
		const { updateSong } = await import('#lib/api/client.ts');
		vi.mocked(updateSong).mockRejectedValueOnce(new Error('Network error'));

		loadSongData(makeSong(savedSongFields));
		setDraftLyrics('new lyrics');

		await expect(handleSave('s1')).rejects.toThrow('Network error');
		expect(get(isDirty)).toBe(true);
	});
});
