import { historyEntry, historyLength } from '#lib/test-utils/library-history.ts';
import {
	makeAlbum as album,
	makeGeneration as generation,
	makeSong as song,
	makeVersion as version
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { songDetailApi } from '#lib/test-utils/song-detail-mocks.ts';
import {
	clearSongDetailState,
	clickNamed,
	editableSongDefaults,
	jobStatus,
	mounted,
	renderView,
	resetSongDetailState,
	settleRender,
	sourceRecipeDefaults,
	stubLibraryMedia,
	writeSaveButton
} from '#lib/test-utils/song-detail-view.ts';
import { phoneAppBar } from '#lib/stores/ui.ts';
import PhoneAppBar from './PhoneAppBar.svelte';

import type { JobItem, SongItem } from '#lib/api/types.ts';
import { EDITOR_GENERATE_LABEL, EDITOR_GENERATING_LABEL } from '#lib/constants/song.ts';
import { TAKES_ERROR, TAKES_LOADING, TAKES_RETRY_LABEL } from '#lib/constants/take.ts';
import { COMPACT_LAYOUT_MAX_PX } from '#lib/constants/media.ts';
import { RECIPE_PANEL_LABEL } from '#lib/constants/recipe.ts';
import { accessibleName, getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { menuRow } from '#lib/test-utils/collection-menu.ts';
import { injectHitboxStyles } from '#lib/test-utils/hitbox.ts';
import { PHONE_APP_BAR_PROPS } from '#lib/test-utils/phone-app-bar.ts';
import {
	editLyrics,
	pendingVersionLoad,
	setDraftBpm,
	setDraftLyrics,
	setDraftPrompt
} from '#lib/stores/editor.ts';
import { activeJobs, generationFailures } from '#lib/stores/jobs.ts';
import {
	detailTab,
	type DetailTab,
	initNavigation,
	navigateToSongTab,
	persistLibraryHistory,
	selectSong,
	openEditTab
} from '#lib/stores/navigation.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { toggleSelection } from '#lib/stores/selection.ts';
import {
	pendingTakeUse,
	recipeModel,
	seedFromTake,
	recipeOpen,
	setSourceFromGeneration,
	sourceGeneration,
	sourceMode
} from '#lib/stores/recipe.ts';

const { fetchAlbum, uploadSongCover, deleteSongCover, deleteAlbumCover, generateSong, listLoras } =
	songDetailApi;

// Stands in for the router the way the real one behaves for this app (issue
// #275): a song selection can now cross from the wall's `/` into the song's
// own `/album/<slug>/<song-slug>` address, which writeLibraryHistory sends
// through `goto` -- unmocked, that call needs a live SvelteKit router this
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

import songDetailViewSource from './SongDetailView.svelte?raw';
import editorHeaderSource from './editor/EditorHeader.svelte?raw';
import recipeLineSource from './editor/RecipeLine.svelte?raw';
import recipeTabsSource from './editor/RecipeTabs.svelte?raw';
import takesListSource from './editor/TakesList.svelte?raw';
import writeColumnSource from './editor/WriteColumn.svelte?raw';
import {
	addGenerationToPlaylist,
	deleteSong,
	deleteVersion,
	fetchSong,
	fetchVersions,
	renameSong,
	updateSong
} from '#lib/api/client.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { addToast } from '#lib/stores/toast.ts';
import { words } from '#lib/words/en.ts';
import { reportResourceStreamReachable } from '#lib/stores/connectivity.ts';

function header(target: HTMLElement): HTMLElement {
	const el = target.querySelector<HTMLElement>('.detail-header');
	if (!el) throw new Error('Expected the Editor header row');
	return el;
}

function visibleText(el: HTMLElement): string {
	return (el.textContent ?? '').replace(/\s+/g, ' ');
}

function albumSongs(): SongItem[] {
	return [
		song({ ...editableSongDefaults(), id: 's-first', title: 'First' }),
		song({ ...editableSongDefaults(), track_number: 2 }),
		song({ ...editableSongDefaults(), id: 's-last', title: 'Last', track_number: 3 })
	];
}

async function renderWithDirtyDraft(): Promise<HTMLElement> {
	songList.set(albumSongs());
	const target = await renderView();
	setDraftLyrics('unsaved edit');
	await tick();
	return target;
}

beforeEach(resetSongDetailState);

afterEach(clearSongDetailState);

describe('SongDetailView header — one row, every state', () => {
	it('shows Generate alone, no Recipe toggle or Co-writer button, never a second toolbar row (C4, #1935 acceptance 6)', async () => {
		const target = await renderView();
		const actions = header(target).querySelector<HTMLElement>('.editor-header-actions');
		if (!actions) throw new Error('Expected header actions');
		expect(visibleText(actions)).not.toContain(words['songTabs.cowriter']);
		expect(visibleText(actions)).not.toContain(RECIPE_PANEL_LABEL);
		expect(target.querySelectorAll('.generate-action .primary-button')).toHaveLength(1);
		expect(target.querySelector('.generate-action .primary-button')?.textContent).toContain(
			EDITOR_GENERATE_LABEL
		);
	});

	it('opens the Recipe from its closed line first in the Write column (C4, #1935 acceptance 1)', async () => {
		const target = await renderView();
		const writeColumn = target.querySelector<HTMLElement>('.write-column') as HTMLElement;
		expect(target.querySelector('[role="region"][aria-label="Recipe"]')).toBeNull();
		clickNamed(writeColumn, RECIPE_PANEL_LABEL + ' ›');
		await tick();
		expect(get(recipeOpen)).toBe(true);
		expect(writeColumn.querySelector('[role="region"][aria-label="Recipe"]')).not.toBeNull();
	});

	it('opens the Co-writer in the right column while Style and Lyrics stay the growing document (S9, #1927 acceptance 2)', async () => {
		const target = await renderView();
		expect(target.querySelector('.cowriter')).toBeNull();
		const tab = target.querySelector<HTMLButtonElement>('[role="tab"][data-tab="cowriter"]');
		if (!tab) throw new Error('Expected the Co-writer tab');
		tab.click();
		await tick();
		expect(get(detailTab)).toBe('cowriter');
		expect(target.querySelector('.cowriter')).not.toBeNull();
		expect(target.querySelector('.detail-header')).not.toBeNull();
		expect(target.querySelectorAll('.write-mode textarea')).toHaveLength(2);
		expect(target.querySelector('.take-row')).toBeNull();
	});
});

describe('SongDetailView share link', () => {
	it('shows a copy-link chip for the public share address, whatever origin the app is opened at', async () => {
		const share_url = 'https://songmaker.example/share/song/abc123';
		songList.set([song({ ...editableSongDefaults(), is_shared: true, share_url })]);
		const target = await renderView();

		const chip = target.querySelector<HTMLButtonElement>('.share-link-chip');
		expect(chip?.textContent?.trim()).toBe('Copy link');
		expect(chip?.title).toBe(share_url);
		expect(target.textContent).not.toContain(share_url);
	});

	it('shows no share chip when the song is not shared', async () => {
		const target = await renderView();
		expect(target.querySelector('.share-link-chip')).toBeNull();
	});
});

describe('SongDetailView desktop vs compact layout', () => {
	it('shows Write and the Takes · Co-writer tabs as two simultaneous columns on desktop (S9, #1927 acceptance 1)', async () => {
		const target = await renderView();
		expect(target.querySelector('.editor-columns')).not.toBeNull();
		const tabs = target.querySelectorAll('.editor-columns [role="tab"]');
		expect(Array.from(tabs, (tab) => tab.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			`${words['songTabs.takes']} 1`,
			words['songTabs.cowriter']
		]);
		expect(target.querySelector('.lyrics-area')).not.toBeNull();
		expect(target.querySelector('.take-row')).not.toBeNull();
	});

	it('publishes the song actions in the layout bar and clears them when leaving', async () => {
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		const bar = document.createElement('div');
		document.body.append(bar);
		mounted.push(mount(PhoneAppBar, { target: bar, props: PHONE_APP_BAR_PROPS }));
		await tick();
		expect(bar.querySelector('h1')?.textContent?.trim()).toBe(get(songList)[0].title);
		expect(target.querySelector('.detail-header')).toBeNull();
		expect(target.querySelector('.write-save')).toBeNull();
		bar.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		const save = Array.from(bar.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(button) => button.textContent?.trim() === words['songMenu.save']
		);
		expect(save?.disabled).toBe(true);
		setDraftLyrics('A changed verse');
		await tick();
		expect(save?.disabled).toBe(false);
		const view = mounted.shift();
		if (!view) throw new Error('Expected mounted song view');
		await unmount(view);
		await tick();
		expect(get(phoneAppBar)).toBeNull();
		expect(bar.querySelector('.brand')?.textContent).toBe('Hallucinai');
	});

	it('switches between Edit and the real Takes list at phone width without losing the draft', async () => {
		openEditTab();
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		expect(target.querySelector('.editor-columns')).toBeNull();
		const lyrics = target.querySelector<HTMLTextAreaElement>('.lyrics-area');
		if (!lyrics) throw new Error('Expected editable lyrics');
		lyrics.value = 'An unfinished verse';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		expect(Array.from(tabs, (tab) => tab.textContent?.trim())).toEqual([
			words['songTabs.edit'],
			words['songTabs.cowriter'],
			`${words['songTabs.takes']} (1)`
		]);
		tabs[2].click();
		await tick();
		expect(target.querySelector('.lyrics-area')).toBeNull();
		expect(target.querySelectorAll('.take-row')).toHaveLength(1);
		expect(target.querySelector('.take-row button.play-btn')).not.toBeNull();
		tabs[0].click();
		await tick();
		expect(target.querySelector<HTMLTextAreaElement>('.lyrics-area')?.value).toBe(
			'An unfinished verse'
		);
		expect(target.querySelector('.takes-list')).toBeNull();
	});
});

describe('SongDetailView adding a take to a playlist', () => {
	it('reports the one add with exactly one toast', async () => {
		// #163/3: the take row shows the outcome, success and failure alike, so
		// the action it calls stays a plain mutation. Two owners meant two
		// toasts for a single entry.
		const target = await renderView();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		row.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		menuRow(row, words['takeMenu.addToPlaylist']).click();
		await tick();
		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		// The picker closes once the add has fully settled, toast included.
		await vi.waitFor(() => expect(row.querySelector('.picker')).toBeNull());

		expect(addGenerationToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(vi.mocked(addToast).mock.calls).toEqual([
			[words['songPage.addedToPlaylist'], 'success']
		]);
	});
});

describe('SongDetailView failure wording', () => {
	const OWN_COVER = {
		card: '/api/songs/s1/cover?variant=card&v=own.jpg',
		detail: '/api/songs/s1/cover?variant=detail&v=own.jpg'
	};

	function appBar() {
		const state = get(phoneAppBar);
		if (!state) throw new Error('Expected the song app bar');
		return state;
	}

	function chooseCoverFile(target: HTMLElement): void {
		const input = target.querySelector<HTMLInputElement>('.cover-file-input');
		if (!input) throw new Error('Expected the cover file input');
		const file = new File([new Uint8Array([1])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
	}

	const actions = [
		{
			action: 'renaming the song',
			fallback: words['songPage.renameFailed'],
			fail: (error: Error) => vi.mocked(renameSong).mockRejectedValueOnce(error),
			run: () =>
				appBar()
					.onrename('New title')
					.catch(() => undefined)
		},
		{
			action: 'uploading a cover',
			fallback: words['songPage.coverUploadFailed'],
			fail: (error: Error) => uploadSongCover.mockRejectedValueOnce(error),
			run: (target: HTMLElement) => chooseCoverFile(target)
		},
		{
			action: 'removing the cover',
			fallback: words['songPage.coverRemoveFailed'],
			ownCover: true,
			fail: (error: Error) => deleteSongCover.mockRejectedValueOnce(error),
			run: (target: HTMLElement) =>
				target.querySelector<HTMLButtonElement>('.cover-remove')?.click()
		},
		{
			action: 'saving a version',
			fallback: words['songPage.saveFailed'],
			fail: (error: Error) => vi.mocked(updateSong).mockRejectedValueOnce(error),
			run: () => appBar().menu.onsave()
		},
		{
			action: 'deleting a version from its Versions row',
			fallback: words['songPage.deleteFailed'],
			versions: [version({ id: 'v1', version_number: 1 })],
			fail: (error: Error) => vi.mocked(deleteVersion).mockRejectedValueOnce(error),
			run: async (target: HTMLElement) => {
				const chip = await vi.waitFor(() => {
					const found = target.querySelector<HTMLButtonElement>('.version-chip');
					if (!found) throw new Error('Expected the version chip');
					return found;
				});
				chip.click();
				await tick();
				getByRoleButton(document.body, words['versions.deleteName']({ number: '1' })).click();
				await tick();
				document.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
			}
		},
		{
			action: 'deleting the song',
			fallback: words['songPage.deleteFailed'],
			fail: (error: Error) => vi.mocked(deleteSong).mockRejectedValueOnce(error),
			run: async () => {
				appBar().menu.ondelete();
				await tick();
				document.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
			}
		}
	];

	it.each(
		actions.flatMap((entry) => [
			{
				...entry,
				failure: 'with no network answer',
				error: new NetworkError('/api/songs/s1', new TypeError('Failed to fetch')),
				shown: entry.fallback
			},
			{
				...entry,
				failure: 'refused by the server',
				error: new ApiError(409, 'The server keeps this song as it is', '/api/songs/s1'),
				shown: 'The server keeps this song as it is'
			}
		])
	)(
		'says $shown once when $action fails $failure',
		async ({ ownCover, versions: seededVersions, fail, run, error, shown }) => {
			if (ownCover) songList.set([song({ ...editableSongDefaults(), cover: OWN_COVER })]);
			if (seededVersions) vi.mocked(fetchVersions).mockResolvedValueOnce(seededVersions);
			fail(error);
			const target = await renderView();
			await run(target);
			await vi.waitFor(() => expect(vi.mocked(addToast).mock.calls).toEqual([[shown, 'error']]));
		}
	);
});

describe('SongDetailView recipe and takes', () => {
	function takesWithNoNetworkAnswer(): void {
		vi.mocked(fetchSong).mockRejectedValueOnce(
			new NetworkError('/api/songs/s1', new TypeError('Failed to fetch'))
		);
	}

	it('keeps the takes on screen and names nothing when their reload gets no network answer offline', async () => {
		reportResourceStreamReachable(false);
		takesWithNoNetworkAnswer();
		songList.set([song({ ...editableSongDefaults(), generation_count: 2 })]);
		const target = await renderView();
		await settleRender();
		expect(target.querySelectorAll('.take-row')).toHaveLength(1);
		expect(target.textContent).not.toContain(TAKES_ERROR);
		expect(target.textContent).not.toContain('Failed to fetch');
		expect(target.querySelector('.takes-list [role="alert"]')).toBeNull();
	});

	it('names the takes failure with Try again when a load gets no network answer while the page counts as online', async () => {
		takesWithNoNetworkAnswer();
		songList.set([song({ ...editableSongDefaults(), generation_count: 2 })]);
		const target = await renderView();
		await settleRender();
		const alert = target.querySelector('.takes-list [role="alert"]') as HTMLElement;
		expect(alert.textContent).toContain(TAKES_ERROR);
		expect(getByRoleButton(alert, TAKES_RETRY_LABEL)).toBeTruthy();
	});

	it('waits for the takes offline and reloads them by itself once the page is back online', async () => {
		reportResourceStreamReachable(false);
		takesWithNoNetworkAnswer();
		songList.set([song({ ...editableSongDefaults(), generation_count: 2, generations: [] })]);
		const target = await renderView();
		await settleRender();
		expect(target.textContent).toContain(TAKES_LOADING);
		expect(target.textContent).not.toContain(TAKES_ERROR);

		vi.mocked(fetchSong).mockResolvedValueOnce(
			song({
				...editableSongDefaults(),
				generation_count: 2,
				generations: [generation({ id: 'g1' }), generation({ id: 'g2' })]
			})
		);
		reportResourceStreamReachable(true);
		await vi.waitFor(() => expect(target.querySelectorAll('.take-row')).toHaveLength(2));
	});

	it.each([
		{
			failure: 'a server refusal',
			error: new ApiError(503, 'Takes are resting', '/api/songs/s1'),
			shown: 'Takes are resting',
			hidden: TAKES_ERROR
		},
		{
			failure: 'a bug that is not the network',
			error: new TypeError('generations is not iterable'),
			shown: TAKES_ERROR,
			hidden: 'generations is not iterable'
		}
	])(
		'names $failure in its own words when the takes cannot load',
		async ({ error, shown, hidden }) => {
			vi.mocked(fetchSong).mockRejectedValueOnce(error);
			songList.set([song({ ...editableSongDefaults(), generation_count: 2, generations: [] })]);
			const target = await renderView();
			await settleRender();
			expect(target.textContent).toContain(shown);
			expect(target.textContent).not.toContain(hidden);
		}
	);

	it('edits the phone recipe inline without opening a sheet', async () => {
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		detailTab.set('edit');
		await tick();
		(target.querySelector('.recipe-line') as HTMLButtonElement).click();
		await tick();
		const input = target.querySelector<HTMLInputElement>(
			'input[aria-label="BPM"]'
		) as HTMLInputElement;
		input.value = '96';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(target.querySelector('[data-field="bpm"] [data-field-changed]')).not.toBeNull();
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('loads deleted voices once and names their existing takes', async () => {
		listLoras.mockResolvedValueOnce([
			{
				id: 'l1',
				user_id: 'u1',
				name: 'Folk Alto',
				slug: 'folk-alto',
				status: 'ready',
				model_mode: 'sft',
				created_at: '2026-01-01T00:00:00+00:00',
				deleted_at: '2026-01-02T00:00:00+00:00',
				samples: []
			}
		]);
		songList.set([
			song({
				...editableSongDefaults(),
				generations: [
					generation({
						...sourceRecipeDefaults(),
						generation_params: { user_lora_id: 'l1' }
					})
				]
			})
		]);

		const target = await renderView();
		await vi.waitFor(() => expect(listLoras).toHaveBeenCalledOnce());
		expect(listLoras).toHaveBeenCalledWith(true);
		await tick();

		expect(target.querySelector('.take-voice')?.textContent?.trim()).toBe(
			'Voice: Folk Alto — voice deleted'
		);
		expect(visibleText(target)).not.toContain('Custom');
	});

	it('shows symbol actions and the row body instead of labelled source buttons in take rows', async () => {
		const target = await renderView();
		const row = target.querySelector('.take-row');
		expect(row).not.toBeNull();
		expect(row?.querySelectorAll('button')).toHaveLength(4);
		expect(row?.querySelector('[role="button"].take-summary')).not.toBeNull();
		expect(row?.textContent).not.toMatch(/Repaint|Cover/);
	});

	const sourceCases = [
		['repaint', false],
		['cover', false],
		['repaint', true],
		['cover', true]
	] as const;

	it('C6: lands a handed-over seed as the chip once its song is open', async () => {
		await renderView();
		pendingTakeUse.set({ generation: generation({ seed: 7, generation_number: 3 }), use: 'seed' });
		await tick();
		expect(get(seedFromTake)).toEqual({ seed: 7, takeNumber: 3 });
	});

	it.each(sourceCases)(
		'lands a picked-up %s source on its task card (compact: %s) (S9, #1927 acceptance 7)',
		async (mode, compact) => {
			stubLibraryMedia({ narrow: compact, compact });
			const target = await renderView();
			detailTab.set(compact ? 'edit' : 'cowriter');

			pendingTakeUse.set({ generation: generation(sourceRecipeDefaults()), use: mode });
			await tick();
			await tick();
			expect(get(recipeOpen)).toBe(false);
			expect(get(sourceMode)).toBe(mode);
			expect(get(detailTab)).toBe('takes');
			expect(target.querySelector('.take-row + .task')).not.toBeNull();
		}
	);

	it.each(sourceCases)(
		'opens the task card for the menu take as %s source (compact: %s)',
		async (mode, compact) => {
			stubLibraryMedia({ narrow: compact, compact });
			const target = await renderView();
			target.querySelector<HTMLButtonElement>('.take-row .menu-trigger')?.click();
			await tick();
			clickNamed(target, mode === 'repaint' ? words['takeMenu.repaint'] : words['takeMenu.cover']);
			await tick();
			expect(get(recipeOpen)).toBe(false);
			expect(get(sourceMode)).toBe(mode);
			expect(get(sourceGeneration)?.id).toBe('g1');
			expect(target.querySelector('.take-row + .task')).not.toBeNull();
			expect(target.querySelector('[role="dialog"]')).toBeNull();
		}
	);

	it.each(['Cancel', 'Delete'])('asks once before take deletion and honors %s', async (choice) => {
		const { deleteGeneration } = await import('#lib/api/client.ts');
		vi.mocked(deleteGeneration).mockClear();
		const target = await renderView();
		target.querySelector<HTMLButtonElement>('.take-row .menu-trigger')?.click();
		await tick();
		clickNamed(target, 'Delete');
		await tick();
		const dialog = target.querySelector<HTMLElement>('[role="dialog"]');
		if (!dialog) throw new Error('Expected a delete confirmation');
		expect(target.querySelectorAll('[role="dialog"]')).toHaveLength(1);
		expect(dialog.querySelector('input')).toBeNull();
		expect(dialog.textContent).toContain('Audio files will be permanently deleted');
		expect(deleteGeneration).not.toHaveBeenCalled();
		clickNamed(dialog, choice);
		await tick();
		if (choice === 'Delete') {
			expect(deleteGeneration).toHaveBeenCalledExactlyOnceWith('g1');
			expect(get(songList)[0].generations).toEqual([]);
		} else {
			expect(deleteGeneration).not.toHaveBeenCalled();
			expect(get(songList)[0].generations).toHaveLength(1);
		}
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('clears the open take from history when bulk delete includes it', async () => {
		selectedGenerationId.set('g1');
		persistLibraryHistory();
		// The write crosses into the song's own address (issue #275) and is
		// therefore asynchronous -- see the note on writeLibraryHistory.
		await vi.waitFor(() => expect(historyEntry().generationId).toBe('g1'));
		const target = await renderView();
		toggleSelection('g1');
		await tick();
		clickNamed(target, 'Delete 1');
		await tick();
		clickNamed(document.body, 'Delete');
		await tick();
		await vi.waitFor(() => expect(get(selectedGenerationId)).toBeNull());
		expect(historyEntry().generationId).toBeNull();
	});
});

describe('SongDetailView Generate is enabled from the draft', () => {
	it('stays disabled until the draft has lyrics, a prompt, and a model — even on a freshly created song with nothing saved', async () => {
		songList.set([song({ ...editableSongDefaults(), lyrics: '', prompt: '' })]);
		const target = await renderView();
		const generateBtn = () =>
			Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
				(el) => el.textContent?.trim() === EDITOR_GENERATE_LABEL
			);
		expect(generateBtn()?.disabled).toBe(true);

		setDraftLyrics('typed lyrics');
		setDraftPrompt('typed style');
		recipeModel.set('turbo');
		await tick();

		expect(generateBtn()?.disabled).toBe(false);
	});

	it.each(['repaint', 'cover'] as const)(
		'keeps Generate plain with a %s source set (S4, #1923 acceptance 3)',
		async (mode) => {
			const target = await renderView();
			setSourceFromGeneration(generation(sourceRecipeDefaults()), mode);
			await tick();

			expect(target.querySelector('.generate-action .primary-button')?.textContent?.trim()).toBe(
				EDITOR_GENERATE_LABEL
			);
		}
	);
});

describe.each([false, true])('SongDetailView Generate with phone layout %s', (phone) => {
	beforeEach(() => {
		recipeModel.set('turbo');
		stubLibraryMedia({ narrow: phone });
		openEditTab();
	});

	function generateBtn(target: HTMLElement): HTMLButtonElement | null {
		return target.querySelector<HTMLButtonElement>('.generate-action .primary-button');
	}

	it('[defect:#1579] shows the full failure at Generate and retries through the same button', async () => {
		const cause = 'Generating failed — try again.';
		generationFailures.set({ s1: { message: cause, unavailable: false } });
		generateSong.mockResolvedValue(jobStatus({ status: 'queued' }));
		const target = await renderView();
		const action = target.querySelector<HTMLElement>('.generate-action');
		if (!action) throw new Error('Expected Generate action');
		expect(target.querySelectorAll('.generate-action')).toHaveLength(1);
		expect(action.textContent).toContain(cause);
		expect(target.querySelector('.takes-list')?.textContent ?? '').not.toContain(cause);
		expect(action.querySelectorAll('button')).toHaveLength(1);
		getByRoleButton(action, EDITOR_GENERATE_LABEL).click();
		await vi.waitFor(() =>
			expect(action.querySelector('[role="status"]')?.textContent).toContain('Queued')
		);
		expect(action.textContent).not.toContain(cause);
		expect(action.querySelector('[role="status"]')?.textContent).toContain('Queued');
	});

	it('shows a queued generation reason and its position from the job stream', async () => {
		activeJobs.set([
			{
				job: jobStatus({
					status: 'queued',
					queue_reason: 'Waiting for LoRA training on this GPU.',
					queue_position: 2
				}),
				songId: 's1'
			}
		]);
		const target = await renderView();

		expect(target.querySelector('.generate-action [role="status"]')?.textContent).toContain(
			'Queued #2'
		);
		expect(generateBtn(target)).toBeNull();
		expect(target.querySelector('.generate-action .reason')?.textContent).toBe(
			'Waiting for LoRA training on this GPU.'
		);
	});
});

describe('SongDetailView Generate double-click guard (#234)', () => {
	beforeEach(() => {
		recipeModel.set('turbo');
	});

	function generateBtn(target: HTMLElement): HTMLButtonElement {
		const btn = target.querySelector<HTMLButtonElement>('.generate-action .primary-button');
		if (!btn) throw new Error('Expected the Generate button');
		return btn;
	}

	// Red before the fix: onGenerate only set its guard from isGenerating,
	// which reads activeJobs — populated only once the POST's response comes
	// back and trackJob() runs. A second synchronous click before that
	// response landed a second POST. The fix sets a guard flag synchronously
	// before onGenerate's first await, closing that window.
	it('sends exactly one request when the button is clicked twice before the first response', async () => {
		let resolveGenerate: (job: JobItem) => void = () => {};
		generateSong.mockReturnValue(
			new Promise<JobItem>((resolve) => {
				resolveGenerate = resolve;
			})
		);
		const target = await renderView();
		const btn = generateBtn(target);

		btn.click();
		btn.click();
		await tick();

		expect(generateSong).toHaveBeenCalledTimes(1);

		resolveGenerate(jobStatus({ status: 'completed' }));
		await settleRender();
	});

	it('locks the button while the request is in flight, before any job exists', async () => {
		let resolveGenerate: (job: JobItem) => void = () => {};
		generateSong.mockReturnValue(
			new Promise<JobItem>((resolve) => {
				resolveGenerate = resolve;
			})
		);
		const target = await renderView();
		const btn = generateBtn(target);
		expect(btn.disabled).toBe(false);

		btn.click();
		await tick();

		expect(target.querySelector('.generate-action .primary-button')).toBeNull();
		expect(target.querySelector('.generate-action [role="status"]')?.textContent).toContain(
			EDITOR_GENERATING_LABEL
		);

		resolveGenerate(jobStatus({ status: 'completed' }));
		await settleRender();

		expect(generateBtn(target).disabled).toBe(false);
	});

	it('releases the guard after a successful response, letting the next click through', async () => {
		generateSong.mockResolvedValue(jobStatus({ status: 'completed' }));
		const target = await renderView();
		const btn = generateBtn(target);

		btn.click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(1));
		await tick();

		generateBtn(target).click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(2));
	});

	it('releases the guard after a failed response, letting a retry through', async () => {
		generateSong.mockRejectedValueOnce(new Error('boom'));
		const target = await renderView();
		const btn = generateBtn(target);

		btn.click();
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Generation failed', 'error'));

		generateSong.mockResolvedValueOnce(jobStatus({ status: 'completed' }));
		generateBtn(target).click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(2));
	});
});

describe('SongDetailView recipe line reads the draft', () => {
	it('keeps the changed dot after Save version (C4, #1935 acceptance 2)', async () => {
		const { updateSong } = await import('#lib/api/client.ts');
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), bpm: 145, version_count: 2 })
		);
		const target = await renderView();
		setDraftBpm(145);
		await tick();
		writeSaveButton(target).click();
		await vi.waitFor(() => expect(writeSaveButton(target).disabled).toBe(true));
		expect(target.querySelector('.recipe-line [data-recipe-changed]')).not.toBeNull();
	});
});

describe('SongDetailView unsaved-draft guard', () => {
	it('prompts before switching songs with a dirty draft; Cancel stays on the current song', async () => {
		const target = await renderWithDirtyDraft();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();

		expect(target.querySelector('.dialog h3')?.textContent).toBe(words['songPage.unsavedTitle']);
		expect(get(selectedSongId)).toBe('s1');

		clickNamed(target, 'Cancel');
		await tick();

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('Discard switches songs without saving', async () => {
		const target = await renderWithDirtyDraft();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();
		clickNamed(target, 'Discard');
		await tick();

		expect(get(selectedSongId)).toBe('s-last');
	});

	it('Save persists the draft as a new version, then switches songs', async () => {
		const { updateSong } = await import('#lib/api/client.ts');
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), lyrics: 'unsaved edit', version_count: 2 })
		);
		const target = await renderWithDirtyDraft();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();
		const dialog = target.querySelector<HTMLElement>('.dialog');
		if (!dialog) throw new Error('Expected the unsaved-changes dialog');
		clickNamed(dialog, words['songPage.unsavedSave']);

		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s-last'));
		expect(updateSong).toHaveBeenCalled();
	});

	it('keeps write-surface Save and the unsaved-changes confirm as distinct accessible names while the dialog is open', async () => {
		const target = await renderWithDirtyDraft();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();

		const dialog = target.querySelector<HTMLElement>('.dialog');
		if (!dialog) throw new Error('Expected the unsaved-changes dialog');

		const buttons = Array.from(target.querySelectorAll('button'));
		const named = (name: string) => buttons.filter((el) => accessibleName(el) === name);
		expect(named(words['songPage.unsavedSave'])).toHaveLength(1);
		expect(named(words['songPage.saveName'])).toHaveLength(1);
		expect(words['songPage.saveName']).not.toBe(words['songPage.unsavedSave']);
	});

	it('makes unsaved changes visible on the write surface before you hunt for them', async () => {
		const target = await renderView();
		const save = writeSaveButton(target);
		expect(save.disabled).toBe(true);
		expect(save.textContent?.trim()).toBe(words['songPage.save']);
		expect(target.querySelector('.write-save [role="status"]')?.textContent?.trim()).toBe('');
		expect(header(target).querySelector('.save-btn')).toBeNull();

		setDraftLyrics('unsaved edit');
		await tick();

		expect(save.disabled).toBe(false);
		expect(target.querySelector('.write-save [role="status"]')?.textContent?.trim()).toBe(
			words['songPage.unsavedTitle']
		);
	});

	it.each([false, true])('saves the draft from its visible action (phone: %s)', async (phone) => {
		stubLibraryMedia({ narrow: phone, compact: phone });
		const { updateSong } = await import('#lib/api/client.ts');
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), version_count: 2 })
		);
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		expect(target.querySelector('.menu-panel')).toBeNull();
		if (phone) {
			const bar = document.createElement('div');
			document.body.append(bar);
			mounted.push(mount(PhoneAppBar, { target: bar, props: PHONE_APP_BAR_PROPS }));
			await tick();
			bar.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
			await tick();
			clickNamed(bar, words['songMenu.save']);
		} else {
			writeSaveButton(target).click();
		}
		await settleRender();

		expect(updateSong).toHaveBeenCalled();
		expect(generateSong).not.toHaveBeenCalled();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('toasts the actual saved version number from the versions API response, not version_count', async () => {
		const { updateSong, fetchVersions } = await import('#lib/api/client.ts');
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), version_count: 2 })
		);
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		// Only override the *post-save* reload — the initial render already
		// consumed one fetchVersions() call while loading the song.
		vi.mocked(fetchVersions).mockResolvedValueOnce([
			version({
				lyrics: 'verse',
				prompt: 'dark folk',
				created_at: '2026-01-01T00:00:00+00:00',
				id: 'v5',
				version_number: 5
			})
		]);
		writeSaveButton(target).click();
		await settleRender();

		expect(addToast).toHaveBeenCalledWith(
			words['songPage.savedVersion']({ number: '5' }),
			'success'
		);
	});

	it.each([
		{ choice: 'Cancel', button: 'Cancel', saveFails: false, use: 'repaint' },
		{ choice: 'Cancel', button: 'Cancel', saveFails: false, use: 'seed' },
		{
			choice: 'a failed Save',
			button: words['songPage.unsavedSave'],
			saveFails: true,
			use: 'repaint'
		},
		{ choice: 'a failed Save', button: words['songPage.unsavedSave'], saveFails: true, use: 'seed' }
	] as const)(
		'C4: cross-song $use or Open vN: $choice leaves it unapplied, the seed unset, and drops what was pending',
		async ({ button, saveFails, use }) => {
			if (saveFails) {
				const { updateSong } = await import('#lib/api/client.ts');
				vi.mocked(updateSong).mockRejectedValueOnce(new Error('save failed'));
			}
			const target = await renderWithDirtyDraft();

			const targetGen = generation({
				...sourceRecipeDefaults(),
				id: 'g-last',
				song_id: 's-last'
			});
			pendingTakeUse.set({ generation: targetGen, use });
			pendingVersionLoad.set({ songId: 's-last', versionId: 'v-last' });
			selectSong(
				's-last',
				song({
					...editableSongDefaults(),
					id: 's-last',
					title: 'Last',
					generations: [targetGen]
				})
			);
			await tick();
			expect(get(sourceGeneration)).toBeNull();

			const dialog = target.querySelector<HTMLElement>('.dialog');
			if (!dialog) throw new Error('Expected the unsaved-changes dialog');
			clickNamed(dialog, button);

			await vi.waitFor(() => expect(get(pendingVersionLoad)).toBeNull());
			expect(get(selectedSongId)).toBe('s1');
			expect(get(pendingTakeUse)).toBeNull();
			expect(get(sourceGeneration)).toBeNull();
			expect(get(seedFromTake)).toBeNull();
		}
	);

	it('cross-song Repaint/Cover: Discard applies the source once the target song opens', async () => {
		const target = await renderWithDirtyDraft();

		const targetGen = generation({
			...sourceRecipeDefaults(),
			id: 'g-last',
			song_id: 's-last'
		});
		pendingTakeUse.set({ generation: targetGen, use: 'repaint' });
		selectSong(
			's-last',
			song({
				...editableSongDefaults(),
				id: 's-last',
				title: 'Last',
				generations: [targetGen]
			})
		);
		await tick();
		clickNamed(target, 'Discard');
		await tick();
		await tick();

		expect(get(selectedSongId)).toBe('s-last');
		expect(get(sourceGeneration)).toEqual(targetGen);
		expect(get(pendingTakeUse)).toBeNull();
	});
});

