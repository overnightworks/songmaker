import { historyEntry, historyLength } from '$lib/test-utils/library-history';
import {
	makeAlbum as album,
	makeGeneration as generation,
	makeHealthResponse,
	makeSong as song,
	makeVersion as version
} from '$lib/test-utils/factories';
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { phoneAppBar } from '$lib/stores/ui';
import PhoneAppBar from './PhoneAppBar.svelte';

import type { GenerationItem, JobItem, SongItem } from '$lib/api/types';
import {
	ALBUM_COVER_ALT_TYPE,
	COMPACT_LAYOUT_MAX_PX,
	COMPACT_LAYOUT_MEDIA,
	EDITOR_GENERATE_LABEL,
	EDITOR_GENERATING_LABEL,
	EDITOR_SAVE_ACCESSIBLE_LABEL,
	EDITOR_SAVE_FAILED,
	EDITOR_SAVE_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	EDITOR_UNSAVED_TITLE,
	EDITOR_VIEW_COWRITER_LABEL,
	RECIPE_PANEL_LABEL,
	LIBRARY_NARROW_MEDIA,
	SONG_COVER_ALT_TYPE,
	SONG_COVER_REMOVE_LABEL,
	SONG_COVER_REPLACE_LABEL,
	SONG_COVER_UPLOAD_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL,
	TAKE_REPAINT_LABEL,
	TAKE_COVER_LABEL,
	TAKE_PLAYLIST_LABEL,
	TAKES_ERROR,
	TAKES_LOADING,
	TAKES_RETRY_LABEL,
	DIALOG_CANCEL_LABEL,
	TOAST_UNDO_LABEL,
	VERSION_DELETE_CONFIRM_LABEL,
	VERSION_DELETE_DRAFT_GOES,
	VERSION_DELETE_EMPTIES_EDITOR,
	VERSION_DELETE_LOAD_UNDO_GOES,
	VERSION_REPLACE_DRAFT_CONFIRM_LABEL,
	VERSION_REPLACE_DRAFT_TITLE,
	VERSIONS_SHEET_LABEL,
	versionDeleteLabel,
	versionDeleteTitle,
	versionLoadedFromLabel,
	versionLoadedToastLabel,
	versionReplaceDraftMessage
} from '$lib/constants';
import { accessibleName, getByRoleButton } from '$lib/test-utils/accessible-name';
import { menuRow } from '$lib/test-utils/collection-menu';
import { clearHitboxStyles, clearPointer, injectHitboxStyles } from '$lib/test-utils/hitbox';
import { PHONE_APP_BAR_PROPS } from '$lib/test-utils/phone-app-bar';
import {
	discardDraft,
	editLyrics,
	pendingVersionLoad,
	versionDeleteRequest,
	setDraftBpm,
	setDraftLyrics,
	loadVersionAsDraft,
	setDraftPrompt,
	versions
} from '$lib/stores/editor';
import { openVersionLabel } from '$lib/constants/now-playing';
import { activeJobs, generationFailures } from '$lib/stores/jobs';
import {
	detailTab,
	type DetailTab,
	initNavigation,
	navigateToSongTab,
	persistLibraryHistory,
	resetNavigationForTests,
	selectSong,
	openEditTab
} from '$lib/stores/navigation';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { clearSelection, toggleSelection } from '$lib/stores/selection';
import {
	pendingTakeUse,
	recipeModel,
	seedFromTake,
	recipeOpen,
	setSourceFromGeneration,
	sourceGeneration,
	sourceMode
} from '$lib/stores/recipe';

const fetchAlbum = vi.fn();
const uploadSongCover = vi.fn();
const deleteSongCover = vi.fn();
const deleteAlbumCover = vi.fn();
const fetchHealth = vi.fn();
const generateSong = vi.fn();
const listLoras = vi.fn();

