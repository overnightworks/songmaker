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
	replaceSongInList: vi.fn()
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
	draftLoadedFrom,
	draftHasUnversionedChanges,
	loadSongData,
	loadVersionAsDraft,
	offerSetAsideVersionLoadUndoAgain,
	retireVersionLoadUndo,
	setAsideVersionLoadUndo,
	savedSongData,
	handleSave,
	handleDeleteVersion,
	discardDraft,
	computeDraftVersionNumber,
	versionDeleteEditorLoss
} from './editor';
import { selectedSongId } from '$lib/stores/player';
import type { GenerationItem, SongItem } from '$lib/api/types';

type VersionLoad = ReturnType<typeof loadVersionAsDraft>;

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

describe('loadVersionAsDraft', () => {
	const latest = makeVersion({ id: 'v2', version_number: 2, lyrics: 'hello', prompt: 'rock' });
	const older = makeVersion({
		id: 'v1',
		version_number: 1,
		lyrics: 'v1 lyrics',
		prompt: 'v1 prompt',
		bpm: 84,
		audio_duration: 210,
		key_scale: 'F minor',
		generation_params: { inference_steps: 40 }
	});

	function openSongWithTwoVersions(): void {
		selectedSongId.set('s1');
		loadSongData(makeSong({ ...songDefaults, id: 's1' }));
		versions.set([latest, older]);
	}

	it('puts the older version into the draft and keeps the latest as saved', () => {
		openSongWithTwoVersions();
		loadVersionAsDraft(older);
		expect(get(editLyrics)).toBe('v1 lyrics');
		expect(get(editPrompt)).toBe('v1 prompt');
		expect(get(editBpm)).toBe(84);
		expect(get(editAudioDuration)).toBe(210);
		expect(get(editKeyScale)).toBe('F minor');
		expect(get(editGenParams)).toEqual({ inference_steps: 40 });
		expect(get(savedSongData).lyrics).toBe('hello');
		expect(get(isDirty)).toBe(true);
		expect(get(draftLoadedFrom)).toBe(1);
	});

	it('takes the current version as the way back to the saved state', () => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		loadVersionAsDraft(latest);
		expect(get(editLyrics)).toBe('hello');
		expect(get(isDirty)).toBe(false);
		expect(get(draftLoadedFrom)).toBeNull();
	});

	it('asks nothing of the server', async () => {
		const client = await import('$lib/api/client');
		vi.clearAllMocks();
		openSongWithTwoVersions();
		vi.mocked(client.fetchVersions).mockClear();
		loadVersionAsDraft(older);
		expect(client.updateSong).not.toHaveBeenCalled();
		expect(client.fetchVersions).not.toHaveBeenCalled();
		expect(client.fetchSong).not.toHaveBeenCalled();
		expect(client.deleteVersion).not.toHaveBeenCalled();
	});

	it.each([
		{ draft: 'the song as opened', change: () => undefined, unversioned: false },
		{
			draft: 'an older version loaded and left untouched',
			change: () => loadVersionAsDraft(older),
			unversioned: false
		},
		{ draft: 'a typed line', change: () => setDraftLyrics('an unsaved line'), unversioned: true },
		{
			draft: 'an older version loaded and then edited',
			change: () => {
				loadVersionAsDraft(older);
				setDraftLyrics('v1 lyrics\na typed line');
			},
			unversioned: true
		}
	])(
		'only a draft no saved version equals has changes in no version: $draft',
		({ change, unversioned }) => {
			openSongWithTwoVersions();
			change();
			expect(get(draftHasUnversionedChanges)).toBe(unversioned);
		}
	);

	const twinOfLatest = makeVersion({
		id: 'v1',
		version_number: 1,
		lyrics: 'hello',
		prompt: 'rock'
	});

	const allShown = { toast: true, hint: true, draftChip: true };

	it.each([
		{ load: 'an older version', version: older, typed: false, shown: allShown },
		{
			load: 'an older version with the text of the current one',
			version: twinOfLatest,
			typed: false,
			shown: allShown
		},
		{
			load: 'an older version with the text of the current one over a typed draft',
			version: twinOfLatest,
			typed: true,
			shown: allShown
		},
		{
			load: 'the current version over a typed draft, back to saved',
			version: latest,
			typed: true,
			shown: { toast: true, hint: false, draftChip: false }
		}
	])(
		'a load of $load shows the toast, the hint and the draft chip together, or only the toast',
		({ version, typed, shown }) => {
			openSongWithTwoVersions();
			versions.set(version === latest ? [latest, older] : [latest, version]);
			if (typed) setDraftLyrics('an unsaved line');
			const load = loadVersionAsDraft(version);
			expect({
				toast: load !== null,
				hint: get(draftLoadedFrom) !== null,
				draftChip: get(isDirty)
			}).toEqual(shown);
		}
	);

	it('answers no undo when the draft already holds that version', () => {
		openSongWithTwoVersions();
		expect(loadVersionAsDraft(latest)).toBeNull();
		loadVersionAsDraft(older);
		expect(loadVersionAsDraft(older)).toBeNull();
		expect(get(draftLoadedFrom)).toBe(1);
	});

	it('undo puts back exactly the draft that was replaced', () => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		setDraftGenParams({ shift: 3 });
		loadVersionAsDraft(older)?.undo();
		expect(get(editLyrics)).toBe('an unsaved line');
		expect(get(editGenParams)).toEqual({ shift: 3 });
		expect(get(savedSongData).lyrics).toBe('hello');
		expect(get(draftLoadedFrom)).toBeNull();
	});

	it('undo of a second load brings back the first load and its hint', () => {
		openSongWithTwoVersions();
		loadVersionAsDraft(older);
		loadVersionAsDraft(latest)?.undo();
		expect(get(editLyrics)).toBe('v1 lyrics');
		expect(get(draftLoadedFrom)).toBe(1);
	});

	it('undo leaves another song alone once the editor has moved on', () => {
		openSongWithTwoVersions();
		const load = loadVersionAsDraft(older);
		selectedSongId.set('s2');
		loadSongData(makeSong({ ...songDefaults, id: 's2', lyrics: 'other song' }));
		load?.undo();
		expect(get(editLyrics)).toBe('other song');
		expect(get(isDirty)).toBe(false);
		expect(load && get(load.holds)).toBe(false);
	});

	async function saveSongS1(): Promise<void> {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(makeSong({ ...songDefaults, id: 's1' }));
		await handleSave('s1');
	}

	it.each([
		{
			action: 'typing in the draft',
			lyrics: 'v1 lyrics\na typed line',
			act: () => setDraftLyrics('v1 lyrics\na typed line')
		},
		{ action: 'another load', lyrics: 'hello', act: () => loadVersionAsDraft(latest) },
		{ action: 'the retire call', lyrics: 'v1 lyrics', act: retireVersionLoadUndo },
		{ action: 'a save', lyrics: 'v1 lyrics', act: saveSongS1 }
	])('undo is offered only until the next action: $action', async ({ lyrics, act }) => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		const load = loadVersionAsDraft(older);
		expect(load && get(load.holds)).toBe(true);
		await act();
		expect(load && get(load.holds)).toBe(false);
		load?.undo();
		expect(get(editLyrics)).toBe(lyrics);
	});

	function offered(load: VersionLoad): boolean {
		return load !== null && get(load.holds) && !get(load.setAside);
	}

	it('the opened Versions list sets the undo aside: it is not offered, and Undo restores nothing', () => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		const load = loadVersionAsDraft(older);
		setAsideVersionLoadUndo();

		expect(offered(load)).toBe(false);
		load?.undo();
		expect(get(editLyrics)).toBe('v1 lyrics');
	});

	it.each([
		{ end: 'a load that changes nothing', act: () => loadVersionAsDraft(older) },
		{ end: 'the list closing without a load', act: offerSetAsideVersionLoadUndoAgain }
	])('$end offers the set-aside undo again', ({ act }) => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		const load = loadVersionAsDraft(older);
		setAsideVersionLoadUndo();

		act();

		expect(offered(load)).toBe(true);
		load?.undo();
		expect(get(editLyrics)).toBe('an unsaved line');
	});

	it.each([
		{ end: 'loading another version from it', act: () => loadVersionAsDraft(latest) },
		{ end: 'a retire', act: retireVersionLoadUndo },
		{ end: 'its toast timing out', act: (load: VersionLoad) => load?.expire() }
	])('the set-aside undo is not offered again after $end', ({ act }) => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		const load = loadVersionAsDraft(older);
		setAsideVersionLoadUndo();
		act(load);

		offerSetAsideVersionLoadUndoAgain();

		expect(offered(load)).toBe(false);
		load?.undo();
		expect(get(editLyrics)).not.toBe('an unsaved line');
	});

	it('an earlier load timing out leaves the newer load its undo', () => {
		openSongWithTwoVersions();
		setDraftLyrics('an unsaved line');
		const earlier = loadVersionAsDraft(older);
		const newer = loadVersionAsDraft(latest);
		earlier?.expire();

		newer?.undo();

		expect(get(editLyrics)).toBe('v1 lyrics');
	});

	it.each([
		{ draft: 'a loaded older version', load: true, newVersion: true },
		{ draft: 'an edit of the latest version', load: false, newVersion: false }
	])('saving $draft asks for a new version: $newVersion', async ({ load, newVersion }) => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(makeSong({ ...songDefaults, id: 's1' }));
		openSongWithTwoVersions();
		if (load) loadVersionAsDraft(older);
		else setDraftLyrics('an edited line');
		await handleSave('s1');
		expect(updateSong).toHaveBeenLastCalledWith(
			's1',
			expect.objectContaining({ new_version: newVersion })
		);
	});

	it('the hint goes once the loaded draft is saved', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(makeSong({ ...songDefaults, id: 's1' }));
		openSongWithTwoVersions();
		loadVersionAsDraft(older);
		await handleSave('s1');
		expect(get(draftLoadedFrom)).toBeNull();
	});

	it('the hint stays gone after a discard, even once the draft is edited again', () => {
		openSongWithTwoVersions();
		loadVersionAsDraft(older);
		discardDraft();
		setDraftLyrics('a fresh line');
		expect(get(draftLoadedFrom)).toBeNull();
	});

	it('the hint goes when another song is opened', () => {
		openSongWithTwoVersions();
		loadVersionAsDraft(older);
		loadSongData(makeSong({ ...songDefaults, id: 's2' }));
		expect(get(draftLoadedFrom)).toBeNull();
	});
});

