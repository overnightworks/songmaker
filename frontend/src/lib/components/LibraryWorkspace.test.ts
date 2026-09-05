import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '$lib/constants';
import { albumList, songList } from '$lib/stores/libraryData';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { EMPTY_RESOURCE_SYNC, resourceSync } from '$lib/stores/resourceSync';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';

const retryResourceSync = vi.hoisted(() => vi.fn(async () => true));

vi.mock('$app/navigation', () => ({ goto: vi.fn(), afterNavigate: vi.fn() }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/stores/resourceSync', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/resourceSync')>()),
	retryResourceSync
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
	fetchShares: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchVersions: vi.fn().mockResolvedValue([]),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));

import LibraryWorkspace from './LibraryWorkspace.svelte';

const ALBUM_TITLE = 'Anfield';

function album(): AlbumItem {
	return {
		id: 'anfield',
		title: ALBUM_TITLE,
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 0,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false
	};
}

function song(): SongItem {
	return {
		id: 'stadion-lauf-a',
		slug: 'stadion-lauf-a',
		title: 'Stadionlauf A',
		album_id: 'anfield',
		album_title: ALBUM_TITLE,
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		version_count: 0,
		generation_count: 0,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		generations: []
	};
}

const mounted: Array<ReturnType<typeof mount>> = [];

function renderWorkspace(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWorkspace, { target }));
	return target;
}

function streamLive(): void {
	resourceSync.set({ ...EMPTY_RESOURCE_SYNC, status: 'live', ready: true });
}

beforeEach(() => {
	retryResourceSync.mockClear();
	resourceSync.set({ ...EMPTY_RESOURCE_SYNC });
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetCollectionForTests();
	albumList.set([album()]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
});

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	document.body.innerHTML = '';
	resourceSync.set({ ...EMPTY_RESOURCE_SYNC });
});

describe('the library workspace', () => {
	it('waits while the live stream has not delivered its first snapshot', () => {
		const target = renderWorkspace();

		expect(target.textContent).toContain('Loading...');
	});

	it('states the failure and offers a retry when the stream never came up', async () => {
		resourceSync.set({ ...EMPTY_RESOURCE_SYNC, status: 'error', error: 'Stream refused' });

		const target = renderWorkspace();
		expect(target.textContent).toContain('Stream refused');

		target.querySelector<HTMLButtonElement>('.retry-btn')?.click();
		expect(retryResourceSync).toHaveBeenCalled();
		expect(target.textContent).not.toContain(RESOURCE_SYNC_ERROR + LIBRARY_RETRY_LABEL);
	});

	// What makes swapping between the workspace's two addresses free
	// (issue #269): the second mount reads the stream that is already live
	// instead of bootstrapping again, so it shows the library on its first
	// frame rather than flashing the Loading gate over it.
	it('shows the library on its first frame when the stream is already live', async () => {
		streamLive();
		openCollection.set({ kind: 'album', id: 'anfield' });
		const first = renderWorkspace();
		await tick();
		expect(first.textContent).toContain(ALBUM_TITLE);

		const second = renderWorkspace();

		expect(second.textContent).not.toContain('Loading...');
		expect(second.textContent).toContain(ALBUM_TITLE);
	});

	it('keeps showing the library when the stream errors after it was live', async () => {
		streamLive();
		const target = renderWorkspace();
		await tick();

		resourceSync.set({
			...EMPTY_RESOURCE_SYNC,
			status: 'error',
			error: 'Lost the stream',
			ready: true
		});
		await tick();

		expect(target.textContent).toContain('Lost the stream');
		expect(target.querySelector('.library-root')).not.toBeNull();
	});

	it('starts song and take content at the editor header without a sibling collection row', async () => {
		streamLive();
		openCollection.set({ kind: 'album', id: 'anfield' });
		songList.set([song()]);
		selectedSongId.set('stadion-lauf-a');
		const target = renderWorkspace();
		await tick();

		const workspace = target.querySelector('.main');
		expect(workspace?.firstElementChild).toHaveClass('detail-panel');
		expect(workspace?.querySelector('.detail-header')).not.toBeNull();
		expect(workspace?.querySelector('[aria-label="Breadcrumb"]')).not.toBeNull();
		expect(workspace?.querySelector('.library-row-scrim')).toBeNull();

		selectedGenerationId.set('take-1');
		await tick();
		expect(workspace?.firstElementChild).toHaveClass('detail-panel');
		expect(workspace?.querySelector('.detail-header')).not.toBeNull();
		expect(workspace?.querySelector('[aria-label="Breadcrumb"]')).not.toBeNull();
		expect(workspace?.querySelector('.library-row-scrim')).toBeNull();
	});
});