describe('SongDetailView Co-writer tab with the Recipe open', () => {
	it('shows the full recipe on the left and the chat on the right (S9, #1927 acceptance 8)', async () => {
		const target = await renderView();
		detailTab.set('cowriter');
		recipeOpen.set(true);
		await tick();

		expect(
			target.querySelector('.editor-columns > .write-column [role="region"][aria-label="Recipe"]')
		).not.toBeNull();
		expect(target.querySelector('.editor-columns > .listen-tabs .cowriter')).not.toBeNull();
	});
});

describe('SongDetailView phone Co-writer is a tab', () => {
	function showTab(target: HTMLElement, tab: DetailTab): void {
		const button = target.querySelector<HTMLButtonElement>(`[role="tab"][data-tab="${tab}"]`);
		if (!button) throw new Error(`Expected the ${tab} tab`);
		button.click();
	}

	it('opens under the song app bar and tabs, and hands the page back to Edit on its tab', async () => {
		openEditTab();
		stubLibraryMedia({ narrow: false, compact: true });
		const target = await renderView();
		const bar = document.createElement('div');
		document.body.append(bar);
		mounted.push(mount(PhoneAppBar, { target: bar, props: PHONE_APP_BAR_PROPS }));
		await tick();
		const songTitle = get(songList)[0].title;
		expect(target.querySelector('.cowriter')).toBeNull();

		showTab(target, 'cowriter');
		await tick();

		expect(target.querySelector('.write-surface')).toBeNull();
		expect(target.querySelectorAll('[role="tab"]')).toHaveLength(3);
		expect(target.querySelector('.cowriter')?.closest('[hidden]')).toBeNull();
		expect(get(phoneAppBar)?.title).toBe(songTitle);
		expect(bar.querySelector('h1')?.textContent?.trim()).toBe(songTitle);
		expect(bar.querySelector('[aria-label="Share song"]')).not.toBeNull();
		expect(bar.querySelector(`[aria-label="${words['songMenu.label']}"]`)).not.toBeNull();

		showTab(target, 'edit');
		await tick();

		expect(target.querySelector('.write-surface')).not.toBeNull();
		expect(target.querySelector('.cowriter')?.closest('[hidden]')).not.toBeNull();
	});

	it('keeps an unsent message while Edit and Takes are looked at', async () => {
		openEditTab();
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		showTab(target, 'cowriter');
		await tick();
		const composer = target.querySelector<HTMLTextAreaElement>('.cowriter textarea');
		if (!composer) throw new Error('Expected the co-writer composer');
		composer.value = 'tighten the chorus';
		composer.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		for (const tab of ['edit', 'takes', 'cowriter'] as const) {
			showTab(target, tab);
			await tick();
		}

		expect(target.querySelectorAll('.cowriter')).toHaveLength(1);
		expect(target.querySelector<HTMLTextAreaElement>('.cowriter textarea')?.value).toBe(
			'tighten the chorus'
		);
	});
});

