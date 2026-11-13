import { mount, tick, unmount } from 'svelte';
import { vi } from 'vitest';
import { addGenerationToPlaylist } from '#lib/api/client.ts';
import type { GenerationItem, JobItem, SongItem } from '#lib/api/types.ts';
import { COMPACT_LAYOUT_MEDIA, LIBRARY_NARROW_MEDIA } from '#lib/constants/media.ts';
import SongDetailView from '#lib/components/SongDetailView.svelte';
import { makeGeneration, makeSong } from '#lib/test-utils/factories.ts';
import { resetSongDetailApi } from '#lib/test-utils/song-detail-mocks.ts';
import { clearHitboxStyles, clearPointer } from '#lib/test-utils/hitbox.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { discardDraft, pendingVersionLoad, versionDeleteRequest } from '#lib/stores/editor.ts';
import { activeJobs, generationFailures } from '#lib/stores/jobs.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { loras } from '#lib/stores/loras.ts';
import { resetNavigationForTests } from '#lib/stores/navigation.ts';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { playlistList, playlistLoad } from '#lib/stores/playlists.ts';
import { pendingTakeUse, recipeModel, recipeOpen, seedFromTake } from '#lib/stores/recipe.ts';
import { clearSelection } from '#lib/stores/selection.ts';
import { addToast } from '#lib/stores/toast.ts';

export function sourceRecipeDefaults(): Partial<GenerationItem> {
	return { generation_params: { inference_steps: 8, guidance_scale: 1.5 } };
}

export function editableSongDefaults(): Partial<SongItem> {
	return {
		album_id: 'a-local',
		album_title: 'Local Album',
		lyrics: 'verse',
		prompt: 'dark folk',
		generations: [makeGeneration(sourceRecipeDefaults())]
	};
}

export function jobStatus(overrides: Partial<JobItem> = {}): JobItem {
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

export const mounted: Array<ReturnType<typeof mount>> = [];

export async function settleRender(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
}

export async function renderView(options: { widthPx?: number } = {}): Promise<HTMLElement> {
	const target = document.createElement('div');
	if (options.widthPx !== undefined) {
		target.style.width = `${options.widthPx}px`;
		target.style.maxWidth = `${options.widthPx}px`;
	}
	document.body.append(target);
	mounted.push(mount(SongDetailView, { target }));
	await settleRender();
	return target;
}

export function writeSaveButton(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('.write-save .save-btn');
	if (!button) throw new Error('Expected the write-surface Save button');
	return button;
}

export function clickNamed(target: HTMLElement, name: string): void {
	const button = Array.from(target.querySelectorAll('button')).find(
		(el) => el.textContent?.replace(/\s+/g, ' ').trim() === name
	);
	if (!button) throw new Error(`Expected button "${name}"`);
	button.click();
}

export function stubLibraryMedia(options: { narrow: boolean; compact?: boolean }): void {
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

/** The stores and mocks every song page test starts from: one song, `s1`, selected. */
export function resetSongDetailState(): void {
	Element.prototype.scrollIntoView = vi.fn();
	// defect:#1598: a background load preserves dirty drafts; reset through the owner.
	discardDraft();
	resetNavigationForTests();
	pendingTakeUse.set(null);
	seedFromTake.set(null);
	recipeOpen.set(false);
	recipeModel.set(null);
	clearSelection();
	songList.set([makeSong(editableSongDefaults())]);
	selectedSongId.set('s1');
	selectedGenerationId.set(null);
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
	resetSongDetailApi();
	loras.set([]);
	activeJobs.set([]);
	generationFailures.set({});
	vi.stubGlobal('EventSource', MockEventSource);
	vi.mocked(addToast).mockClear();
}

export async function clearSongDetailState(): Promise<void> {
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
}
