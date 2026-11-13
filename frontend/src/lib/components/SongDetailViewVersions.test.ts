import { songDetailApi } from '#lib/test-utils/song-detail-mocks.ts';
import { words } from '#lib/words/en.ts';
import {
	clearSongDetailState,
	clickNamed,
	editableSongDefaults,
	jobStatus,
	renderView,
	resetSongDetailState,
	settleRender,
	sourceRecipeDefaults,
	stubLibraryMedia,
	writeSaveButton
} from '#lib/test-utils/song-detail-view.ts';
import {
	makeGeneration as generation,
	makeSong as song,
	makeVersion as version
} from '#lib/test-utils/factories.ts';
import { tick, flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { EDITOR_GENERATE_LABEL } from '#lib/constants/song.ts';
import { deleteVersion, fetchVersions, updateSong } from '#lib/api/client.ts';
import { addToast, addUndoToast } from '#lib/stores/toast.ts';
import { songList } from '#lib/stores/libraryData.ts';
import {
	editLyrics,
	loadVersionAsDraft,
	pendingVersionLoad,
	setDraftLyrics,
	versions
} from '#lib/stores/editor.ts';
import { navigateToSongTab, openEditTab } from '#lib/stores/navigation.ts';
import { recipeModel } from '#lib/stores/recipe.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { DIALOG_CANCEL_LABEL } from '#lib/constants/dialog.ts';

// Stands in for the router the way the real one behaves for this app: a song
// selection can cross into the song's own address, which writeLibraryHistory
// sends through `goto` -- unmocked, that call needs a live SvelteKit router this
// harness never mounts.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('#lib/api/albums.ts', async () =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).albumsApiMock()
);
vi.mock('#lib/api/loras.ts', async (importOriginal) =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).lorasApiMock(
		await importOriginal<typeof import('#lib/api/loras.ts')>()
	)
);
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('#lib/api/client.ts', async (importOriginal) =>
	(await import('#lib/test-utils/song-detail-mocks.ts')).clientApiMock(
		await importOriginal<typeof import('#lib/api/client.ts')>()
	)
);
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

const { generateSong } = songDetailApi;

beforeEach(resetSongDetailState);

afterEach(clearSongDetailState);

