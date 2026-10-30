import { resetLibraryWriteForTests } from '#lib/stores/libraryWrite.ts';
import {
	makeAlbum as album,
	makePlaylist as playlist,
	makeSong as song
} from '#lib/test-utils/factories.ts';
import { browserReportsOnline } from '#lib/test-utils/network.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '#lib/constants.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { openCollection, resetCollectionForTests } from '#lib/stores/collection.ts';
import { librarySurface, resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { resetResourceSyncForTests, resourceSync } from '#lib/stores/resourceSync.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';

const retryResourceSync = vi.hoisted(() => vi.fn(async () => true));

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/stores/resourceSync.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/resourceSync.ts')>()),
	retryResourceSync
}));
vi.mock('#lib/api/library.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/library.ts')>()),
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchVersions: vi.fn().mockResolvedValue([]),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));

import LibraryWorkspace from './LibraryWorkspace.svelte';

const ALBUM_TITLE = 'Anfield';

const mounted: Array<ReturnType<typeof mount>> = [];

function renderWorkspace(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWorkspace, { target }));
	return target;
}

function streamLive(): void {
	resourceSync.update((state) => ({ ...state, status: 'live', ready: true }));
}

beforeEach(() => {
	resetLibraryWriteForTests();
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => Response.json({ items: [] }))
	);
	retryResourceSync.mockClear();
	resetResourceSyncForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetCollectionForTests();
	albumList.set([
		album({ id: 'anfield', title: ALBUM_TITLE, song_count: 0, share_slug: null, cover: null })
	]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
});

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	resetPlaylistsForTests();
	document.body.innerHTML = '';
	resetResourceSyncForTests();
	resetConnectivityForTests();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe('the library workspace', () => {
	it('waits while the live stream has not delivered its first snapshot', () => {
		const target = renderWorkspace();

		expect(target.textContent).toContain('Loading...');
	});

	it('states the failure and offers a retry when the stream never came up', async () => {
		resourceSync.update((state) => ({ ...state, status: 'error', error: 'Stream refused' }));

		const target = renderWorkspace();
		expect(target.textContent).toContain('Stream refused');

		target.querySelector<HTMLButtonElement>('.retry-btn')?.click();
		expect(retryResourceSync).toHaveBeenCalled();
		expect(target.textContent).not.toContain(RESOURCE_SYNC_ERROR + LIBRARY_RETRY_LABEL);
	});

	it('waits under the offline strip instead of showing a failure when the stream could not come up offline', async () => {
		browserReportsOnline(false);
		resourceSync.update((state) => ({ ...state, status: 'error', error: null }));

		const target = renderWorkspace();
		expect(target.textContent).toContain('Loading...');
		expect(target.querySelector('[role="alert"]')).toBeNull();

		browserReportsOnline(true);
		await tick();
		expect(target.querySelector('[role="alert"]')?.textContent).toContain(RESOURCE_SYNC_ERROR);
	});

	it('shows no banner over a working library when a live refresh fails for lack of a network', async () => {
		streamLive();
		const target = renderWorkspace();
		await vi.waitFor(() => expect(target.querySelector('.library-root')).not.toBeNull());

		resourceSync.update((state) => ({ ...state, status: 'error', error: null, ready: true }));
		await tick();

		expect(target.querySelector('.library-root > [role="alert"]')).toBeNull();
		expect(target.querySelector('.library-root')).not.toBeNull();
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

	// #1402: the Playlists page's own surface.
	it('shows the wall of playlists alone on the Playlists surface', async () => {
		streamLive();
		playlistList.set([playlist({ id: 'p1', title: 'Night Drive', share_slug: null })]);
		playlistLoad.set({ status: 'ready', error: null });
		librarySurface.set('playlists');

		const target = renderWorkspace();
		await tick();

		const titles = [...target.querySelectorAll('.wall-tile .tile-title')];
		expect(titles.map((title) => title.textContent)).toEqual(['Night Drive']);
		expect(target.querySelector('.library-wall h1')?.getAttribute('aria-label')).toBe(
			'Playlists · 1'
		);
	});

	// #1506: Home's own surface, which shows no album page even while an album
	// stays the rail context behind it.
	it('1354_rule_31 1354_rule_14: shows Home with Listen and Write on the Home surface, also while an album stays the rail context', async () => {
		streamLive();
		openCollection.set({ kind: 'album', id: 'anfield' });
		librarySurface.set('home');

		const target = renderWorkspace();
		await tick();

		expect(target.querySelector('.library-home h1')?.textContent).toBe('Home');
		expect(
			[...target.querySelectorAll('section[aria-label]')].map((region) =>
				region.getAttribute('aria-label')
			)
		).toEqual(['Listen', 'Write']);
		expect(target.querySelector('.library-wall')).toBeNull();
		expect(target.textContent).not.toContain(ALBUM_TITLE);
	});

	it("1354_rule_31 1354_rule_14: shows the wall of albums, without Home's Listen, on the Library surface", async () => {
		streamLive();
		librarySurface.set('browse');

		const target = renderWorkspace();
		await tick();

		expect(target.querySelector('.library-wall h1')?.textContent).toContain('Library');
		expect(target.querySelector('[aria-label="Listen"]')).toBeNull();
	});

	it('keeps showing the library when the stream errors after it was live', async () => {
		streamLive();
		const target = renderWorkspace();
		await tick();

		resourceSync.update((state) => ({
			...state,
			status: 'error',
			error: 'Lost the stream',
			ready: true
		}));
		await tick();

		expect(target.textContent).toContain('Lost the stream');
		expect(target.querySelector('.library-root')).not.toBeNull();
	});

	it('starts song and take content at the editor header without a sibling collection row', async () => {
		streamLive();
		openCollection.set({ kind: 'album', id: 'anfield' });
		songList.set([
			song({
				id: 'stadion-lauf-a',
				slug: 'stadion-lauf-a',
				title: 'Stadionlauf A',
				album_id: 'anfield',
				album_title: ALBUM_TITLE,
				version_count: 0,
				generation_count: 0
			})
		]);
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