// Stands in for the router the way the real one behaves for this app (issue
// #275): a song selection can now cross from the wall's `/` into the song's
// own `/album/<slug>/<song-slug>` address, which writeLibraryHistory sends
// through `goto` -- unmocked, that call needs a live SvelteKit router this
// harness never mounts.
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: vi.fn()
}));
vi.mock('$lib/api/loras', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/loras')>();
	return { ...actual, listLoras: (...args: unknown[]) => listLoras(...args) };
});
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi.fn()
}));
vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchVersions: vi.fn().mockResolvedValue([]),
		fetchHealth: (...args: unknown[]) => fetchHealth(...args),
		fetchSong: vi.fn(async (id: string) => ({
			id,
			title: 'Local Only',
			album_id: 'a-local',
			album_title: 'Local Album',
			artist: 'Artist',
			track_number: 1,
			vocal_language: 'en',
			lyrics: 'verse',
			prompt: 'dark folk',
			bpm: 120,
			audio_duration: 180,
			key_scale: 'Am',
			generation_params: null,
			version_count: 1,
			generation_count: 0,
			best_scores: null,
			best_rating: null,
			generations: [],
			created_at: '2026-01-01T00:00:00+00:00',
			is_shared: false,
			share_slug: null
		})),
		fetchSongs: vi.fn().mockResolvedValue({
			items: [],
			total: 0,
			offset: 0,
			limit: 200,
			has_more: false
		}),
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ tail_token_budget: 24000, model: '' }),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
		fetchActiveModels: vi.fn().mockResolvedValue([]),
		fetchPresets: vi.fn().mockResolvedValue([]),
		fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
		bulkDeleteGenerations: vi.fn().mockResolvedValue({ deleted: 1 }),
		uploadSongCover: (...args: unknown[]) => uploadSongCover(...args),
		deleteSongCover: (...args: unknown[]) => deleteSongCover(...args),
		deleteAlbumCover: (...args: unknown[]) => deleteAlbumCover(...args),
		generateSong: (...args: unknown[]) => generateSong(...args),
		updateSong: vi.fn(),
		renameSong: vi.fn(),
		deleteSong: vi.fn(),
		deleteVersion: vi.fn(),
		deleteGeneration: vi.fn().mockResolvedValue(undefined),
		addGenerationToPlaylist: vi.fn().mockResolvedValue(undefined),
		fetchPlaylists: vi.fn().mockResolvedValue([])
	};
});
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

import SongDetailView from './SongDetailView.svelte';
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
} from '$lib/api/client';
import { ApiError, NetworkError } from '$lib/api/fetch';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import { addToast, addUndoToast } from '$lib/stores/toast';
import { loras } from '$lib/stores/loras';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';

function sourceRecipeDefaults(): Partial<GenerationItem> {
	return { generation_params: { inference_steps: 8, guidance_scale: 1.5 } };
}

function editableSongDefaults(): Partial<SongItem> {
	return {
		album_id: 'a-local',
		album_title: 'Local Album',
		lyrics: 'verse',
		prompt: 'dark folk',
		generations: [generation(sourceRecipeDefaults())]
	};
}

const mounted: Array<ReturnType<typeof mount>> = [];

function jobStatus(overrides: Partial<JobItem> = {}): JobItem {
	return {
		id: 'job1',
		type: 'generate',
		status: 'completed',
		progress: 1,
		...overrides
	};
}

// trackJob() opens a real EventSource once a generate call resolves; jsdom
// ships none, so a click that lets its promise settle needs a stand-in.
class MockEventSource {
	closed = false;
	close(): void {
		this.closed = true;
	}
}

async function renderView(options: { widthPx?: number } = {}): Promise<HTMLElement> {
	const target = document.createElement('div');
	if (options.widthPx !== undefined) {
		target.style.width = `${options.widthPx}px`;
		target.style.maxWidth = `${options.widthPx}px`;
	}
	document.body.append(target);
	mounted.push(mount(SongDetailView, { target }));
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

function header(target: HTMLElement): HTMLElement {
	const el = target.querySelector<HTMLElement>('.detail-header');
	if (!el) throw new Error('Expected the Editor header row');
	return el;
}

function writeSaveButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.write-save .save-btn');
	if (!button) throw new Error('Expected the write-surface Save button');
	return button;
}

function visibleText(el: HTMLElement): string {
	return (el.textContent ?? '').replace(/\s+/g, ' ');
}

function clickNamed(target: HTMLElement, name: string): void {
	const button = Array.from(target.querySelectorAll('button')).find(
		(el) => el.textContent?.replace(/\s+/g, ' ').trim() === name
	);
	if (!button) throw new Error(`Expected button "${name}"`);
	button.click();
}

function stubLibraryMedia(options: { narrow: boolean; compact?: boolean }): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches:
				query === LIBRARY_NARROW_MEDIA
					? options.narrow
					: query === COMPACT_LAYOUT_MEDIA
						? (options.compact ?? options.narrow)
						: false,
			media: query,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

