import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { GenerationItem, SongItem, VersionGenerationParams } from '$lib/api/types';
import {
	SONG_SPLIT_PANE_GAP_PX,
	SONG_SPLIT_PANE_MIN_PX,
	SONG_SURFACE_COWRITER,
	SONG_SURFACE_RECIPE,
	SONG_SURFACE_TAKES,
	TAKE_AGAIN_LABEL,
	TAKE_AUDIO_COVER_LABEL,
	TAKE_REPAINT_LABEL,
	canSplitSongPanes
} from '$lib/constants';
import { editGenParams, pinnedSeed } from '$lib/stores/editor';
import { detailTab, persistLibraryHistory, resetNavigationForTests } from '$lib/stores/navigation';
import { selectedGenerationId, selectedSongId, songList } from '$lib/stores/player';
import { clearSelection, toggleSelection } from '$lib/stores/selection';
import { pendingSource } from '$lib/stores/source';

vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn()
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
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
		fetchSong: vi.fn(),
		fetchSongs: vi.fn(),
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: '' }),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
		fetchActiveModels: vi.fn().mockResolvedValue([]),
		fetchPresets: vi.fn().mockResolvedValue([]),
		fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
		bulkDeleteGenerations: vi.fn().mockResolvedValue({ deleted: 1 })
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

async function renderView(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(SongDetailView, { target }));
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

function tablist(target: HTMLElement): HTMLElement {
	const el = target.querySelector<HTMLElement>('[role="tablist"]');
	if (!el) throw new Error('Expected Recipe | Takes switch');
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

beforeEach(() => {
	resetNavigationForTests();
	pendingSource.set(null);
	pinnedSeed.set(null);
	clearSelection();
	songList.set([song()]);
	selectedSongId.set('s1');
	selectedGenerationId.set(null);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetNavigationForTests();
	pendingSource.set(null);
	pinnedSeed.set(null);
	clearSelection();
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	songList.set([]);
	delete document.documentElement.dataset.pointer;
	vi.unstubAllGlobals();
});

describe('SongDetailView recipe and takes', () => {
	it('exposes Recipe | Takes and does not treat Co-Writer as a peer tab', async () => {
		const target = await renderView();
		const switchText = tablist(target).textContent ?? '';
		expect(switchText).toContain(SONG_SURFACE_RECIPE);
		expect(switchText).toContain(SONG_SURFACE_TAKES);
		expect(switchText).not.toContain(SONG_SURFACE_COWRITER);
		expect(target.querySelector('.recipe-pane.hidden')).not.toBeNull();
		expect(target.querySelector('.takes-pane.hidden')).toBeNull();

		clickNamed(tablist(target), SONG_SURFACE_RECIPE);
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(target.querySelector('.recipe-pane.hidden')).toBeNull();
		expect(target.querySelector('.takes-pane.hidden')).not.toBeNull();
		expect(target.querySelector('.generate-btn')).not.toBeNull();
		expect(tablist(target).textContent).not.toContain(SONG_SURFACE_COWRITER);
		expect(target.querySelector('.cowriter-open')?.textContent).toContain(SONG_SURFACE_COWRITER);

		clickNamed(target, SONG_SURFACE_COWRITER);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.querySelector('.cowriter-layer.open')).not.toBeNull();
		expect(tablist(target).querySelectorAll('[role="tab"]')).toHaveLength(2);
	});

	it('keeps the take inspector in the song workspace', async () => {
		selectedGenerationId.set('g1');
		const target = await renderView();
		expect(visibleText(target)).toContain('Local Only');
		expect(visibleText(target)).toContain('Take 1');
		expect(target.querySelector('.back-btn')).toBeNull();
		expect(tablist(target).textContent).toContain(SONG_SURFACE_RECIPE);
		expect(target.querySelector('.inspector')).not.toBeNull();

		const closeBtn = target.querySelector<HTMLButtonElement>('.inspector .close-btn');
		if (!closeBtn) throw new Error('Expected inspector close');
		closeBtn.click();
		await tick();
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(detailTab)).toBe('generations');
		expect(target.querySelector('.inspector')).toBeNull();
		expect(tablist(target)).not.toBeNull();
	});

	it('lands pendingSource, Again, and Repaint on Recipe', async () => {
		const target = await renderView();
		expect(get(detailTab)).toBe('generations');

		pendingSource.set({ generation: generation(), mode: 'repaint' });
		await tick();
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(target.querySelector('.recipe-pane.hidden')).toBeNull();
		expect(target.textContent).toContain('Source: Gen #1');
		expect(target.querySelector('.generate-btn')).not.toBeNull();

		clickNamed(tablist(target), SONG_SURFACE_TAKES);
		await tick();
		clickNamed(target, TAKE_AGAIN_LABEL);
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(get(pinnedSeed)).toBe(7);
		expect(get(editGenParams)).toEqual({ inference_steps: 8, guidance_scale: 1.5 });
		expect(target.querySelector('.pinned-seed')?.textContent).toContain('seed:7');
		expect(target.textContent).not.toContain('Source: Gen #1');

		clickNamed(tablist(target), SONG_SURFACE_TAKES);
		await tick();
		clickNamed(target, TAKE_REPAINT_LABEL);
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(target.textContent).toContain('Source: Gen #1');
		expect(target.querySelector('.mode-btn.active')?.textContent).toContain(TAKE_REPAINT_LABEL);

		clickNamed(tablist(target), SONG_SURFACE_TAKES);
		await tick();
		clickNamed(target, TAKE_AUDIO_COVER_LABEL);
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(target.textContent).toContain('Source: Gen #1');
		expect(target.querySelector('.mode-btn.active')?.textContent).toContain('Cover');
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
		clickNamed(target, TAKE_AGAIN_LABEL);
		await tick();
		expect(get(detailTab)).toBe('edit');
		expect(get(pinnedSeed)).toBe(11);
		expect(get(editGenParams)).toEqual({ inference_steps: 12, guidance_scale: 2 });
		expect(target.querySelector('.pinned-seed')?.textContent).toContain('seed:11');
	});

	it('closes Co-Writer when leaving Recipe in stacked mode', async () => {
		const target = await renderView();
		clickNamed(tablist(target), SONG_SURFACE_RECIPE);
		await tick();
		clickNamed(target, SONG_SURFACE_COWRITER);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.querySelector('.cowriter-layer.open')).not.toBeNull();
		expect(target.querySelector('.cowriter-sheet')?.getAttribute('aria-modal')).toBe('true');

		document.body.tabIndex = 0;
		document.body.focus();
		const trapped = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
		window.dispatchEvent(trapped);
		expect(trapped.defaultPrevented).toBe(true);

		clickNamed(tablist(target), SONG_SURFACE_TAKES);
		await tick();
		expect(target.querySelector('.cowriter-layer.open')).toBeNull();

		clickNamed(tablist(target), SONG_SURFACE_RECIPE);
		await tick();
		expect(target.querySelector('.cowriter-layer.open')).toBeNull();
	});

	it('clears the inspector when bulk delete includes the inspected take', async () => {
		selectedGenerationId.set('g1');
		persistLibraryHistory();
		expect(history.state.generationId).toBe('g1');
		const target = await renderView();
		expect(target.querySelector('.inspector')).not.toBeNull();
		toggleSelection('g1');
		await tick();
		clickNamed(target, 'Delete Selected');
		await tick();
		await Promise.resolve();
		await tick();
		expect(get(selectedGenerationId)).toBeNull();
		expect(history.state.generationId).toBeNull();
		expect(target.querySelector('.inspector')).toBeNull();
	});
});