describe('song header album rail', () => {
	function neighborButton(target: HTMLElement, key: 'songHeader.previous' | 'songHeader.next') {
		return target.querySelector<HTMLButtonElement>(`[aria-label="${words[key]}"]`);
	}

	beforeEach(() => {
		injectHitboxStyles();
	});

	it('hides previous/next when browse is shown', async () => {
		stubLibraryMedia({ narrow: false, compact: false });
		songList.set(albumSongs());
		const target = await renderView();
		expect(target.querySelector('.song-rail')).toBeNull();
		expect(neighborButton(target, 'songHeader.previous')).toBeNull();
		expect(neighborButton(target, 'songHeader.next')).toBeNull();
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs.slice(0, 2)).toEqual([words['places.library'], 'Local Album']);
	});

	it('shows one album line and disabled ends without wrapping through neighbors', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		songList.set(albumSongs());
		selectedSongId.set('s1');
		const target = await renderView();
		const prev = neighborButton(target, 'songHeader.previous');
		const next = neighborButton(target, 'songHeader.next');
		const albumLine = target.querySelector('.mobile-album-line');
		if (!prev || !next || !albumLine) throw new Error('Expected mobile album navigation');
		expect(albumLine.textContent).toContain('Local Album · 3 songs');
		expect(albumLine.querySelector('.album-line-cover')).not.toBeNull();
		expect(target.querySelector('.detail-header .breadcrumb')).toBeNull();
		expect(prev.disabled).toBe(false);
		expect(next.disabled).toBe(false);
		expect(prev.getAttribute('data-hitbox')).toBe('frequent');
		expect(next.getAttribute('data-hitbox')).toBe('frequent');
		expect(target.querySelector('.detail-header .crumb-link')).toBeNull();

		selectedSongId.set('s-first');
		await tick();
		expect(prev.disabled).toBe(true);
		expect(next.disabled).toBe(false);

		selectedSongId.set('s-last');
		await tick();
		expect(prev.disabled).toBe(false);
		expect(next.disabled).toBe(true);
	});

	it('keeps previous and next present and disabled on a one-song album', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		const target = await renderView();
		const prev = neighborButton(target, 'songHeader.previous');
		const next = neighborButton(target, 'songHeader.next');
		if (!prev || !next) throw new Error('Expected previous and next');
		expect(prev.disabled).toBe(true);
		expect(next.disabled).toBe(true);
	});

	it('replaces the song and keeps the Takes tab when next is clicked', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		const songs = albumSongs();
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		songList.set(songs);
		selectedSongId.set('s1');
		const cleanup = initNavigation();
		selectSong('s1');
		navigateToSongTab('takes');
		const before = { length: historyLength(), index: historyEntry().index };
		const target = await renderView();
		const next = neighborButton(target, 'songHeader.next');
		if (!next) throw new Error('Expected next');
		next.click();
		await tick();
		expect({ length: historyLength(), index: historyEntry().index }).toEqual(before);
		expect(get(selectedSongId)).toBe('s-last');
		expect(get(detailTab)).toBe('takes');
		cleanup();
	});

	it('keeps the album line inside a narrow desktop editor with a long album title', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		const longAlbumTitle =
			'The Unreasonably Long Anniversary Collection From the Other Side of the Harbor';
		songList.set(albumSongs().map((item) => ({ ...item, album_title: longAlbumTitle })));
		selectedSongId.set('s1');
		const target = await renderView({ widthPx: 320 });
		const headerEl = target.querySelector('.detail-header');
		const rail = target.querySelector('.mobile-album-line');
		const prev = neighborButton(target, 'songHeader.previous');
		const next = neighborButton(target, 'songHeader.next');
		if (!(headerEl instanceof HTMLElement) || !(rail instanceof HTMLElement) || !prev || !next) {
			throw new Error('Expected header song rail');
		}
		expect(rail.textContent).toContain(`${longAlbumTitle} · 3 songs`);
		expect(headerEl.scrollWidth).toBeLessThanOrEqual(320);
		expect(rail.scrollWidth).toBeLessThanOrEqual(320);
	});

	it('shows Library › Album › Track n of m as the breadcrumb', async () => {
		stubLibraryMedia({ narrow: false, compact: false });
		const songs = albumSongs();
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		songList.set(songs);
		selectedSongId.set('s1');
		const target = await renderView();
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs.slice(0, 2)).toEqual([words['places.library'], 'Local Album']);
		const position = songs.findIndex((s) => s.id === 's1') + 1;
		expect(crumbs[2]).toBe(
			words['songPage.trackOf']({ position: String(position), total: String(songs.length) })
		);
	});

	it('removes the album line and breadcrumbs on mobile', async () => {
		stubLibraryMedia({ narrow: true, compact: true });
		selectedAlbumId.set('a-local');
		selectSong('s1');
		const target = await renderView();
		expect(target.querySelector('.detail-header')).toBeNull();
		expect(target.querySelector('.mobile-album-line')).toBeNull();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedAlbumId)).toBe('a-local');
	});
});