describe('versionDeleteEditorLoss', () => {
	const latest = makeVersion({ id: 'v3', version_number: 3, lyrics: 'hello', prompt: 'rock' });
	const middle = makeVersion({ id: 'v2', version_number: 2, lyrics: 'v2 lyrics' });
	const older = makeVersion({ id: 'v1', version_number: 1, lyrics: 'v1 lyrics' });

	it.each([
		{ deleted: older, draft: 'the latest', change: () => undefined, loss: null },
		{
			deleted: older,
			draft: 'a typed line',
			change: () => setDraftLyrics('an unsaved line'),
			loss: { kind: 'unsaved-draft', emptiesEditor: false }
		},
		{
			deleted: older,
			draft: 'its own untouched load',
			change: () => loadVersionAsDraft(older),
			loss: { kind: 'loaded-draft-goes', loadedFrom: 1 }
		},
		{
			deleted: older,
			draft: 'its own load with a typed line',
			change: () => {
				loadVersionAsDraft(older);
				setDraftLyrics('v1 lyrics and a typed line');
			},
			loss: { kind: 'unsaved-draft', emptiesEditor: false }
		},
		{
			deleted: middle,
			draft: 'an untouched load of another older version',
			change: () => loadVersionAsDraft(older),
			loss: { kind: 'loaded-draft-replaced', loadedFrom: 1, replacedBy: 3 }
		},
		{
			deleted: latest,
			draft: 'an untouched load of the version that becomes the latest',
			change: () => loadVersionAsDraft(middle),
			loss: null
		},
		{
			deleted: latest,
			draft: 'an untouched load of an older version',
			change: () => loadVersionAsDraft(older),
			loss: { kind: 'loaded-draft-replaced', loadedFrom: 1, replacedBy: 2 }
		},
		{
			deleted: latest,
			draft: 'a typed line',
			change: () => setDraftLyrics('an unsaved line'),
			loss: { kind: 'unsaved-draft', emptiesEditor: false }
		},
		{
			deleted: latest,
			draft: 'the latest',
			change: () => undefined,
			loss: { kind: 'current-lyrics', replacedBy: 2 }
		}
	])(
		'deleting v$deleted.version_number under $draft takes from the editor: $loss',
		({ deleted, change, loss }) => {
			selectedSongId.set('s1');
			loadSongData(makeSong({ ...songDefaults, id: 's1' }));
			versions.set([latest, middle, older]);
			change();
			expect(versionDeleteEditorLoss(deleted)).toEqual(loss);
		}
	);

	it.each([
		{ draft: 'the latest', change: () => undefined, loss: { kind: 'all-lyrics' } },
		{
			draft: 'a typed line',
			change: () => setDraftLyrics('an unsaved line'),
			loss: { kind: 'unsaved-draft', emptiesEditor: true }
		}
	])('deleting the only version under $draft empties the editor: $loss', ({ change, loss }) => {
		loadSongData(makeSong({ ...songDefaults, id: 's1' }));
		versions.set([latest]);
		change();
		expect(versionDeleteEditorLoss(latest)).toEqual(loss);
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

		expect(computeDraftVersionNumber(versions, generations, false)).toBe(3);
	});

	it('predicts the current version number when the take-less latest version will be overwritten in place', () => {
		// v1 has never been generated into — handleSave() overwrites it rather
		// than creating v2.
		const versions = [makeVersion()];
		const generations: GenerationItem[] = [];

		expect(computeDraftVersionNumber(versions, generations, false)).toBe(1);
	});

	it('predicts version_number + 1 when a loaded draft is saved over a take-less latest version', () => {
		const versions = [makeVersion({ id: 'v2', version_number: 2 }), makeVersion()];
		const generations = [makeGeneration({ seed: null, created_at: '', version_number: 1 })];

		expect(computeDraftVersionNumber(versions, generations, true)).toBe(3);
	});

	it('predicts from the highest surviving version_number, not the count, after a middle version was deleted', () => {
		// v2 was deleted; v1 and v3 remain, both with takes. song.version_count
		// would now read 2, but the next save must land on v4.
		const versions = [makeVersion({ id: 'v3', version_number: 3 }), makeVersion()];
		const generations = [
			makeGeneration({ seed: null, created_at: '', version_number: 3 }),
			makeGeneration({ seed: null, created_at: '', id: 'g2' })
		];

		expect(computeDraftVersionNumber(versions, generations, false)).toBe(4);
	});

	it('returns 1 when the song has no versions yet', () => {
		expect(computeDraftVersionNumber([], [], false)).toBe(1);
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
