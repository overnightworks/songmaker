import {
	makeAlbum as album,
	makeGeneration as generation,
	makeHealthResponse,
	makeSong as song,
	makeVersion as version
} from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { phoneAppBar } from '$lib/stores/ui';
import PhoneAppBar from './PhoneAppBar.svelte';

import type { GenerationItem, JobItem, SongItem } from '$lib/api/types';
import {
	ALBUM_COVER_ALT_TYPE,
	COMPACT_LAYOUT_MAX_PX,
	COMPACT_LAYOUT_MEDIA,
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
	EDITOR_GENERATING_LABEL,
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_SAVE_ACCESSIBLE_LABEL,
	EDITOR_SAVE_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	EDITOR_UNSAVED_TITLE,
	EDITOR_VIEW_COWRITER_LABEL,
	EDITOR_VIEW_RECIPE_LABEL,
	LIBRARY_NARROW_MEDIA,
	SONG_COVER_ALT_TYPE,
	SONG_COVER_REMOVE_LABEL,
	SONG_COVER_REPLACE_LABEL,
	SONG_COVER_UPLOAD_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL,
	TAKE_REPAINT_LABEL,
	TAKE_COVER_LABEL,
	TAKE_PLAYLIST_LABEL
} from '$lib/constants';
import { accessibleName, getByRoleButton } from '$lib/test-utils/accessible-name';
import { clearHitboxStyles, clearPointer, injectHitboxStyles } from '$lib/test-utils/hitbox';
import { editLyrics, pinnedSeed, setDraftLyrics, setDraftPrompt } from '$lib/stores/editor';
import { activeJobs, generationFailures } from '$lib/stores/jobs';
import {
	detailTab,
	initNavigation,
	persistLibraryHistory,
	resetNavigationForTests,
	selectSong,
	openWriteTab
} from '$lib/stores/navigation';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { clearSelection, toggleSelection } from '$lib/stores/selection';
import {
	pendingSource,
	recipeModel,
	recipeOpen,
	coWriterOpen,
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
vi.mock('$app/navigation', () => ({
	goto: vi.fn((url: string, options?: { replaceState?: boolean }) => {
		if (options?.replaceState) history.replaceState(null, '', url);
		else history.pushState(null, '', url);
		return Promise.resolve();
	})
}));
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
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: '' }),
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
import recipePanelSource from './editor/RecipePanel.svelte?raw';
import takesListSource from './editor/TakesList.svelte?raw';
import writeColumnSource from './editor/WriteColumn.svelte?raw';
import { addGenerationToPlaylist } from '$lib/api/client';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import { addToast } from '$lib/stores/toast';
import { loras } from '$lib/stores/loras';

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
	resetNavigationForTests();
	pendingSource.set(null);
	pinnedSeed.set(null);
	recipeOpen.set(false);
	coWriterOpen.set(false);
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
	pendingSource.set(null);
	pinnedSeed.set(null);
	recipeOpen.set(false);
	coWriterOpen.set(false);
	clearSelection();
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	selectedAlbumId.set(null);
	songList.set([]);
	albumList.set([]);
	activeJobs.set([]);
	generationFailures.set({});
	clearHitboxStyles();
	clearPointer();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('SongDetailView header — one row, every state', () => {
	it('shows Co-Writer/Recipe toggles stacked and Generate alone, never a second toolbar row', async () => {
		const target = await renderView();
		const actions = header(target).querySelector<HTMLElement>('.editor-header-actions');
		if (!actions) throw new Error('Expected header actions');
		expect(visibleText(actions)).toContain(EDITOR_VIEW_COWRITER_LABEL);
		expect(visibleText(actions)).toContain(EDITOR_VIEW_RECIPE_LABEL);
		expect(target.querySelectorAll('.generate-action .primary-button')).toHaveLength(1);
		expect(target.querySelector('.generate-action .primary-button')?.textContent).toContain(
			EDITOR_GENERATE_MODE_LABELS.generate
		);
	});

	it('toggles the Recipe panel independently of the Write/Takes content', async () => {
		const target = await renderView();
		expect(target.querySelector('.recipe-panel')).toBeNull();
		clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
		await tick();
		expect(get(recipeOpen)).toBe(true);
		expect(target.querySelector('.recipe-panel')).not.toBeNull();
	});

	it('switches the Write column into Co-Writer mode without hiding the header', async () => {
		const target = await renderView();
		clickNamed(header(target), EDITOR_VIEW_COWRITER_LABEL);
		await tick();
		await Promise.resolve();
		await tick();
		expect(get(coWriterOpen)).toBe(true);
		expect(target.querySelector('.cowriter-mode')).not.toBeNull();
		expect(target.querySelector('.detail-header')).not.toBeNull();
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
	it('shows Write and Takes as two simultaneous columns on desktop, no tab switcher', async () => {
		const target = await renderView();
		expect(target.querySelector('.editor-columns')).not.toBeNull();
		expect(target.querySelector('[role="tablist"]')).toBeNull();
		expect(target.querySelector('.lyrics-area')).not.toBeNull();
		expect(target.querySelector('.takes-column')).not.toBeNull();
	});

	it('publishes the song actions in the layout bar and clears them when leaving', async () => {
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		const bar = document.createElement('div');
		document.body.append(bar);
		mounted.push(mount(PhoneAppBar, { target: bar }));
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

	it('switches between Write and the real Takes list at phone width without losing the draft', async () => {
		openWriteTab();
		stubLibraryMedia({ narrow: true, compact: true });
		const target = await renderView({ widthPx: 390 });
		expect(target.querySelector('.editor-columns')).toBeNull();
		const lyrics = target.querySelector<HTMLTextAreaElement>('.lyrics-area');
		if (!lyrics) throw new Error('Expected editable lyrics');
		lyrics.value = 'An unfinished verse';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		expect(Array.from(tabs, (tab) => tab.textContent?.trim())).toEqual(['Write', 'Takes (1)']);
		tabs[1].click();
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
		row.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
		await tick();
		const addItem = Array.from(row.querySelectorAll<HTMLButtonElement>('.overflow-item')).find(
			(el) => el.textContent?.trim() === TAKE_PLAYLIST_LABEL
		);
		if (!addItem) throw new Error(`Expected a "${TAKE_PLAYLIST_LABEL}" menu item`);
		addItem.click();
		await tick();
		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		// The picker closes once the add has fully settled, toast included.
		await vi.waitFor(() => expect(row.querySelector('.picker')).toBeNull());

		expect(addGenerationToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(vi.mocked(addToast).mock.calls).toEqual([['Added to playlist', 'success']]);
	});
});

describe('SongDetailView recipe and takes', () => {
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
		expect(row?.querySelectorAll('button')).toHaveLength(3);
		expect(row?.querySelector('[role="button"].take-summary')).not.toBeNull();
		expect(row?.textContent).not.toMatch(/Repaint|Cover/);
	});

	it.each(['repaint', 'cover'] as const)(
		'lands a picked-up %s source in the Recipe panel',
		async (mode) => {
			const target = await renderView();
			expect(get(recipeOpen)).toBe(false);

			pendingSource.set({ generation: generation(sourceRecipeDefaults()), mode });
			await tick();
			await tick();
			expect(get(recipeOpen)).toBe(true);
			expect(get(sourceMode)).toBe(mode);
			clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
			await tick();
			clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
			await tick();
			expect(get(recipeOpen)).toBe(true);
		}
	);

	it.each([
		['repaint', false],
		['cover', false],
		['repaint', true],
		['cover', true]
	] as const)(
		'opens the recipe with the menu take as %s source (compact: %s)',
		async (mode, compact) => {
			stubLibraryMedia({ narrow: compact, compact });
			const target = await renderView();
			expect(get(recipeOpen)).toBe(false);
			target.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
			await tick();
			clickNamed(target, mode === 'repaint' ? TAKE_REPAINT_LABEL : TAKE_COVER_LABEL);
			await tick();
			expect(get(recipeOpen)).toBe(true);
			expect(get(sourceMode)).toBe(mode);
			expect(get(sourceGeneration)?.id).toBe('g1');
			expect(target.querySelector('.recipe-panel')).not.toBeNull();
		}
	);

	it.each(['Cancel', 'Delete'])('asks once before take deletion and honors %s', async (choice) => {
		const { deleteGeneration } = await import('$lib/api/client');
		vi.mocked(deleteGeneration).mockClear();
		const target = await renderView();
		target.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
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
		await vi.waitFor(() => expect(history.state.generationId).toBe('g1'));
		const target = await renderView();
		toggleSelection('g1');
		await tick();
		clickNamed(target, 'Delete Selected');
		await tick();
		await Promise.resolve();
		await tick();
		expect(get(selectedGenerationId)).toBeNull();
		expect(history.state.generationId).toBeNull();
	});
});

describe('SongDetailView Generate is enabled from the draft', () => {
	it('stays disabled until the draft has lyrics, a prompt, and a model — even on a freshly created song with nothing saved', async () => {
		songList.set([song({ ...editableSongDefaults(), lyrics: '', prompt: '' })]);
		const target = await renderView();
		const generateBtn = () =>
			Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
				(el) => el.textContent?.trim() === EDITOR_GENERATE_MODE_LABELS.generate
			);
		expect(generateBtn()?.disabled).toBe(true);

		setDraftLyrics('typed lyrics');
		setDraftPrompt('typed style');
		recipeModel.set('turbo');
		await tick();

		expect(generateBtn()?.disabled).toBe(false);
	});

	it.each([
		['repaint', 'Repaint'],
		['cover', 'Cover']
	] as const)('names Generate after the active %s mode', async (mode, label) => {
		const target = await renderView();
		setSourceFromGeneration(generation(sourceRecipeDefaults()), mode);
		await tick();

		expect(target.querySelector('.generate-action .primary-button')?.textContent?.trim()).toBe(
			label
		);
	});

	it('keeps Text2Music named Generate', async () => {
		const target = await renderView();
		expect(target.querySelector('.generate-action .primary-button')?.textContent?.trim()).toBe(
			EDITOR_GENERATE_MODE_LABELS.generate
		);
	});
});

describe.each([false, true])('SongDetailView Generate with phone layout %s', (phone) => {
	beforeEach(() => {
		recipeModel.set('turbo');
		stubLibraryMedia({ narrow: phone });
		openWriteTab();
	});

	function generateBtn(target: HTMLElement): HTMLButtonElement | null {
		return target.querySelector<HTMLButtonElement>('.generate-action .primary-button');
	}

	it('disables Generate with a reason when no ACE-Step worker is online', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ acestep_workers_online: 0 }));
		const target = await renderView();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(true);
		expect(target.querySelector('.generate-action .reason')?.textContent).toContain(
			EDITOR_GPU_OFFLINE_TITLE
		);
		expect(btn?.title).toBe(EDITOR_GPU_OFFLINE_TITLE);
	});

	it('keeps Generate enabled when at least one ACE-Step worker is online', async () => {
		fetchHealth.mockResolvedValue(makeHealthResponse({ acestep_workers_online: 2 }));
		const target = await renderView();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(false);
		expect(btn?.textContent).toContain(EDITOR_GENERATE_MODE_LABELS.generate);
	});

	it('re-enables Generate without a reload once a worker comes back online', async () => {
		vi.useFakeTimers();
		fetchHealth.mockResolvedValue(makeHealthResponse({ acestep_workers_online: 0 }));
		const target = await renderView();
		expect(generateBtn(target)?.disabled).toBe(true);

		fetchHealth.mockResolvedValue(makeHealthResponse({ acestep_workers_online: 1 }));
		await vi.advanceTimersByTimeAsync(15_000);
		await tick();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(false);
		expect(btn?.textContent).toContain(EDITOR_GENERATE_MODE_LABELS.generate);
	});

	it('shows the worker failure at Generate, expands it and retries through the same button', async () => {
		const cause =
			'Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available';
		generationFailures.set({ s1: cause });
		generateSong.mockResolvedValue(jobStatus({ status: 'queued' }));
		const target = await renderView();
		const action = target.querySelector<HTMLElement>('.generate-action');
		if (!action) throw new Error('Expected Generate action');
		expect(target.querySelectorAll('.generate-action')).toHaveLength(1);
		expect(action.textContent).toContain(cause);
		expect(target.querySelector('.takes-list')?.textContent ?? '').not.toContain(cause);
		const expand = getByRoleButton(action, EDITOR_GENERATE_FAILURE_EXPAND_LABEL);
		expect(expand.getAttribute('aria-expanded')).toBe('false');
		expand.click();
		await tick();
		expect(expand.getAttribute('aria-expanded')).toBe('true');
		getByRoleButton(action, EDITOR_GENERATE_MODE_LABELS.generate).click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(1));
		await tick();
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
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('boom', 'error'));

		generateSong.mockResolvedValueOnce(jobStatus({ status: 'completed' }));
		generateBtn(target).click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(2));
	});
});

