import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, GenerationItem, SongItem, VersionGenerationParams } from '$lib/api/types';
import {
	ALBUM_COVER_ALT_TYPE,
	COMPACT_LAYOUT_MEDIA,
	EDITOR_GENERATE_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_TAB_WRITE_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	EDITOR_VIEW_RECIPE_LABEL,
	HITBOX_FREQUENT_PX,
	LIBRARY_NARROW_MEDIA,
	SONG_COVER_ALT_TYPE,
	SONG_COVER_REMOVE_LABEL,
	SONG_COVER_REPLACE_LABEL,
	SONG_COVER_UPLOAD_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL
} from '$lib/constants';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';
import { editGenParams, pinnedSeed } from '$lib/stores/editor';
import {
	detailTab,
	initNavigation,
	persistLibraryHistory,
	resetNavigationForTests,
	selectSong,
	switchTab
} from '$lib/stores/navigation';
import {
	albumList,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import { clearSelection, toggleSelection } from '$lib/stores/selection';
import { pendingSource, recipeModel, recipeOpen, coWriterOpen } from '$lib/stores/recipe';

const fetchAlbum = vi.fn();
const uploadSongCover = vi.fn();
const deleteSongCover = vi.fn();
const deleteAlbumCover = vi.fn();

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
		fetchHealth: vi.fn().mockResolvedValue(null),
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
		deleteAlbumCover: (...args: unknown[]) => deleteAlbumCover(...args)
	};
});
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn()
}));

import SongDetailView from './SongDetailView.svelte';

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
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	const gen = generation();
	return {
		id: 's1',
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

function px(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	const parsed = Number.parseFloat(resolved);
	return Number.isFinite(parsed) ? parsed : 0;
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
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
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
	uploadSongCover.mockReset();
	deleteSongCover.mockReset();
	deleteAlbumCover.mockReset();
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
	delete document.documentElement.dataset.pointer;
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
});

describe('SongDetailView recipe and takes', () => {
	it('keeps the take inspector as a modal over the workspace', async () => {
		selectedGenerationId.set('g1');
		const target = await renderView();
		expect(visibleText(target)).toContain('Local Only');
		expect(target.querySelector('.inspector-modal')).not.toBeNull();
		expect(target.querySelector('.inspector')).not.toBeNull();

		const closeBtn = target.querySelector<HTMLButtonElement>('.inspector .close-btn');
		if (!closeBtn) throw new Error('Expected inspector close');
		closeBtn.click();
		await tick();
		expect(get(selectedGenerationId)).toBeNull();
		expect(target.querySelector('.inspector-modal')).toBeNull();
	});

	it('lands a picked-up source in the Recipe panel', async () => {
		const target = await renderView();
		expect(get(recipeOpen)).toBe(false);

		pendingSource.set({ generation: generation(), mode: 'repaint' });
		await tick();
		await tick();
		expect(get(recipeOpen)).toBe(true);
		clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
		await tick();
		clickNamed(header(target), EDITOR_VIEW_RECIPE_LABEL);
		await tick();
		expect(get(recipeOpen)).toBe(true);
	});

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
		clickNamed(target, 'Again');
		await tick();
		expect(get(pinnedSeed)).toBe(11);
		expect(get(editGenParams)).toEqual({ inference_steps: 12, guidance_scale: 2 });
		expect(get(recipeOpen)).toBe(true);
	});

	it('clears the inspector when bulk delete includes the inspected take', async () => {
		selectedGenerationId.set('g1');
		persistLibraryHistory();
		expect(history.state.generationId).toBe('g1');
		const target = await renderView();
		expect(target.querySelector('.inspector-modal')).not.toBeNull();
		toggleSelection('g1');
		await tick();
		clickNamed(target, 'Delete Selected');
		await tick();
		await Promise.resolve();
		await tick();
		expect(get(selectedGenerationId)).toBeNull();
		expect(history.state.generationId).toBeNull();
		expect(target.querySelector('.inspector-modal')).toBeNull();
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
		const sheet = document.createElement('style');
		sheet.dataset.hitboxStyles = 'true';
		sheet.textContent = hitboxCss;
		document.head.append(sheet);
	});

	afterEach(() => {
		document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
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

		document.documentElement.dataset.pointer = 'coarse';
		expect(px(getComputedStyle(prev).minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(getComputedStyle(next).minWidth)).toBe(HITBOX_FREQUENT_PX);

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
		expect(px(getComputedStyle(prev).minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(getComputedStyle(next).minWidth)).toBe(HITBOX_FREQUENT_PX);
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
