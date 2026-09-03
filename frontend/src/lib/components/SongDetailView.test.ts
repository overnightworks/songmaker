import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type {
	AlbumItem,
	GenerationItem,
	JobItem,
	SongItem,
	VersionGenerationParams,
	VersionItem
} from '$lib/api/types';
import type { HealthSummary } from '$lib/api/client';
import {
	ALBUM_COVER_ALT_TYPE,
	COMPACT_LAYOUT_MAX_PX,
	COMPACT_LAYOUT_MEDIA,
	EDITOR_GENERATE_LABEL,
	EDITOR_GENERATING_LABEL,
	EDITOR_GPU_OFFLINE_LABEL,
	EDITOR_GPU_OFFLINE_TITLE,
	EDITOR_SAVE_ACCESSIBLE_LABEL,
	EDITOR_SAVE_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_TAB_WRITE_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	EDITOR_UNSAVED_TITLE,
	EDITOR_VIEW_COWRITER_LABEL,
	EDITOR_VIEW_RECIPE_LABEL,
	HITBOX_FREQUENT_PX,
	LIBRARY_NARROW_MEDIA,
	SONG_COVER_ALT_TYPE,
	SONG_COVER_REMOVE_LABEL,
	SONG_COVER_REPLACE_LABEL,
	SONG_COVER_UPLOAD_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL,
	TAKE_AGAIN_LABEL,
	TAKE_PLAYLIST_LABEL
} from '$lib/constants';
import { accessibleName } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minHeightPx,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import {
	editGenParams,
	editLyrics,
	pinnedSeed,
	setDraftLyrics,
	setDraftPrompt
} from '$lib/stores/editor';
import { activeJobs } from '$lib/stores/jobs';
import {
	detailTab,
	initNavigation,
	persistLibraryHistory,
	resetNavigationForTests,
	selectSong,
	switchTab
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

const mounted: Array<ReturnType<typeof mount>> = [];

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: { inference_steps: 8, guidance_scale: 1.5 },
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

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

function healthSummary(overrides: Partial<HealthSummary> = {}): HealthSummary {
	return {
		status: 'ok',
		queue_depth_cap_reached: false,
		music_queue_depth: 0,
		scoring_queue_depth: 0,
		acestep_workers_online: 1,
		acestep_workers_total: 1,
		...overrides
	};
}

function version(overrides: Partial<VersionItem> = {}): VersionItem {
	return {
		id: 'v1',
		version_number: 1,
		lyrics: 'verse',
		prompt: 'dark folk',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	const gen = generation();
	return {
		id: 's1',
		slug: 'local-only',
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
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [gen],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
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

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Local Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 3,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function albumSongs(): SongItem[] {
	return [
		song({ id: 's-first', title: 'First', track_number: 1 }),
		song({ id: 's1', title: 'Local Only', track_number: 2 }),
		song({ id: 's-last', title: 'Last', track_number: 3 })
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
	songList.set([song()]);
	selectedSongId.set('s1');
	selectedGenerationId.set(null);
	fetchAlbum.mockReset();
	fetchAlbum.mockResolvedValue(album());
	playlistList.set([
		{
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addGenerationToPlaylist).mockClear();
	uploadSongCover.mockReset();
	deleteSongCover.mockReset();
	deleteAlbumCover.mockReset();
	fetchHealth.mockReset();
	fetchHealth.mockResolvedValue(healthSummary());
	generateSong.mockReset();
	activeJobs.set([]);
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
	clearHitboxStyles();
	clearPointer();
	vi.unstubAllGlobals();
});

describe('SongDetailView header — one row, every state', () => {
	it('shows Co-Writer/Recipe toggles stacked and Generate alone, never a second toolbar row', async () => {
		const target = await renderView();
		const actions = header(target).querySelector<HTMLElement>('.editor-header-actions');
		if (!actions) throw new Error('Expected header actions');
		expect(visibleText(actions)).toContain(EDITOR_VIEW_COWRITER_LABEL);
		expect(visibleText(actions)).toContain(EDITOR_VIEW_RECIPE_LABEL);
		expect(target.querySelectorAll('.generate-btn')).toHaveLength(1);
		expect(target.querySelector('.generate-btn')?.textContent).toContain(EDITOR_GENERATE_LABEL);
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
		songList.set([song({ is_shared: true, share_slug: 'abc123' })]);
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

	it('shows Write | Takes tabs and only one at a time when compact, defaulting to Takes', async () => {
		stubLibraryMedia({ narrow: false, compact: true });
		const target = await renderView();
		const tablist = target.querySelector('[role="tablist"]');
		expect(tablist?.textContent).toContain(EDITOR_TAB_WRITE_LABEL);
		expect(tablist?.textContent).toContain(EDITOR_TAB_TAKES_LABEL);
		expect(target.querySelector('.editor-columns')).toBeNull();
		expect(get(detailTab)).toBe('takes');
		expect(target.querySelector('.lyrics-area')).toBeNull();
		expect(target.querySelector('.takes-list, .empty')).not.toBeNull();

		clickNamed(target, EDITOR_TAB_WRITE_LABEL);
		await tick();
		expect(get(detailTab)).toBe('write');
		expect(target.querySelector('.lyrics-area')).not.toBeNull();
		expect(target.querySelector('.takes-list')).toBeNull();
	});

	it('sizes the Write | Takes tabs to the frequent hitbox on a coarse pointer', async () => {
		// #163/6: the tabs are how a phone moves through the editor at all.
		injectHitboxStyles();
		stubLibraryMedia({ narrow: false, compact: true });
		const target = await renderView();
		setPointer('coarse');

		const tabs = Array.from(target.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
		expect(tabs).toHaveLength(2);
		for (const tab of tabs) {
			expect(minHeightPx(tab, tab.textContent ?? 'tab')).toBe(HITBOX_FREQUENT_PX);
		}
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
	it.each([
		['Repaint', 'repaint'],
		['Cover', 'cover']
	] as const)('%s opens Recipe with the selected take in %s mode', async (label, mode) => {
		const target = await renderView();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		Array.from(row.querySelectorAll<HTMLButtonElement>('.take-action-btn'))
			.find((button) => button.textContent?.trim() === label)
			?.click();
		await tick();

		expect(get(recipeOpen)).toBe(true);
		expect(get(sourceGeneration)).toEqual(expect.objectContaining({ id: 'g1' }));
		expect(get(sourceMode)).toBe(mode);
	});

	it.each(['repaint', 'cover'] as const)(
		'lands a picked-up %s source in the Recipe panel',
		async (mode) => {
			const target = await renderView();
			expect(get(recipeOpen)).toBe(false);

			pendingSource.set({ generation: generation(), mode });
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

	it('keeps draft params when Again has no reusable take params', async () => {
		songList.set([
			song({
				generation_params: { inference_steps: 12, guidance_scale: 2 },
				generations: [generation({ generation_params: null, seed: 11 })]
			})
		]);
		const target = await renderView();
		expect(get(editGenParams)).toEqual({ inference_steps: 12, guidance_scale: 2 });
		const takeMenuBtn = target.querySelector<HTMLButtonElement>('.overflow-btn');
		takeMenuBtn?.click();
		await tick();
		clickNamed(target, TAKE_AGAIN_LABEL);
		await tick();
		expect(get(pinnedSeed)).toBe(11);
		expect(get(editGenParams)).toEqual({ inference_steps: 12, guidance_scale: 2 });
		expect(get(recipeOpen)).toBe(true);
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
		songList.set([song({ lyrics: '', prompt: '' })]);
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

	it.each([
		['repaint', 'Generate Repaint'],
		['cover', 'Generate Cover']
	] as const)('names Generate after the active %s mode', async (mode, label) => {
		const target = await renderView();
		setSourceFromGeneration(generation(), mode);
		await tick();

		expect(target.querySelector('.generate-btn')?.textContent?.trim()).toBe(label);
	});

	it('keeps Text2Music named Generate', async () => {
		const target = await renderView();
		expect(target.querySelector('.generate-btn')?.textContent?.trim()).toBe(EDITOR_GENERATE_LABEL);
	});
});

describe('SongDetailView Generate reacts to ACE-Step worker availability', () => {
	beforeEach(() => {
		recipeModel.set('turbo');
	});

	function generateBtn(target: HTMLElement): HTMLButtonElement | null {
		return target.querySelector<HTMLButtonElement>('.generate-btn');
	}

	it('disables Generate with a reason when no ACE-Step worker is online', async () => {
		fetchHealth.mockResolvedValue(healthSummary({ acestep_workers_online: 0 }));
		const target = await renderView();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(true);
		expect(btn?.textContent).toContain(EDITOR_GPU_OFFLINE_LABEL);
		expect(btn?.title).toBe(EDITOR_GPU_OFFLINE_TITLE);
	});

	it('keeps Generate enabled when at least one ACE-Step worker is online', async () => {
		fetchHealth.mockResolvedValue(healthSummary({ acestep_workers_online: 2 }));
		const target = await renderView();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(false);
		expect(btn?.textContent).toContain(EDITOR_GENERATE_LABEL);
	});

	it('re-enables Generate without a reload once a worker comes back online', async () => {
		fetchHealth.mockResolvedValue(healthSummary({ acestep_workers_online: 0 }));
		const target = await renderView();
		expect(generateBtn(target)?.disabled).toBe(true);

		fetchHealth.mockResolvedValue(healthSummary({ acestep_workers_online: 1 }));
		const { refreshHealth } = await import('$lib/stores/health');
		await refreshHealth();
		await tick();

		const btn = generateBtn(target);
		expect(btn?.disabled).toBe(false);
		expect(btn?.textContent).toContain(EDITOR_GENERATE_LABEL);
	});
});

describe('SongDetailView Generate double-click guard (#234)', () => {
	beforeEach(() => {
		recipeModel.set('turbo');
	});

	function generateBtn(target: HTMLElement): HTMLButtonElement {
		const btn = target.querySelector<HTMLButtonElement>('.generate-btn');
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

		expect(btn.disabled).toBe(true);
		expect(btn.textContent).toContain(EDITOR_GENERATING_LABEL);

		resolveGenerate(jobStatus({ status: 'completed' }));
		await tick();
		await Promise.resolve();
		await tick();

		expect(btn.disabled).toBe(false);
	});

	it('releases the guard after a successful response, letting the next click through', async () => {
		generateSong.mockResolvedValue(jobStatus({ status: 'completed' }));
		const target = await renderView();
		const btn = generateBtn(target);

		btn.click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(1));
		await tick();

		btn.click();
		await vi.waitFor(() => expect(generateSong).toHaveBeenCalledTimes(2));
	});

	it('releases the guard after a failed response, letting a retry through', async () => {
		generateSong.mockRejectedValueOnce(new Error('boom'));
		const target = await renderView();
		const btn = generateBtn(target);

		btn.click();
		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('boom', 'error'));

		generateSong.mockResolvedValueOnce(jobStatus({ status: 'completed' }));
		btn.click();
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

		selectSong('s-last', song({ id: 's-last', album_id: 'a-local', title: 'Last' }));
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

		selectSong('s-last', song({ id: 's-last', album_id: 'a-local', title: 'Last' }));
		await tick();
		clickNamed(target, 'Discard');
		await tick();

		expect(get(selectedSongId)).toBe('s-last');
	});

	it('Save persists the draft as a new version, then switches songs', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(song({ lyrics: 'unsaved edit', version_count: 2 }));
		songList.set(albumSongs());
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		selectSong('s-last', song({ id: 's-last', album_id: 'a-local', title: 'Last' }));
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

		selectSong('s-last', song({ id: 's-last', album_id: 'a-local', title: 'Last' }));
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

	it('saves from the write surface without the overflow menu or generate', async () => {
		const { updateSong } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(song({ version_count: 2 }));
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		expect(target.querySelector('.menu-panel')).toBeNull();
		writeSaveButton(target).click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(updateSong).toHaveBeenCalled();
		expect(generateSong).not.toHaveBeenCalled();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('toasts the actual saved version number from the versions API response, not version_count', async () => {
		const { updateSong, fetchVersions } = await import('$lib/api/client');
		vi.mocked(updateSong).mockResolvedValueOnce(song({ version_count: 2 }));
		const target = await renderView();
		setDraftLyrics('unsaved edit');
		await tick();

		// Only override the *post-save* reload — the initial render already
		// consumed one fetchVersions() call while loading the song.
		vi.mocked(fetchVersions).mockResolvedValueOnce([version({ id: 'v5', version_number: 5 })]);
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

		const targetGen = generation({ id: 'g-last', song_id: 's-last' });
		pendingSource.set({ generation: targetGen, mode: 'repaint' });
		selectSong(
			's-last',
			song({ id: 's-last', album_id: 'a-local', title: 'Last', generations: [targetGen] })
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

		const targetGen = generation({ id: 'g-last', song_id: 's-last' });
		pendingSource.set({ generation: targetGen, mode: 'repaint' });
		selectSong(
			's-last',
			song({ id: 's-last', album_id: 'a-local', title: 'Last', generations: [targetGen] })
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
	it('keeps the Write | Takes tabs underneath instead of replacing them', async () => {
		stubLibraryMedia({ narrow: false, compact: true });
		const target = await renderView();
		expect(target.querySelector('.editor-tabs')).not.toBeNull();

		coWriterOpen.set(true);
		await tick();

		expect(target.querySelector('.editor-tabs')).not.toBeNull();
		expect(target.querySelector('.sheet-panel')).not.toBeNull();
		expect(target.querySelector('.sheet-panel .cowriter-mode')).not.toBeNull();
	});
});

describe('recipe params from a take', () => {
	it('copies reusable params on Again', async () => {
		const { recipeParamsFromTake } = await import('$lib/stores/recipe');
		const params: VersionGenerationParams = recipeParamsFromTake({
			inference_steps: 8,
			guidance_scale: 1.5,
			task_type: 'text2music',
			seed: 99
		});
		expect(params.inference_steps).toBe(8);
		expect(params.guidance_scale).toBe(1.5);
		expect((params as Record<string, unknown>).task_type).toBeUndefined();
		expect((params as Record<string, unknown>).seed).toBeUndefined();
	});
});

describe('song header album rail', () => {
	beforeEach(() => {
		injectHitboxStyles();
	});

	it('hides previous/next when browse is shown', async () => {
		stubLibraryMedia({ narrow: false, compact: true });
		document.documentElement.dataset.pointer = 'coarse';
		songList.set(albumSongs());
		const target = await renderView();
		expect(target.querySelector('.song-rail')).toBeNull();
		expect(target.querySelector(`[aria-label="${SONG_PREVIOUS_LABEL}"]`)).toBeNull();
		expect(target.querySelector(`[aria-label="${SONG_NEXT_LABEL}"]`)).toBeNull();
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs[0]).toBe('Library');
		expect(crumbs[1]).toBe('Local Album');
	});

	it('shows album title and disabled ends without wrapping through neighbors', async () => {
		stubLibraryMedia({ narrow: true });
		albumList.set([album()]);
		songList.set(albumSongs());
		selectedSongId.set('s1');
		const target = await renderView();
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
		if (!prev || !next) throw new Error('Expected previous and next');
		expect(prev.disabled).toBe(false);
		expect(next.disabled).toBe(false);
		expect(prev.getAttribute('data-hitbox')).toBe('frequent');
		expect(next.getAttribute('data-hitbox')).toBe('frequent');
		const albumCrumb = Array.from(target.querySelectorAll('.crumb-link')).find(
			(el) => el.textContent === 'Local Album'
		);
		expect(albumCrumb).toBeDefined();

		setPointer('coarse');
		expect(minSquarePx(prev, 'previous song').width).toBe(HITBOX_FREQUENT_PX);
		expect(minSquarePx(next, 'next song').width).toBe(HITBOX_FREQUENT_PX);

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
		stubLibraryMedia({ narrow: true });
		const target = await renderView();
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
		if (!prev || !next) throw new Error('Expected previous and next');
		expect(prev.disabled).toBe(true);
		expect(next.disabled).toBe(true);
	});

	it('replaces the song and keeps the Write tab when next is clicked', async () => {
		stubLibraryMedia({ narrow: true, compact: true });
		const songs = albumSongs();
		albumList.set([album()]);
		songList.set(songs);
		selectedSongId.set('s1');
		const cleanup = initNavigation();
		selectSong('s1');
		switchTab('write');
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

	it('keeps the narrow coarse rail inside 320px with a long album title', async () => {
		stubLibraryMedia({ narrow: true });
		document.documentElement.dataset.pointer = 'coarse';
		const longAlbumTitle =
			'The Unreasonably Long Anniversary Collection From the Other Side of the Harbor';
		songList.set(albumSongs().map((item) => ({ ...item, album_title: longAlbumTitle })));
		selectedSongId.set('s1');
		const target = await renderView({ widthPx: 320 });
		const headerEl = target.querySelector('.detail-header');
		const rail = target.querySelector('.song-rail');
		const prev = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_PREVIOUS_LABEL}"]`);
		const next = target.querySelector<HTMLButtonElement>(`[aria-label="${SONG_NEXT_LABEL}"]`);
		if (!(headerEl instanceof HTMLElement) || !(rail instanceof HTMLElement) || !prev || !next) {
			throw new Error('Expected header song rail');
		}
		const albumCrumb = Array.from(rail.querySelectorAll('.crumb-link')).find(
			(el) => el.textContent === longAlbumTitle
		);
		expect(albumCrumb).toBeDefined();
		expect(minSquarePx(prev, 'previous song').width).toBe(HITBOX_FREQUENT_PX);
		expect(minSquarePx(next, 'next song').width).toBe(HITBOX_FREQUENT_PX);
		expect(headerEl.scrollWidth).toBeLessThanOrEqual(320);
		expect(rail.scrollWidth).toBeLessThanOrEqual(320);
	});

	it('shows Library › Album › Track n of m as the breadcrumb', async () => {
		stubLibraryMedia({ narrow: false, compact: true });
		const songs = albumSongs();
		albumList.set([album()]);
		songList.set(songs);
		selectedSongId.set('s1');
		const target = await renderView();
		const crumbs = Array.from(target.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs[0]).toBe('Library');
		expect(crumbs[1]).toBe('Local Album');
		expect(crumbs[2]).toBe(`Track ${songs.findIndex((s) => s.id === 's1') + 1} of ${songs.length}`);
	});

	it('opens album overview from the album title', async () => {
		stubLibraryMedia({ narrow: true });
		selectedAlbumId.set('a-local');
		const cleanup = initNavigation();
		selectSong('s1');
		const target = await renderView();
		const albumBtn = Array.from(target.querySelectorAll<HTMLButtonElement>('.crumb-link')).find(
			(el) => el.textContent === 'Local Album'
		);
		if (!albumBtn) throw new Error('Expected album control');
		albumBtn.click();
		await tick();
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedAlbumId)).toBe('a-local');
		cleanup();
	});
});

describe('SongDetailView cover hero', () => {
	it('inherits parent album cover and does not show remove', async () => {
		albumList.set([
			album({
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
				cover: {
					card: '/api/songs/s1/cover?variant=card&v=own.jpg',
					detail: '/api/songs/s1/cover?variant=detail&v=own.jpg'
				}
			})
		]);
		albumList.set([
			album({
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
		albumList.set([album()]);
		uploadSongCover.mockResolvedValue(
			song({
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
				cover: {
					card: '/api/songs/s1/cover?variant=card&v=own.jpg',
					detail: '/api/songs/s1/cover?variant=detail&v=own.jpg'
				}
			})
		]);
		albumList.set([
			album({
				cover: {
					card: '/api/albums/a-local/cover?variant=card&v=album.jpg',
					detail: '/api/albums/a-local/cover?variant=detail&v=album.jpg'
				}
			})
		]);
		deleteSongCover.mockResolvedValue(song({ cover: null }));
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
		// The compact shell keeps its own rule: `main` scrolls the whole panel,
		// whose bottom padding is what clears the sticky Generate bar.
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

describe('mobile layout reserves space for the sticky Generate bar', () => {
	// jsdom cannot compute fixed-element layout, so this pins the stylesheet
	// rule directly (the same technique routes/layout.test.ts uses).
	it("keeps the takes scroll container's bottom padding clear of both the sticky Generate bar and the player bar", () => {
		const media = /@media \(max-width: 768px\) \{[\s\S]*?\.detail-panel \{([\s\S]*?)\}/.exec(
			songDetailViewSource
		);
		if (!media) throw new Error('Expected a mobile .detail-panel rule in the stylesheet');
		expect(media[1]).toContain('--editor-generate-bar-height');
		expect(media[1]).toContain('--player-height');
	});
});