function coverImages(coverPath: string, version: string) {
	return {
		card: `${coverPath}?variant=card&v=${version}`,
		detail: `${coverPath}?variant=detail&v=${version}`
	};
}

describe('SongDetailView cover hero', () => {
	it('inherits parent album cover and does not show remove', async () => {
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: coverImages('/api/albums/a-local/cover', 'album.jpg')
			})
		]);
		const target = await renderView();
		const img = target.querySelector<HTMLImageElement>('img');
		expect(img?.getAttribute('src')).toContain('/api/albums/a-local/cover?variant=detail');
		expect(img?.getAttribute('alt')).toBe(
			words['songPage.coverAltAlbum']({ title: 'Local Album' })
		);
		expect(target.querySelector('.cover-remove')).toBeNull();
		expect(target.querySelector<HTMLButtonElement>('.cover-hit')?.getAttribute('aria-label')).toBe(
			words['songPage.coverUpload']
		);
		expect(fetchAlbum).not.toHaveBeenCalled();
	});

	it('does not pick some other album when the parent is missing', async () => {
		albumList.set([
			album({
				song_count: 3,
				id: 'other-album',
				title: 'Other Album',
				cover: coverImages('/api/albums/other-album/cover', 'other.jpg')
			})
		]);
		fetchAlbum.mockResolvedValue(
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: coverImages('/api/albums/a-local/cover', 'parent.jpg')
			})
		);
		const target = await renderView();
		await vi.waitFor(() => expect(fetchAlbum).toHaveBeenCalledWith('a-local'));
		await vi.waitFor(() =>
			expect(target.querySelector('img')?.getAttribute('src')).toContain(
				'/api/albums/a-local/cover?variant=detail'
			)
		);
		expect(target.querySelector('img')?.getAttribute('src')).not.toContain('other-album');
		expect(target.querySelector('.cover-remove')).toBeNull();
	});

	it('shows own cover, song alt, and remove', async () => {
		songList.set([
			song({
				...editableSongDefaults(),
				cover: coverImages('/api/songs/s1/cover', 'own.jpg')
			})
		]);
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: coverImages('/api/albums/a-local/cover', 'album.jpg')
			})
		]);
		const target = await renderView();
		const img = target.querySelector<HTMLImageElement>('img');
		expect(img?.getAttribute('src')).toContain('/api/songs/s1/cover?variant=detail');
		expect(img?.getAttribute('alt')).toBe(words['songPage.coverAlt']({ title: 'Local Only' }));
		expect(
			target.querySelector<HTMLButtonElement>('.cover-remove')?.getAttribute('aria-label')
		).toBe(words['songHeader.removeCover']);
		expect(target.querySelector<HTMLButtonElement>('.cover-hit')?.getAttribute('aria-label')).toBe(
			words['songPage.coverReplace']
		);
	});

	it('uploads a song override', async () => {
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		uploadSongCover.mockResolvedValue(
			song({
				...editableSongDefaults(),
				cover: coverImages('/api/songs/s1/cover', 'new.jpg')
			})
		);
		const target = await renderView();
		const input = target.querySelector('.cover-file-input');
		expect(input).toBeInstanceOf(HTMLInputElement);
		if (!(input instanceof HTMLInputElement)) return;
		const file = new File([new Uint8Array([1, 2, 3])], 'cover.jpg', { type: 'image/jpeg' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadSongCover).toHaveBeenCalledTimes(1));
		await tick();
		expect(target.querySelector('img')?.getAttribute('src')).toContain('/api/songs/s1/cover');
		expect(target.querySelector('.cover-remove')).not.toBeNull();
	});

	it('removes only the own cover and then inherits the parent album', async () => {
		songList.set([
			song({
				...editableSongDefaults(),
				cover: coverImages('/api/songs/s1/cover', 'own.jpg')
			})
		]);
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: coverImages('/api/albums/a-local/cover', 'album.jpg')
			})
		]);
		deleteSongCover.mockResolvedValue(song({ ...editableSongDefaults(), cover: null }));
		const target = await renderView();
		expect(target.querySelector('img')?.getAttribute('src')).toContain('/api/songs/s1/cover');
		target.querySelector<HTMLButtonElement>('.cover-remove')?.click();
		await vi.waitFor(() => expect(deleteSongCover).toHaveBeenCalledTimes(1));
		expect(deleteAlbumCover).not.toHaveBeenCalled();
		await tick();
		expect(target.querySelector('img')?.getAttribute('src')).toContain(
			'/api/albums/a-local/cover?variant=detail'
		);
		expect(target.querySelector('.cover-remove')).toBeNull();
	});
});