describe('SongDetailView recipe chips read the draft', () => {
	it('updates the BPM chip live as the Recipe panel edits it, and marks it changed', async () => {
		const target = await renderView();
		clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
		await tick();

		const bpmInput = target.querySelector<HTMLInputElement>('.recipe-groups input[type="number"]');
		if (!bpmInput) throw new Error('Expected the BPM input');
		bpmInput.value = '140';
		bpmInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		const bpmChip = Array.from(target.querySelectorAll('.chip')).find((el) =>
			el.textContent?.includes('BPM')
		);
		expect(bpmChip?.textContent).toContain('140');
		expect(bpmChip?.querySelector('.chip-changed-dot')).not.toBeNull();
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
			mounted.push(mount(PhoneAppBar, { target }));
			await tick();
			target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
			await tick();
			clickNamed(target, 'Save version');
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

	it('cross-song Repaint/Cover: Cancel leaves it unapplied and drops the pending source', async () => {
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		const targetGen = generation({
			...sourceRecipeDefaults(),
			id: 'g-last',
			song_id: 's-last'
		});
		pendingSource.set({ generation: targetGen, mode: 'repaint' });
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

		clickNamed(target, 'Cancel');
		await tick();

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingSource)).toBeNull();
		expect(get(sourceGeneration)).toBeNull();
	});

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
		pendingSource.set({ generation: targetGen, mode: 'repaint' });
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
		expect(get(pendingSource)).toBeNull();
	});
});