function albumSongs(): SongItem[] {
	return [
		song({ ...editableSongDefaults(), id: 's-first', title: 'First' }),
		song({ ...editableSongDefaults(), track_number: 2 }),
		song({ ...editableSongDefaults(), id: 's-last', title: 'Last', track_number: 3 })
	];
}

beforeEach(() => {
	Element.prototype.scrollIntoView = vi.fn();
	// defect:#1598: a background load preserves dirty drafts; reset through the owner.
	discardDraft();
	resetNavigationForTests();
	pendingTakeUse.set(null);
	seedFromTake.set(null);
	recipeOpen.set(false);
	recipeModel.set(null);
	clearSelection();
	songList.set([song(editableSongDefaults())]);
	selectedSongId.set('s1');
	selectedGenerationId.set(null);
	fetchAlbum.mockReset();
	fetchAlbum.mockResolvedValue(album({ id: 'a-local', title: 'Local Album', song_count: 3 }));
	playlistList.set([
		{
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addGenerationToPlaylist).mockClear();
	uploadSongCover.mockReset();
	deleteSongCover.mockReset();
	deleteAlbumCover.mockReset();
	fetchHealth.mockReset();
	fetchHealth.mockResolvedValue(makeHealthResponse());
	generateSong.mockReset();
	listLoras.mockReset();
	listLoras.mockResolvedValue([]);
	loras.set([]);
	activeJobs.set([]);
	generationFailures.set({});
	vi.stubGlobal('EventSource', MockEventSource);
	vi.mocked(addToast).mockClear();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetNavigationForTests();
	pendingVersionLoad.set(null);
	versionDeleteRequest.set(null);
	recipeOpen.set(false);
	clearSelection();
	selectedSongId.set(null);
	selectedAlbumId.set(null);
	songList.set([]);
	albumList.set([]);
	clearHitboxStyles();
	clearPointer();
	resetConnectivityForTests();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('SongDetailView header — one row, every state', () => {
	it('shows Generate alone, no Recipe toggle or Co-writer button, never a second toolbar row (C4, #1935 acceptance 6)', async () => {
		const target = await renderView();
		const actions = header(target).querySelector<HTMLElement>('.editor-header-actions');
		if (!actions) throw new Error('Expected header actions');
		expect(visibleText(actions)).not.toContain(EDITOR_VIEW_COWRITER_LABEL);
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
	it('shows a copy-link chip instead of the raw share URL when the song is shared', async () => {
		songList.set([song({ ...editableSongDefaults(), is_shared: true, share_slug: 'abc123' })]);
		const target = await renderView();

		const chip = target.querySelector<HTMLButtonElement>('.share-link-chip');
		expect(chip).not.toBeNull();
		expect(chip?.textContent?.trim()).toBe('Copy link');
		expect(chip?.title).toBe(`${window.location.origin}/share/song/abc123`);
		expect(target.textContent).not.toContain(`${window.location.origin}/share/song/abc123`);
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
			'Takes 1',
			'Co-writer'
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
			(button) => button.textContent?.trim() === 'Save version'
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
			'Edit',
			'Co-writer',
			'Takes (1)'
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
		menuRow(row, TAKE_PLAYLIST_LABEL).click();
		await tick();
		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		// The picker closes once the add has fully settled, toast included.
		await vi.waitFor(() => expect(row.querySelector('.picker')).toBeNull());

		expect(addGenerationToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(vi.mocked(addToast).mock.calls).toEqual([['Added to playlist', 'success']]);
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
			fallback: 'Rename failed',
			fail: (error: Error) => vi.mocked(renameSong).mockRejectedValueOnce(error),
			run: () =>
				appBar()
					.onrename('New title')
					.catch(() => undefined)
		},
		{
			action: 'uploading a cover',
			fallback: 'Cover upload failed',
			fail: (error: Error) => uploadSongCover.mockRejectedValueOnce(error),
			run: (target: HTMLElement) => chooseCoverFile(target)
		},
		{
			action: 'removing the cover',
			fallback: 'Cover remove failed',
			ownCover: true,
			fail: (error: Error) => deleteSongCover.mockRejectedValueOnce(error),
			run: (target: HTMLElement) =>
				target.querySelector<HTMLButtonElement>('.cover-remove')?.click()
		},
		{
			action: 'saving a version',
			fallback: EDITOR_SAVE_FAILED,
			fail: (error: Error) => vi.mocked(updateSong).mockRejectedValueOnce(error),
			run: () => appBar().menu.onsave()
		},
		{
			action: 'deleting a version from its Versions row',
			fallback: 'Delete failed',
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
				getByRoleButton(document.body, versionDeleteLabel(1)).click();
				await tick();
				document.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
			}
		},
		{
			action: 'deleting the song',
			fallback: 'Delete failed',
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
	async function settleTakesLoad(): Promise<void> {
		await tick();
		await Promise.resolve();
		await tick();
	}

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
		await settleTakesLoad();
		expect(target.querySelectorAll('.take-row')).toHaveLength(1);
		expect(target.textContent).not.toContain(TAKES_ERROR);
		expect(target.textContent).not.toContain('Failed to fetch');
		expect(target.querySelector('.takes-list [role="alert"]')).toBeNull();
	});

	it('names the takes failure with Try again when a load gets no network answer while the page counts as online', async () => {
		takesWithNoNetworkAnswer();
		songList.set([song({ ...editableSongDefaults(), generation_count: 2 })]);
		const target = await renderView();
		await settleTakesLoad();
		const alert = target.querySelector('.takes-list [role="alert"]') as HTMLElement;
		expect(alert.textContent).toContain(TAKES_ERROR);
		expect(getByRoleButton(alert, TAKES_RETRY_LABEL)).toBeTruthy();
	});

	it('waits for the takes offline and reloads them by itself once the page is back online', async () => {
		reportResourceStreamReachable(false);
		takesWithNoNetworkAnswer();
		songList.set([song({ ...editableSongDefaults(), generation_count: 2, generations: [] })]);
		const target = await renderView();
		await settleTakesLoad();
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
			await settleTakesLoad();
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
			clickNamed(target, mode === 'repaint' ? TAKE_REPAINT_LABEL : TAKE_COVER_LABEL);
			await tick();
			expect(get(recipeOpen)).toBe(false);
			expect(get(sourceMode)).toBe(mode);
			expect(get(sourceGeneration)?.id).toBe('g1');
			expect(target.querySelector('.take-row + .task')).not.toBeNull();
			expect(target.querySelector('[role="dialog"]')).toBeNull();
		}
	);

	it.each(['Cancel', 'Delete'])('asks once before take deletion and honors %s', async (choice) => {
		const { deleteGeneration } = await import('$lib/api/client');
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

	it('keeps Generate pressable with no reason when no ACE-Step worker is online', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ acestep_workers_online: 0 }));
		const target = await renderView();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(false);
		expect(btn?.title).toBe('');
		expect(target.querySelector('.generate-action .reason')).toBeNull();
		expect(btn?.textContent).toContain(EDITOR_GENERATE_LABEL);
	});

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
		await tick();
		await Promise.resolve();
		await tick();
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
		await tick();
		await Promise.resolve();
		await tick();

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
		const { updateSong } = await import('$lib/api/client');
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
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();

		expect(target.querySelector('.dialog h3')?.textContent).toBe(EDITOR_UNSAVED_TITLE);
		expect(get(selectedSongId)).toBe('s1');

		clickNamed(target, 'Cancel');
		await tick();

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('Discard switches songs without saving', async () => {
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();
		clickNamed(target, 'Discard');
		await tick();

		expect(get(selectedSongId)).toBe('s-last');
	});

	it('Save persists the draft as a new version, then switches songs', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), lyrics: 'unsaved edit', version_count: 2 })
		);
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();
		const dialog = target.querySelector<HTMLElement>('.dialog');
		if (!dialog) throw new Error('Expected the unsaved-changes dialog');
		clickNamed(dialog, EDITOR_UNSAVED_SAVE_LABEL);

		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s-last'));
		expect(updateSong).toHaveBeenCalled();
	});

	it('keeps write-surface Save and the unsaved-changes confirm as distinct accessible names while the dialog is open', async () => {
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		selectSong('s-last', song({ ...editableSongDefaults(), id: 's-last', title: 'Last' }));
		await tick();

		const dialog = target.querySelector<HTMLElement>('.dialog');
		if (!dialog) throw new Error('Expected the unsaved-changes dialog');

		const buttons = Array.from(target.querySelectorAll('button'));
		expect(buttons.filter((el) => accessibleName(el) === EDITOR_UNSAVED_SAVE_LABEL)).toHaveLength(
			1
		);
		expect(
			buttons.filter((el) => accessibleName(el) === EDITOR_SAVE_ACCESSIBLE_LABEL)
		).toHaveLength(1);
		expect(EDITOR_SAVE_ACCESSIBLE_LABEL).not.toBe(EDITOR_UNSAVED_SAVE_LABEL);
	});

	it('makes unsaved changes visible on the write surface before you hunt for them', async () => {
		const target = await renderView();
		const save = writeSaveButton(target);
		expect(save.disabled).toBe(true);
		expect(save.textContent?.trim()).toBe(EDITOR_SAVE_LABEL);
		expect(target.querySelector('.write-save [role="status"]')?.textContent?.trim()).toBe('');
		expect(header(target).querySelector('.save-btn')).toBeNull();

		setDraftLyrics('unsaved edit');
		await tick();

		expect(save.disabled).toBe(false);
		expect(target.querySelector('.write-save [role="status"]')?.textContent?.trim()).toBe(
			EDITOR_UNSAVED_TITLE
		);
	});

	it.each([false, true])('saves the draft from its visible action (phone: %s)', async (phone) => {
		stubLibraryMedia({ narrow: phone, compact: phone });
		const { updateSong } = await import('$lib/api/client');
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
			clickNamed(bar, 'Save version');
		} else {
			writeSaveButton(target).click();
		}
		await tick();
		await Promise.resolve();
		await tick();

		expect(updateSong).toHaveBeenCalled();
		expect(generateSong).not.toHaveBeenCalled();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('toasts the actual saved version number from the versions API response, not version_count', async () => {
		const { updateSong, fetchVersions } = await import('$lib/api/client');
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
		await tick();
		await Promise.resolve();
		await tick();

		expect(addToast).toHaveBeenCalledWith('Saved version 5', 'success');
	});

	it.each([
		{ choice: 'Cancel', button: 'Cancel', saveFails: false, use: 'repaint' },
		{ choice: 'Cancel', button: 'Cancel', saveFails: false, use: 'seed' },
		{ choice: 'a failed Save', button: EDITOR_UNSAVED_SAVE_LABEL, saveFails: true, use: 'repaint' },
		{ choice: 'a failed Save', button: EDITOR_UNSAVED_SAVE_LABEL, saveFails: true, use: 'seed' }
	] as const)(
		'C4: cross-song $use or Open vN: $choice leaves it unapplied, the seed unset, and drops what was pending',
		async ({ button, saveFails, use }) => {
			if (saveFails) {
				const { updateSong } = await import('$lib/api/client');
				vi.mocked(updateSong).mockRejectedValueOnce(new Error('save failed'));
			}
			songList.set(albumSongs());
			const target = await renderView();
			setDraftLyrics('unsaved edit');
			await tick();

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
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

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
		expect(bar.querySelector('[aria-label="Song menu"]')).not.toBeNull();

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
	beforeEach(() => {
		injectHitboxStyles();
	});

	it('hides previous/next when browse is shown', async () => {
		stubLibraryMedia({ narrow: false, compact: false });
		songList.set(albumSongs());
		const target = await renderView();
		expect(target.querySelector('.song-rail')).toBeNull();
		expect(target.querySelector(`[aria-label="${SONG_PREVIOUS_LABEL}"]`)).toBeNull();
		expect(target.querySelector(`[aria-label="${SONG_NEXT_LABEL}"]`)).toBeNull();
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs[0]).toBe('Library');
		expect(crumbs[1]).toBe('Local Album');
	});

	it('shows one album line and disabled ends without wrapping through neighbors', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		songList.set(albumSongs());
		selectedSongId.set('s1');
		const target = await renderView();
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
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
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
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
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
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
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
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
		expect(crumbs[0]).toBe('Library');
		expect(crumbs[1]).toBe('Local Album');
		expect(crumbs[2]).toBe(`Track ${songs.findIndex((s) => s.id === 's1') + 1} of ${songs.length}`);
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

describe('SongDetailView cover hero', () => {
	it('inherits parent album cover and does not show remove', async () => {
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=album.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=album.jpg'
				}
			})
		]);
		const target = await renderView();
		const img = target.querySelector<HTMLImageElement>('img');
		expect(img?.getAttribute('src')).toContain('/api/albums/a-local/cover?variant=detail');
		expect(img?.getAttribute('alt')).toBe(`${ALBUM_COVER_ALT_TYPE} Local Album`);
		expect(target.querySelector('.cover-remove')).toBeNull();
		expect(target.querySelector<HTMLButtonElement>('.cover-hit')?.getAttribute('aria-label')).toBe(
			SONG_COVER_UPLOAD_LABEL
		);
		expect(fetchAlbum).not.toHaveBeenCalled();
	});

	it('does not pick some other album when the parent is missing', async () => {
		albumList.set([
			album({
				song_count: 3,
				id: 'other-album',
				title: 'Other Album',
				cover: {
					card: '/api/albums/other-album/cover?variant=card&v=other.jpg',
					detail: '/api/albums/other-album/cover?variant=detail&v=other.jpg'
				}
			})
		]);
		fetchAlbum.mockResolvedValue(
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=parent.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=parent.jpg'
				}
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
				cover: {
					card: '/api/songs/s1/cover?variant=card&v=own.jpg',
					detail: '/api/songs/s1/cover?variant=detail&v=own.jpg'
				}
			})
		]);
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=album.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=album.jpg'
				}
			})
		]);
		const target = await renderView();
		const img = target.querySelector<HTMLImageElement>('img');
		expect(img?.getAttribute('src')).toContain('/api/songs/s1/cover?variant=detail');
		expect(img?.getAttribute('alt')).toBe(`${SONG_COVER_ALT_TYPE} Local Only`);
		expect(
			target.querySelector<HTMLButtonElement>('.cover-remove')?.getAttribute('aria-label')
		).toBe(SONG_COVER_REMOVE_LABEL);
		expect(target.querySelector<HTMLButtonElement>('.cover-hit')?.getAttribute('aria-label')).toBe(
			SONG_COVER_REPLACE_LABEL
		);
	});

	it('uploads a song override', async () => {
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		uploadSongCover.mockResolvedValue(
			song({
				...editableSongDefaults(),
				cover: {
					card: '/api/songs/s1/cover?variant=card&v=new.jpg',
					detail: '/api/songs/s1/cover?variant=detail&v=new.jpg'
				}
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
				cover: {
					card: '/api/songs/s1/cover?variant=card&v=own.jpg',
					detail: '/api/songs/s1/cover?variant=detail&v=own.jpg'
				}
			})
		]);
		albumList.set([
			album({
				id: 'a-local',
				title: 'Local Album',
				song_count: 3,
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=album.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=album.jpg'
				}
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
		// The header is deliberately left outside it: a size container is also
		// the containing block for the fixed overlays the header carries.
		expect(songDetailViewSource).not.toMatch(/\.detail-panel \{[^}]*container:/);
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
		const { fetchVersions } = await import('$lib/api/client');
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

	function shownToasts(): Promise<typeof import('$lib/stores/toast')> {
		return vi.importActual<typeof import('$lib/stores/toast')>('$lib/stores/toast');
	}

	function versionChip(target: HTMLElement): HTMLButtonElement {
		const chip = target.querySelector<HTMLButtonElement>('.version-chip');
		if (!chip) throw new Error('Expected the version chip');
		return chip;
	}

	function versionsSheet(): HTMLElement | null {
		return document.querySelector<HTMLElement>(
			`[role="dialog"][aria-label="${VERSIONS_SHEET_LABEL}"]`
		);
	}

	function replaceDialog(): HTMLElement | null {
		return document.querySelector<HTMLElement>(
			`[role="dialog"][aria-label="${VERSION_REPLACE_DRAFT_TITLE}"]`
		);
	}

	async function tapVersion(target: HTMLElement, versionNumber: number): Promise<void> {
		await vi.waitFor(() => expect(versionChip(target).textContent).toContain('v2'));
		versionChip(target).click();
		await tick();
		const row = Array.from(document.querySelectorAll<HTMLButtonElement>('.version-row')).find(
			(el) => el.textContent?.trim().startsWith(`v${versionNumber}`)
		);
		if (!row) throw new Error(`Expected the v${versionNumber} row`);
		row.click();
		await tick();
		await Promise.resolve();
		await tick();
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
		expect(versionChip(target).textContent?.trim()).toBe('v2 · draft');
		expect(target.textContent).toContain(versionLoadedFromLabel(1));
		expect(addUndoToast).toHaveBeenCalledWith(
			versionLoadedToastLabel(1),
			expect.objectContaining({ label: TOAST_UNDO_LABEL }),
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

			expect(statusLine()).toBe('Unsaved changes');
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
		named('.version-link', openVersionLabel(n))?.click();
		await tick();
		await Promise.resolve();
		await tick();
	}

	it('Open v1 on a take group loads v1 as the draft and shows it on Edit', async () => {
		navigateToSongTab('takes');
		const target = await renderView();
		await vi.waitFor(() => expect(get(versions)).toHaveLength(2));

		await openFromTakeGroup(target, 1);

		expect(target.querySelector<HTMLTextAreaElement>('.lyrics-area')?.value).toBe('first draft');
		expect(versionChip(target).textContent?.trim()).toBe('v2 · draft');
		expect(target.textContent).toContain(versionLoadedFromLabel(1));
		expect(addUndoToast).toHaveBeenCalledWith(
			versionLoadedToastLabel(1),
			expect.objectContaining({ label: TOAST_UNDO_LABEL }),
			'brief'
		);
	});

	it('Open on the clean current version answers: "v2 is already the draft" and the focus moves to the lyrics', async () => {
		const takeOfV2 = generation({ ...sourceRecipeDefaults(), version_id: 'v2', version_number: 2 });
		songList.set([song({ ...editableSongDefaults(), generations: [takeOfV2] })]);
		navigateToSongTab('takes');
		const target = await renderView();
		await vi.waitFor(() => expect(get(versions)).toHaveLength(2));

		await openFromTakeGroup(target, 2);
		await vi.waitFor(() =>
			expect(document.activeElement).toBe(target.querySelector('textarea.lyrics-area'))
		);

		expect(addToast).toHaveBeenCalledWith('v2 is already the draft', 'info');
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
		expect(versionChip(target).textContent?.trim()).toBe('v2 · draft');
		expect(target.textContent).toContain(versionLoadedFromLabel(1));
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
		expect(dialog.textContent).toContain(versionReplaceDraftMessage(1));
		expect(get(editLyrics)).toBe('unsaved edit');
		expect(target.textContent).not.toContain(versionLoadedFromLabel(1));
	});

	it('over a dirty draft asks first, and Cancel keeps the edit and the sheet', async () => {
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();
		await tapVersion(target, 1);

		const dialog = replaceDialog();
		if (!dialog) throw new Error('Expected the replace-draft confirm');
		expect(dialog.textContent).toContain(versionReplaceDraftMessage(1));
		clickNamed(dialog, DIALOG_CANCEL_LABEL);
		await tick();
		await Promise.resolve();
		await tick();

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
		clickNamed(dialog, VERSION_REPLACE_DRAFT_CONFIRM_LABEL);
		await tick();
		await Promise.resolve();
		await tick();
	}

	it('Replace loads the version, and Undo brings the replaced edit back', async () => {
		const target = await renderView();
		await replaceTypedDraftWith(target, 1);

		expect(versionsSheet()).toBeNull();
		expect(get(editLyrics)).toBe('first draft');

		undoLastLoad();
		await tick();
		expect(get(editLyrics)).toBe('unsaved edit');
		expect(target.textContent).not.toContain(versionLoadedFromLabel(1));
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
			expect(loaded?.message).toBe(versionLoadedToastLabel(1));
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
		expect(loaded?.message).toBe(versionLoadedToastLabel(1));
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
		await tick();
		await Promise.resolve();
		await tick();

		const { toasts } = await shownToasts();
		expect(get(toasts).map((toast) => toast.message)).toEqual([versionLoadedToastLabel(1)]);
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
		expect(get(toasts).map((toast) => toast.message)).toEqual([versionLoadedToastLabel(2)]);
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
		clickNamed(dialog, VERSION_REPLACE_DRAFT_CONFIRM_LABEL);
		await tick();

		expect(get(editLyrics)).toBe('verse');
		expect(versionChip(target).textContent?.trim()).toBe('v2');
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
			`button[aria-label="${versionDeleteLabel(versionNumber)}"]`
		);
		if (!trash) throw new Error(`Expected the delete on the v${versionNumber} row`);
		trash.click();
		await tick();
	}

	function deleteConfirm(): HTMLElement | null {
		return (
			Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).find((dialog) =>
				dialog.querySelector('h3')?.textContent?.startsWith('Delete v')
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
		{ takes: 1, picked: false, shown: ['Delete v1 and its 1 take?'] },
		{ takes: 1, picked: true, shown: [versionDeleteTitle(1, 1), 'It is the album pick.'] },
		{ takes: 2, picked: true, shown: [versionDeleteTitle(1, 2), 'The album pick is one of them.'] }
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
			expect(versionRowNumbers()).toEqual(['v2', 'v1']);
		}
	);

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
			shown: [versionDeleteTitle(1, 1), VERSION_DELETE_DRAFT_GOES]
		},
		{
			deleted: 1,
			draft: 'an untouched load of v1',
			prepare: loadV1Untouched,
			held: [LATEST, FIRST],
			shown: [
				versionDeleteTitle(1, 1),
				'The draft loaded from v1 goes too.',
				'Undo for your earlier draft goes too.'
			]
		},
		{
			deleted: 2,
			draft: 'an untouched load of v1',
			prepare: loadV1Untouched,
			held: [THIRD, LATEST, FIRST],
			shown: [
				'Delete v2?',
				'The draft loaded from v1 leaves the editor; v3 replaces it.',
				VERSION_DELETE_LOAD_UNDO_GOES
			]
		},
		{
			deleted: 2,
			draft: 'an untouched load of v1 whose Undo timed out',
			prepare: loadV1WithItsUndoTimedOut,
			held: [THIRD, LATEST, FIRST],
			shown: ['Delete v2?', 'The draft loaded from v1 leaves the editor; v3 replaces it.']
		},
		{
			deleted: 2,
			draft: 'the current version',
			prepare: leaveTheCurrentVersion,
			held: [LATEST, FIRST],
			shown: ['Delete v2?', 'Its lyrics leave the editor; v1 replaces them.']
		},
		{
			deleted: 2,
			draft: 'the current version',
			prepare: leaveTheCurrentVersion,
			held: [LATEST],
			shown: ['Delete v2?', VERSION_DELETE_EMPTIES_EDITOR]
		},
		{
			deleted: 2,
			draft: 'an unsaved edit',
			prepare: typeAnEdit,
			held: [LATEST],
			shown: ['Delete v2?', VERSION_DELETE_DRAFT_GOES, VERSION_DELETE_EMPTIES_EDITOR]
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
		clickNamed(dialog, VERSION_DELETE_CONFIRM_LABEL);

		await vi.waitFor(() => expect(get(versions)).toEqual([LATEST]));
		await tick();
		expect(deleteVersion).toHaveBeenCalledExactlyOnceWith('v1', true);
		expect(addToast).toHaveBeenCalledWith('Deleted v1', 'success');
		expect(deleteConfirm()).toBeNull();
		const sheet = versionsSheet();
		expect(sheet).not.toBeNull();
		expect(versionRowNumbers()).toEqual(['v2']);
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
		clickNamed(dialog, VERSION_REPLACE_DRAFT_CONFIRM_LABEL);
		await tick();
		await Promise.resolve();
		await tick();
		const { toasts } = await shownToasts();
		expect(get(toasts).map((t) => t.message)).toEqual([versionLoadedToastLabel(2)]);

		act(target);
		await tick();

		expect(get(toasts)).toEqual([]);
		undoLastLoad();
		await tick();
		expect(get(editLyrics)).not.toBe('unsaved edit');
	});

	it('Generate after a load saves the loaded text as the next version; the hint and the Undo toast go', async () => {
		const { fetchVersions } = await import('$lib/api/client');
		const next = version({ id: 'v3', version_number: 3, lyrics: 'first draft' });
		vi.mocked(updateSong).mockResolvedValueOnce(
			song({ ...editableSongDefaults(), lyrics: 'first draft', version_count: 3 })
		);
		vi.mocked(fetchVersions).mockResolvedValueOnce([next, LATEST, FIRST]);
		generateSong.mockResolvedValue(jobStatus({ status: 'queued' }));
		const target = await renderView();
		await tapVersion(target, 1);
		const { toasts } = await shownToasts();
		expect(get(toasts).map((t) => t.message)).toEqual([versionLoadedToastLabel(1)]);

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
		expect(target.textContent).not.toContain(versionLoadedFromLabel(1));
		expect(versionChip(target).textContent?.trim()).toBe('v3');
		expect(get(toasts)).toEqual([]);
	});
});