describe('the editor answers to its own width, not the viewport', () => {
	// jsdom computes no layout, so these pin the stylesheet; the browser gate
	// on #185 — 1100 and 1280 with Now Playing docked — is the real proof.
	it('makes the body under the header the size container its columns query', () => {
		expect(songDetailViewSource).toMatch(/\.editor-body \{[^}]*container: editor \/ size;/);
		// Header and shared-link line stay outside it: it contains fixed overlays and sizes the Co-writer column.
		expect(songDetailViewSource).not.toMatch(/\.detail-panel \{[^}]*container:/);
		expect(songDetailViewSource).toMatch(/\{@render sharedLink\(\)\}\s*<div class="editor-body">/);
	});

	it('stacks Write and Takes until the editor itself has room for both', () => {
		expect(songDetailViewSource).toMatch(
			/\.editor-columns \{[^}]*grid-template-columns: minmax\(0, 1fr\);/
		);
		expect(songDetailViewSource).toMatch(
			/@container editor \(min-width: 680px\) \{\s*\.editor-columns \{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/
		);
		// No track with a pixel floor of its own — the takes column's 360px
		// was what pushed a take row's actions outside `main`.
		expect(songDetailViewSource).not.toMatch(/minmax\(\d+px/);
	});

	it('scrolls the body under the header rather than clipping a stacked column', () => {
		expect(songDetailViewSource).toMatch(
			/\.detail-panel:not\(\.compact\) \.editor-body \{[^}]*overflow: hidden auto;/
		);
		expect(songDetailViewSource).not.toMatch(/\n\t\.editor-body \{[^}]*overflow:/);
	});

	it('asks the viewport nothing but whether the shell is compact', () => {
		const editorStylesheets = {
			SongDetailView: songDetailViewSource,
			EditorHeader: editorHeaderSource,
			RecipeLine: recipeLineSource,
			RecipeTabs: recipeTabsSource,
			TakesList: takesListSource,
			WriteColumn: writeColumnSource
		};
		for (const [component, source] of Object.entries(editorStylesheets)) {
			const widthQueries = source.match(/@media \([^)]*width[^)]*\)/g) ?? [];
			expect(widthQueries, component).toEqual(
				widthQueries.map(() => `@media (max-width: ${COMPACT_LAYOUT_MAX_PX}px)`)
			);
		}
	});
});