describe('SongDetailView Co-Writer and Recipe stacked (both open)', () => {
	it('shows the condensed EditorStacked summary instead of the full panel, keeping the chat visible; Edit reveals the full panel', async () => {
		const target = await renderView();
		coWriterOpen.set(true);
		recipeOpen.set(true);
		await tick();

		expect(target.querySelector('.editor-stacked')).not.toBeNull();
		expect(target.querySelector('.recipe-panel')).toBeNull();
		expect(target.querySelector('.cowriter-chat')).not.toBeNull();

		target.querySelector<HTMLButtonElement>('.stacked-edit')?.click();
		await tick();

		expect(target.querySelector('.recipe-panel')).not.toBeNull();
		expect(target.querySelector('.editor-stacked')).toBeNull();
	});
});

describe('SongDetailView mobile Co-Writer opens as a sheet', () => {
	it('keeps the Write surface underneath instead of replacing it', async () => {
		openWriteTab();
		stubLibraryMedia({ narrow: false, compact: true });
		const target = await renderView();
		expect(target.querySelector('.write-surface .take-strip')).not.toBeNull();

		coWriterOpen.set(true);
		await tick();

		expect(target.querySelector('.write-surface .take-strip')).not.toBeNull();
		expect(target.querySelector('.sheet-panel')).not.toBeNull();
		expect(target.querySelector('.sheet-panel .cowriter-mode')).not.toBeNull();
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

	it('replaces the song and keeps the Write tab when next is clicked', async () => {
		stubLibraryMedia({ narrow: true, compact: false });
		const songs = albumSongs();
		albumList.set([album({ id: 'a-local', title: 'Local Album', song_count: 3 })]);
		songList.set(songs);
		selectedSongId.set('s1');
		const cleanup = initNavigation();
		selectSong('s1');
		openWriteTab();
		const index = history.state.index;
		const push = vi.spyOn(history, 'pushState');
		const target = await renderView();
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
		if (!next) throw new Error('Expected next');
		next.click();
		await tick();
		expect(push).not.toHaveBeenCalled();
		expect(history.state.index).toBe(index);
		expect(get(selectedSongId)).toBe('s-last');
		expect(get(detailTab)).toBe('write');
		push.mockRestore();
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
		expect(songDetailViewSource).toMatch(/\.editor-body \{[^}]*container: editor \/ inline-size;/);
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
			RecipePanel: recipePanelSource,
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