describe.each([false, true])('SongDetailView loading a version, phone layout %s', (phone) => {
	const LATEST = version({
		id: 'v2',
		version_number: 2,
		lyrics: 'verse',
		prompt: 'dark folk',
		created_at: '2026-10-02T12:00:00+00:00'
	});
	const FIRST = version({
		id: 'v1',
		version_number: 1,
		lyrics: 'first draft',
		prompt: 'slow ballad',
		bpm: 84,
		created_at: '2026-09-24T12:00:00+00:00'
	});

	beforeEach(async () => {
		recipeModel.set('turbo');
		stubLibraryMedia({ narrow: phone });
		openEditTab();
		const { fetchVersions } = await import('#lib/api/client.ts');
		vi.mocked(fetchVersions).mockResolvedValueOnce([LATEST, FIRST]);
		const shown = await shownToasts();
		shown.toasts.set([]);
		vi.mocked(addUndoToast).mockClear().mockImplementation(shown.addUndoToast);
		vi.mocked(updateSong).mockClear();
		vi.mocked(deleteVersion).mockReset();
	});

	afterEach(() => {
		vi.mocked(addUndoToast).mockReset();
	});

	function shownToasts(): Promise<typeof import('#lib/stores/toast.ts')> {
		return vi.importActual<typeof import('#lib/stores/toast.ts')>('#lib/stores/toast.ts');
	}

	function versionChip(target: HTMLElement): HTMLButtonElement {
		const chip = target.querySelector<HTMLButtonElement>('.version-chip');
		if (!chip) throw new Error('Expected the version chip');
		return chip;
	}

	function versionsSheet(): HTMLElement | null {
		return document.querySelector<HTMLElement>(
			`[role="dialog"][aria-label="${words['versions.heading']}"]`
		);
	}

	function replaceDialog(): HTMLElement | null {
		return document.querySelector<HTMLElement>(
			`[role="dialog"][aria-label="${words['versions.replaceTitle']}"]`
		);
	}

	async function tapVersion(target: HTMLElement, versionNumber: number): Promise<void> {
		await vi.waitFor(() =>
			expect(versionChip(target).textContent).toContain(words['versions.name']({ number: '2' }))
		);
		versionChip(target).click();
		await tick();
		const row = Array.from(document.querySelectorAll<HTMLButtonElement>('.version-row')).find(
			(el) => el.textContent?.trim().startsWith(`v${versionNumber}`)
		);
		if (!row) throw new Error(`Expected the v${versionNumber} row`);
		row.click();
		await settleRender();
	}

	function undoLastLoad(): void {
		const [, action] = vi.mocked(addUndoToast).mock.calls.at(-1) ?? [];
		if (!action) throw new Error('Expected an undo toast');
		void action.handler();
	}

	it('a clean draft loads the tapped version without asking; the chip stays on the latest', async () => {
		const target = await renderView();
		await tapVersion(target, 1);

		expect(replaceDialog()).toBeNull();
		expect(versionsSheet()).toBeNull();
		expect(get(editLyrics)).toBe('first draft');
		expect(versionChip(target).textContent?.trim()).toBe(
			words['versions.chipDraft']({ number: '2' })
		);
		expect(target.textContent).toContain(words['writeColumn.loadedFrom']({ number: '1' }));
		expect(addUndoToast).toHaveBeenCalledWith(
			words['versions.loaded']({ number: '1' }),
			expect.objectContaining({ label: words['versions.undo'] }),
			'brief'
		);
		expect(updateSong).not.toHaveBeenCalled();
	});

	it.runIf(!phone)(
		'an untouched load says how it differs, not that it is unsaved; a typed edit says it is unsaved',
		async () => {
			const target = await renderView();
			const statusLine = () => target.querySelector('.write-save-hint')?.textContent?.trim();
			await tapVersion(target, 1);

			expect(statusLine()).toBe('');
			expect(writeSaveButton(target).disabled).toBe(false);
			expect(target.querySelector('.draft-banner')?.textContent?.trim()).toMatch(
				/^Draft — differs from v2\. Generate creates v\d+\.$/
			);

			setDraftLyrics('first draft, edited');
			await tick();

			expect(statusLine()).toBe(words['songPage.unsavedTitle']);
		}
	);

	it.each([
		{ next: 2, lyrics: 'verse' },
		{ next: 1, lyrics: 'first draft' }
	])(
		'a draft equal to a saved version is clean: after an untouched v1, v$next loads without asking',
		async ({ next, lyrics }) => {
			const target = await renderView();
			await tapVersion(target, 1);
			await tapVersion(target, next);

			expect(replaceDialog()).toBeNull();
			expect(versionsSheet()).toBeNull();
			expect(get(editLyrics)).toBe(lyrics);
		}
	);

	async function openFromTakeGroup(target: HTMLElement, n: number): Promise<void> {
		const buttons = (css: string) => [...target.querySelectorAll<HTMLButtonElement>(css)];
		const named = (css: string, text: string) =>
			buttons(css).find((button) => button.textContent?.includes(text));
		named('button[aria-expanded="false"]', `v${n} ·`)?.click();
		flushSync();
		named('.version-link', words['takesList.openVersion']({ number: String(n) }))?.click();
		await settleRender();
	}

	it('Open v1 on a take group loads v1 as the draft and shows it on Edit', async () => {
		navigateToSongTab('takes');
		const target = await renderView();
		await vi.waitFor(() => expect(get(versions)).toHaveLength(2));

		await openFromTakeGroup(target, 1);

		expect(target.querySelector<HTMLTextAreaElement>('.lyrics-area')?.value).toBe('first draft');
		expect(versionChip(target).textContent?.trim()).toBe(
			words['versions.chipDraft']({ number: '2' })
		);
		expect(target.textContent).toContain(words['writeColumn.loadedFrom']({ number: '1' }));
		expect(addUndoToast).toHaveBeenCalledWith(
			words['versions.loaded']({ number: '1' }),
			expect.objectContaining({ label: words['versions.undo'] }),
			'brief'
		);
	});

	it('Open on the clean current version answers that it is already the draft and the focus moves to the lyrics', async () => {
		const takeOfV2 = generation({ ...sourceRecipeDefaults(), version_id: 'v2', version_number: 2 });
		songList.set([song({ ...editableSongDefaults(), generations: [takeOfV2] })]);
		navigateToSongTab('takes');
		const target = await renderView();
		await vi.waitFor(() => expect(get(versions)).toHaveLength(2));

		await openFromTakeGroup(target, 2);
		await vi.waitFor(() =>
			expect(document.activeElement).toBe(target.querySelector('textarea.lyrics-area'))
		);

		expect(addToast).toHaveBeenCalledWith(words['versions.alreadyDraft']({ number: '2' }), 'info');
		expect(addUndoToast).not.toHaveBeenCalled();
		expect(get(editLyrics)).toBe('verse');
	});

	it('an Open from Now Playing loads that version on arrival and shows it on Edit', async () => {
		navigateToSongTab('takes');
		pendingVersionLoad.set({ songId: 's1', versionId: 'v1' });
		const target = await renderView();

		await vi.waitFor(() =>
			expect(target.querySelector<HTMLTextAreaElement>('.lyrics-area')?.value).toBe('first draft')
		);
		expect(versionChip(target).textContent?.trim()).toBe(
			words['versions.chipDraft']({ number: '2' })
		);
		expect(target.textContent).toContain(words['writeColumn.loadedFrom']({ number: '1' }));
		expect(get(pendingVersionLoad)).toBeNull();
	});

	it('an Open from Now Playing over a dirty draft asks first', async () => {
		const target = await renderView();
		await vi.waitFor(() => expect(get(versions)).toHaveLength(2));
		setDraftLyrics('unsaved edit');
		pendingVersionLoad.set({ songId: 's1', versionId: 'v1' });
		await tick();

		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		expect(dialog.textContent).toContain(words['versions.replaceMessage']({ number: '1' }));
		expect(get(editLyrics)).toBe('unsaved edit');
		expect(target.textContent).not.toContain(words['writeColumn.loadedFrom']({ number: '1' }));
	});

	it('over a dirty draft asks first, and Cancel keeps the edit and the sheet', async () => {
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();
		await tapVersion(target, 1);

		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		expect(dialog.textContent).toContain(words['versions.replaceMessage']({ number: '1' }));
		clickNamed(dialog, DIALOG_CANCEL_LABEL);
		await settleRender();

		expect(replaceDialog()).toBeNull();
		expect(versionsSheet()).not.toBeNull();
		expect(get(editLyrics)).toBe('unsaved edit');
		expect(addUndoToast).not.toHaveBeenCalled();
	});

	const BRIEF_UNDO_TOAST_MS = 5000;

	async function replaceTypedDraftWith(target: HTMLElement, versionNumber: number): Promise<void> {
		setDraftLyrics('unsaved edit');
		await tick();
		await tapVersion(target, versionNumber);
		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		clickNamed(dialog, words['versions.replaceConfirm']);
		await settleRender();
	}

	it('Replace loads the version, and Undo brings the replaced edit back', async () => {
		const target = await renderView();
		await replaceTypedDraftWith(target, 1);

		expect(versionsSheet()).toBeNull();
		expect(get(editLyrics)).toBe('first draft');

		undoLastLoad();
		await tick();
		expect(get(editLyrics)).toBe('unsaved edit');
		expect(target.textContent).not.toContain(words['writeColumn.loadedFrom']({ number: '1' }));
		expect(updateSong).not.toHaveBeenCalled();
	});

	it.each([
		{ again: 'its row in the sheet', reload: (target: HTMLElement) => tapVersion(target, 1) },
		{
			again: 'its Open link on the take group',
			reload: async (target: HTMLElement) => {
				navigateToSongTab('takes');
				await tick();
				await openFromTakeGroup(target, 1);
			}
		}
	])(
		'loading the version the draft already holds changes nothing, and its Undo still brings the edit back: $again',
		async ({ reload }) => {
			const target = await renderView();
			await replaceTypedDraftWith(target, 1);

			await reload(target);

			expect(replaceDialog()).toBeNull();
			expect(versionsSheet()).toBeNull();
			expect(get(editLyrics)).toBe('first draft');
			const { toasts } = await shownToasts();
			const [loaded, ...others] = get(toasts);
			expect(others).toEqual([]);
			expect(loaded?.message).toBe(words['versions.loaded']({ number: '1' }));
			await loaded?.action?.handler();
			await tick();
			expect(get(editLyrics)).toBe('unsaved edit');
		}
	);

	it('loading the version the draft already holds brings back no Undo toast once its Undo timed out', async () => {
		const target = await renderView();
		vi.useFakeTimers();
		await replaceTypedDraftWith(target, 1);

		vi.advanceTimersByTime(BRIEF_UNDO_TOAST_MS);
		const { toasts } = await shownToasts();
		expect(get(toasts)).toEqual([]);
		await tapVersion(target, 1);

		expect(get(editLyrics)).toBe('first draft');
		expect(get(toasts)).toEqual([]);
	});

	async function toggleVersionsChip(target: HTMLElement): Promise<void> {
		versionChip(target).click();
		await tick();
	}

	function versionRowButton(versionNumber: number): HTMLButtonElement {
		const row = Array.from(document.querySelectorAll<HTMLButtonElement>('.version-row')).find(
			(el) => el.textContent?.trim().startsWith(`v${versionNumber}`)
		);
		if (!row) throw new Error(`Expected the v${versionNumber} row`);
		return row;
	}

	it('a peek at the Versions list keeps the Undo: its toast leaves while the list is open and comes back once it closes', async () => {
		const target = await renderView();
		await replaceTypedDraftWith(target, 1);
		const { toasts } = await shownToasts();

		await toggleVersionsChip(target);
		expect(get(toasts)).toEqual([]);
		await toggleVersionsChip(target);

		expect(versionsSheet()).toBeNull();
		const [loaded, ...others] = get(toasts);
		expect(others).toEqual([]);
		expect(loaded?.message).toBe(words['versions.loaded']({ number: '1' }));
		await loaded?.action?.handler();
		await tick();
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('the Undo toast keeps its time while the list is open: a tap on the loaded version brings it back with the time it had left', async () => {
		const target = await renderView();
		vi.useFakeTimers();
		await replaceTypedDraftWith(target, 1);
		vi.advanceTimersByTime(1000);
		await toggleVersionsChip(target);
		vi.advanceTimersByTime(4 * BRIEF_UNDO_TOAST_MS);

		versionRowButton(1).click();
		await settleRender();

		const { toasts } = await shownToasts();
		expect(get(toasts).map((toast) => toast.message)).toEqual([
			words['versions.loaded']({ number: '1' })
		]);
		vi.advanceTimersByTime(BRIEF_UNDO_TOAST_MS - 1001);
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(1);
		expect(get(toasts)).toEqual([]);
	});

	it('loading another version from the opened list retires the Undo of the last load', async () => {
		const target = await renderView();
		await replaceTypedDraftWith(target, 1);

		await tapVersion(target, 2);

		const { toasts } = await shownToasts();
		expect(get(toasts).map((toast) => toast.message)).toEqual([
			words['versions.loaded']({ number: '2' })
		]);
		const [, firstLoadUndo] = vi.mocked(addUndoToast).mock.calls[0] ?? [];
		await firstLoadUndo?.handler();
		expect(get(editLyrics)).toBe('verse');
	});

	it('the current version over a dirty draft goes back to the saved state behind the same confirm', async () => {
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();
		await tapVersion(target, 2);
		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		clickNamed(dialog, words['versions.replaceConfirm']);
		await tick();

		expect(get(editLyrics)).toBe('verse');
		expect(versionChip(target).textContent?.trim()).toBe(words['versions.name']({ number: '2' }));
	});

	async function askToDeleteVersion(
		target: HTMLElement,
		versionNumber: number,
		latestNumber = 2
	): Promise<void> {
		await vi.waitFor(() => expect(versionChip(target).textContent).toContain(`v${latestNumber}`));
		versionChip(target).click();
		await tick();
		const trash = document.querySelector<HTMLButtonElement>(
			`button[aria-label="${words['versions.deleteName']({ number: String(versionNumber) })}"]`
		);
		if (!trash) throw new Error(`Expected the delete on the v${versionNumber} row`);
		trash.click();
		await tick();
	}

	function deleteConfirm(): HTMLElement | null {
		return (
			Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).find((dialog) =>
				dialog
					.querySelector('h3')
					?.textContent?.startsWith(words['versions.deleteName']({ number: '' }))
			) ?? null
		);
	}

	function confirmLines(dialog: HTMLElement): string[] {
		return [dialog.querySelector('h3'), ...dialog.querySelectorAll('li')].map(
			(line) => line?.textContent?.trim() ?? ''
		);
	}

	function versionRowNumbers(): string[] {
		return Array.from(document.querySelectorAll('.version-number'), (el) => el.textContent ?? '');
	}

	it.each([
		{ takes: 1, picked: false, shown: [words['versions.deleteTitleTakes'](1, { number: '1' })] },
		{
			takes: 1,
			picked: true,
			shown: [
				words['versions.deleteTitleTakes'](1, { number: '1' }),
				words['versions.deletePick'](1)
			]
		},
		{
			takes: 2,
			picked: true,
			shown: [
				words['versions.deleteTitleTakes'](2, { number: '1' }),
				words['versions.deletePick'](2)
			]
		}
	])(
		'the delete on a row names its $takes take(s) (album pick among them: $picked), and Cancel deletes nothing',
		async ({ takes, picked, shown }) => {
			const takesOfV1 = Array.from({ length: takes }, (_, index) =>
				generation({
					...sourceRecipeDefaults(),
					id: `g${index + 1}`,
					generation_number: index + 1,
					is_picked: picked && index === 0
				})
			);
			songList.set([song({ ...editableSongDefaults(), generations: takesOfV1 })]);
			const target = await renderView();
			await askToDeleteVersion(target, 1);

			const dialog = deleteConfirm();
			if (!dialog) throw new Error('Expected the version delete confirm');
			expect(confirmLines(dialog)).toEqual(shown);
			clickNamed(dialog, DIALOG_CANCEL_LABEL);
			await tick();

			expect(deleteConfirm()).toBeNull();
			expect(deleteVersion).not.toHaveBeenCalled();
			expect(versionsSheet()).not.toBeNull();
			expect(versionRowNumbers()).toEqual([
				words['versions.name']({ number: '2' }),
				words['versions.name']({ number: '1' })
			]);
		}
	);

	const DELETE_V2 = words['versions.deleteTitle']({ number: '2' });
	const LOADED_V1_REPLACED_BY_V3 = words['versions.deleteLoadedDraftReplaced']({
		loadedFrom: '1',
		replacedBy: '3'
	});
	const THIRD = version({ id: 'v3', version_number: 3, lyrics: 'chorus', prompt: 'dark folk' });
	const typeAnEdit = () => setDraftLyrics('unsaved edit');
	const loadV1Untouched = () => void loadVersionAsDraft(FIRST);
	const loadV1WithItsUndoTimedOut = () => loadVersionAsDraft(FIRST)?.expire();
	const leaveTheCurrentVersion = () => undefined;

	it.each([
		{
			deleted: 1,
			draft: 'an unsaved edit',
			prepare: typeAnEdit,
			held: [LATEST, FIRST],
			shown: [
				words['versions.deleteTitleTakes'](1, { number: '1' }),
				words['versions.deleteDraftGoes']
			]
		},
		{
			deleted: 1,
			draft: 'an untouched load of v1',
			prepare: loadV1Untouched,
			held: [LATEST, FIRST],
			shown: [
				words['versions.deleteTitleTakes'](1, { number: '1' }),
				words['versions.deleteLoadedDraftGoes']({ number: '1' }),
				words['versions.deleteLoadUndoGoes']
			]
		},
		{
			deleted: 2,
			draft: 'an untouched load of v1',
			prepare: loadV1Untouched,
			held: [THIRD, LATEST, FIRST],
			shown: [DELETE_V2, LOADED_V1_REPLACED_BY_V3, words['versions.deleteLoadUndoGoes']]
		},
		{
			deleted: 2,
			draft: 'an untouched load of v1 whose Undo timed out',
			prepare: loadV1WithItsUndoTimedOut,
			held: [THIRD, LATEST, FIRST],
			shown: [DELETE_V2, LOADED_V1_REPLACED_BY_V3]
		},
		{
			deleted: 2,
			draft: 'the current version',
			prepare: leaveTheCurrentVersion,
			held: [LATEST, FIRST],
			shown: [DELETE_V2, words['versions.deleteReplacedBy']({ number: '1' })]
		},
		{
			deleted: 2,
			draft: 'the current version',
			prepare: leaveTheCurrentVersion,
			held: [LATEST],
			shown: [DELETE_V2, words['versions.deleteEmptiesEditor']]
		},
		{
			deleted: 2,
			draft: 'an unsaved edit',
			prepare: typeAnEdit,
			held: [LATEST],
			shown: [DELETE_V2, words['versions.deleteDraftGoes'], words['versions.deleteEmptiesEditor']]
		}
	])(
		'the delete on v$deleted under $draft says what leaves the editor ($held.length versions)',
		async ({ deleted, prepare, held, shown }) => {
			vi.mocked(fetchVersions).mockReset().mockResolvedValue([]).mockResolvedValueOnce(held);
			const target = await renderView();
			await vi.waitFor(() => expect(get(versions)).toHaveLength(held.length));
			prepare();
			await tick();
			await askToDeleteVersion(target, deleted, held[0].version_number);

			const dialog = deleteConfirm();
			if (!dialog) throw new Error('Expected the version delete confirm');
			expect(confirmLines(dialog)).toEqual(shown);
		}
	);

	it('Delete removes the version with its takes; the sheet stays open on the rest and keeps the focus', async () => {
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchVersions).mockResolvedValueOnce([LATEST]);
		const target = await renderView();
		await askToDeleteVersion(target, 1);
		const dialog = deleteConfirm();
		if (!dialog) throw new Error('Expected the version delete confirm');
		clickNamed(dialog, words['versions.deleteConfirm']);

		await vi.waitFor(() => expect(get(versions)).toEqual([LATEST]));
		await tick();
		expect(deleteVersion).toHaveBeenCalledExactlyOnceWith('v1', true);
		expect(addToast).toHaveBeenCalledWith(words['versions.deleted']({ number: '1' }), 'success');
		expect(deleteConfirm()).toBeNull();
		const sheet = versionsSheet();
		expect(sheet).not.toBeNull();
		expect(versionRowNumbers()).toEqual([words['versions.name']({ number: '2' })]);
		expect(sheet?.contains(document.activeElement)).toBe(true);
	});

	function typeInLyrics(target: HTMLElement): void {
		const lyrics = target.querySelector<HTMLTextAreaElement>('textarea.lyrics-area');
		if (!lyrics) throw new Error('Expected the lyrics field');
		lyrics.value = `${lyrics.value}\na typed line`;
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
	}

	it.each([
		{ action: 'typing in the draft', act: typeInLyrics },
		{
			action: 'Generate',
			act: (target: HTMLElement) =>
				getByRoleButton(
					target.querySelector<HTMLElement>('.generate-action') ?? target,
					EDITOR_GENERATE_LABEL
				).click()
		}
	])('the Undo toast of a load goes with the next action: $action', async ({ act }) => {
		generateSong.mockResolvedValue(jobStatus({ status: 'queued' }));
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();
		await tapVersion(target, 2);
		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		clickNamed(dialog, words['versions.replaceConfirm']);
		await settleRender();
		const { toasts } = await shownToasts();
		expect(get(toasts).map((t) => t.message)).toEqual([words['versions.loaded']({ number: '2' })]);

		act(target);
		await tick();

		expect(get(toasts)).toEqual([]);
		undoLastLoad();
		await tick();
		expect(get(editLyrics)).not.toBe('unsaved edit');
	});

	it('Generate after a load saves the loaded text as the next version; the hint and the Undo toast go', async () => {
		const { fetchVersions } = await import('#lib/api/client.ts');
		const next = version({ id: 'v3', version_number: 3, lyrics: 'first draft' });
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), lyrics: 'first draft', version_count: 3 })
		);
		vi.mocked(fetchVersions).mockResolvedValueOnce([next, LATEST, FIRST]);
		generateSong.mockResolvedValue(jobStatus({ status: 'queued' }));
		const target = await renderView();
		await tapVersion(target, 1);
		const { toasts } = await shownToasts();
		expect(get(toasts).map((t) => t.message)).toEqual([words['versions.loaded']({ number: '1' })]);

		getByRoleButton(
			target.querySelector<HTMLElement>('.generate-action') ?? target,
			EDITOR_GENERATE_LABEL
		).click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(1));

		expect(vi.mocked(updateSong).mock.calls[0]?.[1]).toEqual(
			expect.objectContaining({ lyrics: 'first draft', prompt: 'slow ballad', bpm: 84 })
		);
		expect(generateSong.mock.calls[0]?.[3]).toBe('v3');
		await tick();
		expect(target.textContent).not.toContain(words['writeColumn.loadedFrom']({ number: '1' }));
		expect(versionChip(target).textContent?.trim()).toBe(words['versions.name']({ number: '3' }));
		expect(get(toasts)).toEqual([]);
	});
});