describe('song workbench split', () => {
	let restorePanesRect: (() => void) | undefined;

	function stubDesktopPanes(width: number): { setWidth: (next: number) => void } {
		document.documentElement.dataset.pointer = 'fine';
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: false,
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			}))
		);
		const observers: ResizeObserverCallback[] = [];
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(cb: ResizeObserverCallback) {
					observers.push(cb);
				}
				observe() {}
				disconnect() {}
				unobserve() {}
			}
		);
		let panesWidth = width;
		const original = HTMLElement.prototype.getBoundingClientRect;
		restorePanesRect?.();
		HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
			if (this.classList.contains('panes')) {
				return new DOMRect(0, 0, panesWidth, 100);
			}
			return original.call(this);
		};
		restorePanesRect = () => {
			HTMLElement.prototype.getBoundingClientRect = original;
		};
		return {
			setWidth: (next: number) => {
				panesWidth = next;
				for (const cb of observers) {
					cb([], {} as ResizeObserver);
				}
			}
		};
	}

	afterEach(() => {
		restorePanesRect?.();
		restorePanesRect = undefined;
	});

	it('splits only when both panes can be 360px after the gap', () => {
		const min = SONG_SPLIT_PANE_MIN_PX * 2 + SONG_SPLIT_PANE_GAP_PX;
		expect(canSplitSongPanes(SONG_SPLIT_PANE_MIN_PX * 2)).toBe(false);
		expect(canSplitSongPanes(min - 1)).toBe(false);
		expect(canSplitSongPanes(min)).toBe(true);
	});

	it('shows Recipe and Takes side by side only when the panes box fits both columns', async () => {
		const min = SONG_SPLIT_PANE_MIN_PX * 2 + SONG_SPLIT_PANE_GAP_PX;
		const panes = stubDesktopPanes(min - 1);
		const target = await renderView();
		expect(target.querySelector('.detail-panel.split')).toBeNull();
		expect(tablist(target)).not.toBeNull();

		panes.setWidth(min);
		await tick();
		expect(target.querySelector('.detail-panel.split')).not.toBeNull();
		expect(target.querySelector('[role="tablist"]')).toBeNull();
	});

	it('does not make split Co-Writer a modal or tab trap', async () => {
		stubDesktopPanes(SONG_SPLIT_PANE_MIN_PX * 2 + SONG_SPLIT_PANE_GAP_PX);
		const target = await renderView();
		expect(target.querySelector('.detail-panel.split')).not.toBeNull();
		clickNamed(target, SONG_SURFACE_COWRITER);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.querySelector('.cowriter-layer.open')).not.toBeNull();
		expect(target.querySelector('.cowriter-sheet')?.getAttribute('aria-modal')).toBe('false');

		document.body.tabIndex = 0;
		document.body.focus();
		const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
		window.dispatchEvent(tab);
		expect(tab.defaultPrevented).toBe(false);
	});
});

describe('recipe params from a take', () => {
	it('copies reusable params on Again', async () => {
		const { recipeParamsFromTake } = await import('$lib/stores/source');
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
