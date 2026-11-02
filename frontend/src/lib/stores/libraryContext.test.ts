import {
	historyEntry,
	historyLength,
	mountAddressRoute,
	mountRouteUnderKeptPage,
	pressBack,
	pressForward,
	reloadLibraryPage,
	reloadLibraryPageBeforeRouterStarts,
	replaceHistoryEntry,
	standingHistoryEntry
} from '#lib/test-utils/library-history.ts';
import {
	makeAlbum as album,
	makeGeneration as generation,
	makePlaylist as playlistItem,
	makePlaylistDetail as playlistDetail,
	makeSong as song
} from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistDetailItem } from '#lib/api/types.ts';
import { ApiError } from '#lib/api/fetch.ts';
import { LIBRARY_HISTORY_KIND } from '#lib/constants.ts';
import { openCollection, setOpenCollection, type OpenCollection } from '#lib/stores/collection.ts';
import {
	libraryBrowse,
	librarySearch,
	searchQuery,
	librarySort,
	loadLibraryBrowse,
	resetLibrarySearchForTests
} from '#lib/stores/librarySearch.ts';
import {
	albumList,
	allAlbumsLoad,
	ensureAllAlbumsLoaded,
	songList
} from '#lib/stores/libraryData.ts';
import { selectSong } from '#lib/stores/navigation.ts';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import {
	playlistList,
	playlistLoad,
	resetPlaylistsForTests,
	selectedPlaylistDetail
} from '#lib/stores/playlists.ts';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const searchLibrary = vi.fn();

// Only the route-shape crossing suite below drives a write that actually
// crosses (every other test in this file sets window.location to the write's
// own target first, so its write is same-shape and never reaches this) --
// mocked the same way navigation.test.ts does, so a crossing write's `goto`
// call moves the URL like the real one does.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);

vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));
vi.mock('#lib/api/albums.ts', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));
// player.ts's ensureGenerationsLoaded, which openTakeAddress uses to resolve
// a take number against the song's full generations, fetches through this
// module's fetchSong rather than #lib/api/songs's -- both share the fetchSong
// spy below so a test only has to program one mocked response either way.
vi.mock('#lib/api/client.ts', () => ({
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue(null),
	fetchActiveGeneration: vi.fn().mockResolvedValue(null),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn()
}));

import { goto, pushState, replaceState } from '$app/navigation';
import {
	attachLandingHandler,
	installHistoryController,
	pushEntry,
	replaceEntry
} from '#lib/history/historyController.ts';
import { holdLayer } from '#lib/stores/layers.ts';
import { fakePage, holdRouteLoads, landed } from '#lib/test-utils/app-navigation.ts';
import {
	albumRoutePath,
	HOME_ROUTE_PATH,
	LIBRARY_ROUTE_PATH,
	songRoutePath
} from '#lib/routes/addresses.ts';

import {
	applyLibraryHistory,
	cancelLibraryHistoryApply,
	captureLibraryScroll,
	currentLibraryHistoryState,
	detailTab,
	holdLibraryRestoresUntil,
	hydrateLibraryFromHistory,
	isLibraryHistoryState,
	keepLibraryPageAsLeft,
	libraryHistoryEntry,
	libraryHistoryUrl,
	librarySurface,
	openAlbumAddress,
	openHomeAddress,
	openPlaylistAddress,
	openPlaylistsAddress,
	openLibraryAddress,
	libraryScrollAnchor,
	libraryScrollRestore,
	openSongAddress,
	openTakeAddress,
	resolveLegacySongQueryAddress,
	libraryRootState,
	rememberedSongTab,
	resetLibraryContextForTests,
	setLibrarySurface,
	showSongTab,
	snapshotLibraryHistory,
	takePlaceReturnedFrom,
	writeLibraryHistory,
	type LibraryHistoryState
} from './libraryContext';

// A library entry as it reaches the router: the library beside the entry the
// history controller stamped, known by its id (issue #1006).
function stampedLibrary(library: LibraryHistoryState): App.PageState {
	return { library, entry: expect.objectContaining({ id: expect.any(Number) }) };
}

function emptyPage<T>(items: T[] = []) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: false };
}

function albumSnapshot(id: string): { kind: 'album'; id: string } {
	return { kind: 'album', id };
}

beforeEach(() => {
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchAlbum.mockReset();
	fetchAlbums.mockReset();
	fetchSong.mockReset();
	fetchSongs.mockReset();
	searchLibrary.mockReset();
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue(
		playlistDetail({ title: 'P', slug: 'p', entry_count: 0, share_slug: null })
	);
	fetchAlbums.mockResolvedValue(emptyPage());
	fetchSongs.mockResolvedValue({ ...emptyPage(), limit: 200 });
	searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchAlbum.mockResolvedValue(album({ id: 'a9', title: 'Remote' }));
	fetchSong.mockResolvedValue(
		song({
			title: 'Tide',
			generation_count: 0,
			slug: 's9',
			id: 's9',
			album_id: 'a9',
			album_title: 'Remote'
		})
	);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	searchQuery.set('');
	albumList.set([]);
	allAlbumsLoad.set({ status: 'idle', error: null });
	songList.set([]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	playlistLoad.set({ status: 'idle', error: null });
	replaceHistoryEntry('/');
	vi.mocked(goto).mockClear();
	vi.mocked(pushState).mockClear();
	vi.mocked(replaceState).mockClear();
	installHistoryController();
	attachLandingHandler(() => undefined);
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
});

describe('library history snapshot', () => {
	it('round-trips the mixed library query, sort, collection, and scroll', () => {
		searchQuery.set('Tide');
		librarySort.set('oldest');
		selectedSongId.set('s1');
		captureLibraryScroll(240);
		libraryBrowse.set({
			status: 'ready',
			error: null,
			albumHasMore: true,
			songHasMore: false,
			albumOffset: 50,
			songOffset: 200
		});

		const snap = snapshotLibraryHistory(3);
		expect(snap).toMatchObject({
			kind: LIBRARY_HISTORY_KIND,
			index: 3,
			surface: 'browse',
			query: 'Tide',
			sort: 'oldest',
			albumOffset: 50,
			songOffset: 200,
			songId: 's1',
			scrollAnchor: 240,
			detailTab: 'edit'
		});
		expect(isLibraryHistoryState(snap)).toBe(true);
	});

	// Issue #1289: another page pushed over a library page finds it as it
	// was left once Back returns to it.
	it('keeps where the library page history stands on was left in its entry', async () => {
		const albumPage: LibraryHistoryState = {
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'album', id: 'a1' }
		};
		replaceHistoryEntry('/album/a1', albumPage);
		librarySurface.set('browse');
		captureLibraryScroll(240);
		const entries = historyLength();

		await keepLibraryPageAsLeft();

		expect(historyEntry()).toEqual({ ...albumPage, scrollAnchor: 240 });
		expect(historyLength()).toBe(entries);
		expect(location.pathname).toBe('/album/a1');
	});

	it('keeps nothing on a page outside the library', async () => {
		replaceHistoryEntry('/settings/voices');
		captureLibraryScroll(240);

		await keepLibraryPageAsLeft();

		expect(historyEntry()).toBeNull();
		expect(location.pathname).toBe('/settings/voices');
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
	});

	it('does not snapshot a previous search page count onto a new query', () => {
		searchQuery.set('new');
		librarySearch.set({
			q: 'old',
			status: 'ready',
			error: null,
			items: [
				{ type: 'album', album: album() },
				{ type: 'album', album: album({ id: 'a2' }) }
			],
			hasMore: true,
			nextCursor: 'cursor-old'
		});

		const snap = snapshotLibraryHistory(1);

		expect(snap.query).toBe('new');
		expect(snap.searchLoadedCount).toBe(0);
		expect(snap.searchCursor).toBeNull();
	});

	it('rejects legacy section-based blobs so restore falls back to root', () => {
		expect(isLibraryHistoryState(null)).toBe(false);
		expect(
			isLibraryHistoryState({
				kind: LIBRARY_HISTORY_KIND,
				index: 0,
				section: 'albums',
				browseTrackAlbumId: null
			})
		).toBe(false);
		expect(isLibraryHistoryState(libraryRootState())).toBe(true);
	});

	it('rejects a malformed collection snapshot', () => {
		expect(
			isLibraryHistoryState({ ...libraryRootState(), collection: { kind: 'song', id: 'x' } })
		).toBe(false);
		expect(
			isLibraryHistoryState({ ...libraryRootState(), collection: { kind: 'album', id: 'a1' } })
		).toBe(true);
	});
});

describe('applyLibraryHistory', () => {
	it('defect:#1354: issues a fresh scroll restore request for every landing, also at an equal offset', async () => {
		const state = { ...libraryRootState(), scrollAnchor: 240 };
		await applyLibraryHistory(state);
		const first = get(libraryScrollRestore);
		await applyLibraryHistory(state);
		const second = get(libraryScrollRestore);

		expect(first).toEqual({ top: 240 });
		expect(second).toEqual({ top: 240 });
	});

	it('hydrates an album collection that is not yet loaded', async () => {
		const state = { ...libraryRootState(), collection: { kind: 'album' as const, id: 'a9' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a9' });
		expect(get(albumList).some((a) => a.id === 'a9')).toBe(true);
	});

	it.each([
		{ surface: 'detail' as const, songsLoaded: true },
		{ surface: 'browse' as const, songsLoaded: false }
	])(
		'loads the open album songs only where the landing surface shows them ($surface)',
		async ({ surface, songsLoaded }) => {
			fetchSongs.mockImplementation(async (albumId?: string) => ({
				...emptyPage(albumId === 'a9' ? [song({ id: 's9', album_id: 'a9' })] : []),
				limit: 200
			}));

			await applyLibraryHistory({
				...libraryRootState(),
				surface,
				collection: { kind: 'album', id: 'a9' }
			});

			expect(get(songList).some((item) => item.album_id === 'a9')).toBe(songsLoaded);
		}
	);

	it('restores browse pages even when a search query is replayed', async () => {
		fetchAlbums.mockResolvedValue(emptyPage([album()]));
		searchLibrary.mockResolvedValue({
			items: [{ type: 'album', album: album({ id: 'a-hit' }) }],
			next_cursor: null,
			has_more: false
		});

		await applyLibraryHistory({ ...libraryRootState(), query: 'Tide' });

		expect(fetchAlbums).toHaveBeenCalled();
		expect(searchLibrary).toHaveBeenCalled();
		expect(get(albumList).map((item) => item.id)).toEqual(['a1']);
		expect(get(librarySearch).items).toHaveLength(1);
	});

	it('hydrates a playlist collection via loadPlaylistDetail', async () => {
		fetchPlaylist.mockResolvedValueOnce(
			playlistDetail({ slug: 'p', entry_count: 0, share_slug: null, title: 'Night Drive' })
		);
		const state = { ...libraryRootState(), collection: { kind: 'playlist' as const, id: 'p1' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistDetail)?.title).toBe('Night Drive');
	});

	it('clears a playlist collection that no longer exists', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'gone', '/api/playlists/gone'));
		const state = { ...libraryRootState(), collection: { kind: 'playlist' as const, id: 'gone' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toBeNull();
		expect(get(selectedPlaylistDetail)).toBeNull();
	});

	it('lets a newer history restore win over an in-flight playlist fetch', async () => {
		let resolveFirst: ((value: PlaylistDetailItem) => void) | undefined;
		fetchPlaylist.mockImplementationOnce(
			() =>
				new Promise<PlaylistDetailItem>((resolve) => {
					resolveFirst = resolve;
				})
		);
		fetchPlaylist.mockResolvedValueOnce(
			playlistDetail({ slug: 'p', entry_count: 0, share_slug: null, id: 'p2', title: 'Second' })
		);
		const first = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'playlist', id: 'p1' }
		});
		const second = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'playlist', id: 'p2' }
		});
		await second;
		resolveFirst?.(playlistDetail({ slug: 'p', entry_count: 0, share_slug: null, title: 'First' }));
		await first;
		expect(get(selectedPlaylistDetail)?.id).toBe('p2');
	});

	it("applies nothing once a write cancelled it while Back put the song's entry back", async () => {
		let releaseHold: () => void = () => undefined;
		void holdLibraryRestoresUntil(new Promise<void>((resolve) => (releaseHold = resolve)));
		const held = applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's1' });

		cancelLibraryHistoryApply();
		releaseHold();

		expect(await held).toBe(false);
		expect(get(librarySurface)).toBe('browse');
		expect(get(selectedSongId)).toBeNull();
	});

	it('keeps a newer restore collection when an earlier album resolution finishes late', async () => {
		let resolveAlbum: ((value: AlbumItem) => void) | undefined;
		fetchAlbum.mockImplementationOnce(
			() =>
				new Promise<AlbumItem>((resolve) => {
					resolveAlbum = resolve;
				})
		);

		const first = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'album', id: 'a1' }
		});
		await vi.waitFor(() => expect(resolveAlbum).toBeTypeOf('function'));
		const second = applyLibraryHistory(libraryRootState());
		await second;
		resolveAlbum?.(album());
		await expect(first).resolves.toBe(false);

		expect(get(openCollection)).toBeNull();
		expect(get(albumList).some((item) => item.id === 'a1')).toBe(false);
	});

	it('keeps a newer selected song when an earlier song lookup finishes late', async () => {
		let rejectSong: ((reason: Error) => void) | undefined;
		fetchSong.mockImplementationOnce(
			() =>
				new Promise((_, reject) => {
					rejectSong = reject;
				})
		);
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				slug: 's2',
				id: 's2',
				album_id: 'a9'
			})
		);

		const first = applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's1' });
		await vi.waitFor(() => expect(rejectSong).toBeTypeOf('function'));
		const second = applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's2' });
		await expect(second).resolves.toBe(true);
		rejectSong?.(new ApiError(404, 'gone', '/api/songs/s1'));
		await expect(first).resolves.toBe(false);

		expect(get(selectedSongId)).toBe('s2');
	});

	// Issue #1006 H5: an apply belongs to the entry it landed on, so a Back that
	// leaves that entry stops it even when nothing in the library heard the Back
	// -- the second of two quick Backs from Settings.
	it('applies nothing more once history has left the entry it landed on', async () => {
		let resolveAlbum: ((value: AlbumItem) => void) | undefined;
		fetchAlbum.mockImplementationOnce(
			() => new Promise<AlbumItem>((resolve) => (resolveAlbum = resolve))
		);
		replaceEntry(LIBRARY_ROUTE_PATH, { library: libraryRootState() });
		const albumState = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a1' }
		};
		pushEntry(albumRoutePath('a1'), { library: albumState });
		const applying = applyLibraryHistory(albumState);
		await vi.waitFor(() => expect(resolveAlbum).toBeTypeOf('function'));

		await pressBack();
		resolveAlbum?.(album());

		await expect(applying).resolves.toBe(false);
		expect(get(albumList).some((item) => item.id === 'a1')).toBe(false);
		// Back to the top entry: a later push must not cut an entry above it.
		await pressForward();
	});

	// Issue #1267: the song's apply joins the album-songs lookup the song itself
	// started; that lookup refused while history moves on must not fail the
	// apply -- and with it the library's snapshot -- but leave the screen to the
	// entry history landed on.
	it('stops quietly when the album songs lookup it joined is refused after history left the entry', async () => {
		albumList.set([album({ id: 'a1' })]);
		const listed = song({ id: 's1', album_id: 'a1', generation_count: 0, generations: [] });
		let refuseSongs: ((reason: unknown) => void) | undefined;
		fetchSongs.mockImplementation(async (albumId?: string) => {
			if (albumId !== 'a1') return { ...emptyPage([listed]), limit: 200 };
			return new Promise((_, reject) => (refuseSongs = reject));
		});
		replaceEntry(LIBRARY_ROUTE_PATH, { library: libraryRootState() });
		const songState = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a1' },
			songId: 's1'
		};
		pushEntry(songRoutePath('a1', 's1'), { library: songState });
		const applying = applyLibraryHistory(songState);
		await vi.waitFor(() => expect(refuseSongs).toBeTypeOf('function'));

		await pressBack();
		refuseSongs?.(new ApiError(500, 'boom', '/api/songs'));

		await expect(applying).resolves.toBe(false);
		await pressForward();
	});

	it('fetches the selected song when retained takes are fewer than generation_count', async () => {
		songList.set([
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				slug: 's9',
				id: 's9',
				album_id: 'a9',
				generation_count: 2,
				generations: [generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 })]
			})
		]);
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				slug: 's9',
				id: 's9',
				album_id: 'a9',
				generation_count: 2,
				generations: [
					generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 }),
					generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1, id: 'g2' })
				]
			})
		);
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			songId: 's9'
		});
		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(
			get(songList)
				.find((item) => item.id === 's9')
				?.generations.map((item) => item.id)
		).toEqual(['g1', 'g2']);
	});

	it('keeps the selected song after a transient fetch error but clears it on 404', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchSong.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/songs/s9'));
		await applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's9' });
		expect(get(selectedSongId)).toBe('s9');

		fetchSong.mockRejectedValueOnce(new ApiError(404, 'gone', '/api/songs/s9'));
		await applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's9' });
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
	});

	it('defaults a missing detailTab to the Edit tab without failing restore', async () => {
		const { detailTab: recordedTab, ...withoutDetailTab } = libraryRootState();
		expect(recordedTab).toBe('edit');
		detailTab.set('takes');
		await applyLibraryHistory(withoutDetailTab);
		expect(get(detailTab)).toBe('edit');
		expect(get(librarySurface)).toBe('browse');
	});

	it.each([
		['write', 'edit'],
		['chat', 'cowriter'],
		['generations', 'takes']
	] as const)('restores an old %s history entry on the %s tab', async (legacy, restored) => {
		detailTab.set(restored === 'edit' ? 'takes' : 'edit');
		await applyLibraryHistory({ ...libraryRootState(), detailTab: legacy as never });
		expect(get(detailTab)).toBe(restored);
	});

	it('remembers the tab a restored song was shown on, and only for that song', async () => {
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			songId: 's9',
			detailTab: 'takes'
		});
		expect(rememberedSongTab('s9')).toBe('takes');
		expect(rememberedSongTab('s8')).toBe('edit');
	});

	it('forgets every remembered tab on reset', () => {
		showSongTab('s9', 'takes');
		resetLibraryContextForTests();
		expect(rememberedSongTab('s9')).toBe('edit');
	});
});

describe('hydrateLibraryFromHistory', () => {
	it('1354_rule_31: replaces history after hydrate so a deleted playlist is not replayed', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		replaceHistoryEntry('/', {
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'playlist', id: 'p-gone' }
		});
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/playlists/p-gone'));
		await hydrateLibraryFromHistory();
		expect(historyEntry().collection).toBeNull();
		expect(historyEntry().surface).toBe('browse');
		expect(location.pathname).toBe(LIBRARY_ROUTE_PATH);
	});

	// Regression for issue #281: on a cold tab with no LibraryHistoryState yet,
	// this falls back to its own restoreLibraryBrowse -- which a concurrent,
	// newer browse load (an address's own resolution racing the same bootstrap,
	// exactly like the branch above) can supersede. A superseded restore's own
	// `false` return is not a bootstrap failure; only libraryBrowse's own final
	// status says whether the library actually loaded. Getting this wrong
	// closed the live stream and showed "Library sync failed" on a real stack
	// every time a cold take open's extra generations fetch let it lose this
	// race -- see e2e/README.md's Guard rails section for the full story.
	it('reports success even when its own browse restore loses the race to a newer one', async () => {
		let resolveSuperseded: (() => void) | undefined;
		fetchAlbums.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveSuperseded = () => resolve(emptyPage());
				})
		);

		const hydrate = hydrateLibraryFromHistory();
		await loadLibraryBrowse({ reset: true });
		resolveSuperseded?.();

		await expect(hydrate).resolves.toBe(true);
		expect(get(libraryBrowse).status).toBe('ready');
	});

	describe('once a surface read every album', () => {
		beforeEach(async () => {
			fetchAlbums.mockResolvedValue(
				emptyPage([album({ id: 'a-kept', title: 'Kept' }), album({ id: 'a-gone', title: 'Gone' })])
			);
			await hydrateLibraryFromHistory();
			await ensureAllAlbumsLoaded();
			fetchAlbums.mockClear();
			fetchAlbums.mockResolvedValue(emptyPage([album({ id: 'a-kept', title: 'Kept' })]));
		});

		it('drops an album deleted elsewhere when a snapshot follows a gap in the stream', async () => {
			await expect(hydrateLibraryFromHistory()).resolves.toBe(true);

			expect(get(albumList).map((item) => item.id)).toEqual(['a-kept']);
		});

		it('reads only the first album page on history navigation', async () => {
			await applyLibraryHistory(libraryRootState());

			expect(fetchAlbums).toHaveBeenCalledTimes(1);
		});
	});
});

describe('libraryHistoryUrl', () => {
	it('addresses an open album by its slug', () => {
		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'friday-at-murphy-s' }
			})
		).toBe('/album/friday-at-murphy-s');
	});

	it('addresses an open song by its own slug under its album, not by id', () => {
		songList.set([
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				slug: 'tide',
				album_id: 'anfield'
			})
		]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'anfield' },
				songId: 's1'
			})
		).toBe('/album/anfield/tide');
	});

	it('addresses a selected take by its number under the song, not the query string', () => {
		songList.set([
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				slug: 'tide',
				album_id: 'anfield',
				generations: [
					generation({ mp3_path: '/audio/g1.mp3', seed: 1, song_id: 's1', generation_number: 3 })
				]
			})
		]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'anfield' },
				songId: 's1',
				generationId: 'g1'
			})
		).toBe('/album/anfield/tide/take/3');
	});

	it('falls back to the query appendage while the take is not yet among the loaded generations', () => {
		songList.set([
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				slug: 'tide',
				album_id: 'anfield'
			})
		]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'anfield' },
				songId: 's1',
				generationId: 'g1'
			})
		).toBe('/album/anfield/tide?gen=g1');
	});

	it('falls back to the legacy song address while the song is not yet known', () => {
		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'anfield' },
				songId: 's1'
			})
		).toBe('/?song=s1');
	});

	it.each([
		{
			surface: 'browse',
			retains: 'an album',
			collection: albumSnapshot('anfield'),
			path: LIBRARY_ROUTE_PATH
		},
		{
			surface: 'home',
			retains: 'an album',
			collection: albumSnapshot('anfield'),
			path: HOME_ROUTE_PATH
		},
		{ surface: 'home', retains: 'nothing', collection: null, path: HOME_ROUTE_PATH }
	] as const)(
		'1354_rule_31: addresses the $surface surface itself, with $retains as the rail context',
		({ surface, collection, path }) => {
			expect(libraryHistoryUrl({ ...libraryRootState(), surface, collection })).toBe(path);
		}
	);

	it('addresses an open playlist by its slug, not its id', () => {
		playlistList.set([playlistItem({ title: 'P', share_slug: null, slug: 'friday-night' })]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'p1' }
			})
		).toBe('/playlist/friday-night');
	});

	it('1354_rule_31: falls back to the library while the open playlist is not yet in playlistList', () => {
		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'p1' }
			})
		).toBe(LIBRARY_ROUTE_PATH);
	});

	// #1402: the Playlists page keeps the playlist open last as the rail
	// context, as the wall does, yet addresses only itself.
	it('addresses the Playlists page by its own path, whichever playlist stays the rail context', () => {
		playlistList.set([
			playlistItem({ title: 'P', share_slug: null, id: 'p1', slug: 'friday-night' })
		]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'playlists',
				collection: { kind: 'playlist', id: 'p1' }
			})
		).toBe('/playlists');
	});
});

// libraryRouteShape itself is not exported -- writeLibraryHistory's own
// crossing decision (a navigation vs. shallow routing) is the observable
// behaviour, so that is what these pin. Central to issue #265's S7: since
// ensureLibraryWorkspaceRoute (#264) was removed, writeLibraryHistory is the
// only thing left that can catch a write landing on a library address from a
// non-library route (Settings, login, a share page) -- and it can only catch
// it if leaving such a route always counts as a crossing, every time,
// regardless of which of the five library shapes the write lands on.
describe('writeLibraryHistory through the router (issues #265 S7, #1165)', () => {
	const albumState: LibraryHistoryState = {
		...libraryRootState(),
		surface: 'detail',
		collection: { kind: 'album', id: 'a2' }
	};

	// Issue #1165: the library already shows the page a crossing opens, so its
	// entry stands before the router has loaded the route, which `goto` then
	// mounts over that same entry.
	it('installs a crossing push from a library page at once, and mounts its route through goto over it', async () => {
		replaceHistoryEntry(albumRoutePath('a1'), {
			...albumState,
			collection: { kind: 'album', id: 'a1' }
		});
		const lengthBefore = historyLength();

		const written = writeLibraryHistory(libraryRootState(), songRoutePath('a1', 's1'), 'push');

		expect((await landed(location)).pathname).toBe(songRoutePath('a1', 's1'));
		expect(historyEntry()).toEqual(libraryRootState());
		await written;
		expect(goto).toHaveBeenCalledWith(songRoutePath('a1', 's1'), {
			replace: true,
			reset: false,
			state: stampedLibrary(libraryRootState())
		});
		expect(historyLength()).toBe(lengthBefore + 1);
		expect(historyEntry()).toEqual(libraryRootState());
	});

	// Issue #1263: a song tapped as soon as its album shows -- opened from the
	// wall, or left onto by the song before it -- while the router still mounts
	// the album's route. The library already shows the song, so its entry stands
	// in the same task; the song's route mounts over it once the router has
	// loaded it, and a Back then returns to the album.
	it.each([
		{ albumWrite: 'push', from: LIBRARY_ROUTE_PATH, fromState: libraryRootState() },
		{
			albumWrite: 'replace',
			from: songRoutePath('a2', 's9'),
			fromState: { ...albumState, songId: 's9' }
		}
	] as const)(
		"writes a push into history at once while the album's $albumWrite still mounts its route",
		async ({ albumWrite, from, fromState }) => {
			replaceHistoryEntry(from, fromState);
			const routesLoaded = holdRouteLoads();
			void writeLibraryHistory(albumState, albumRoutePath('a2'), albumWrite);
			const song = { ...albumState, index: 1, songId: 's1' };

			const songMounted = writeLibraryHistory(song, songRoutePath('a2', 's1'), 'push');

			expect((await landed(location)).pathname).toBe(songRoutePath('a2', 's1'));
			expect(historyEntry()).toEqual(song);
			const songEntry = standingHistoryEntry();
			routesLoaded();
			await songMounted;
			expect(fakePage.url.pathname).toBe(songRoutePath('a2', 's1'));
			expect(standingHistoryEntry()).toEqual(songEntry);
			expect(historyEntry()).toEqual(song);
			await pressBack();
			expect(location.pathname).toBe(albumRoutePath('a2'));
			expect(historyEntry()).toEqual(albumState);
		}
	);

	// A layer closing, or Go to song leaving a history layer, steps
	// back before the crossing it opens: once that step lands, the crossing's
	// entry stands, so a Back pressed while its route still loads returns to
	// the page underneath instead of stepping past it.
	it('installs a crossing push queued behind a step back the moment that step lands', async () => {
		await writeLibraryHistory(libraryRootState(), LIBRARY_ROUTE_PATH, 'replace');
		const leaveMenu = await landed(holdLayer('menu', () => undefined));
		const lengthBefore = historyLength();
		vi.mocked(goto).mockImplementationOnce(() => new Promise<void>(() => undefined));

		leaveMenu();
		void writeLibraryHistory({ ...albumState, index: 1 }, albumRoutePath('a2'), 'push');

		await vi.waitFor(() => expect(location.pathname).toBe(albumRoutePath('a2')));
		expect(historyEntry()).toEqual({ ...albumState, index: 1 });
		expect(historyLength()).toBe(lengthBefore);
		await pressBack();
		expect(location.pathname).toBe(LIBRARY_ROUTE_PATH);
		expect(historyEntry()).toEqual(libraryRootState());
	});

	// A layer opening over the new album while its route still loads stands at
	// once, so a Back pressed before the route has loaded closes it and keeps
	// the album. The router writes over whichever entry stands once the route
	// has loaded, so the mount is issued again over the layer's entry.
	it("gives a layer opened while the album's route still loads its entry at once, which Back closes and keeps the album", async () => {
		await writeLibraryHistory(libraryRootState(), LIBRARY_ROUTE_PATH, 'replace');
		vi.mocked(goto).mockImplementationOnce(() => new Promise<void>(() => undefined));
		await landed(void writeLibraryHistory(albumState, albumRoutePath('a2'), 'push'));
		const album = standingHistoryEntry();
		let menuClosed = false;

		await landed(holdLayer('menu', () => (menuClosed = true)));

		expect(standingHistoryEntry()).toEqual({ id: expect.any(Number), layer: 'menu' });
		expect(standingHistoryEntry()?.id).toBeGreaterThan(album?.id ?? Number.NaN);
		expect(historyEntry()).toEqual(albumState);
		await pressBack();
		expect(menuClosed).toBe(true);
		expect(standingHistoryEntry()).toEqual(album);
		expect(historyEntry()).toEqual(albumState);
		expect(location.pathname).toBe(albumRoutePath('a2'));
	});

	// A song-to-song move across album boundaries stays the 'album' shape on
	// both sides -- only the route-file depth decides a crossing, never which
	// album or song the address names.
	it.each([
		{ mode: 'push', write: pushState },
		{ mode: 'replace', write: replaceState }
	] as const)(
		'keeps same-shape churn shallow ($mode), and the entry reads back as the library',
		async ({ mode, write }) => {
			replaceHistoryEntry(albumRoutePath('a1'));

			await writeLibraryHistory(albumState, albumRoutePath('a2'), mode);

			expect(goto).not.toHaveBeenCalled();
			expect(write).toHaveBeenCalledWith(albumRoutePath('a2'), stampedLibrary(albumState));
			expect(historyEntry()).toEqual(albumState);
			expect(location.pathname).toBe(albumRoutePath('a2'));
		}
	);

	// The one pairing that used to fail silently before 'external' became its
	// own shape: a write landing on the Library (openLibraryWall's target, or
	// openPlaylist's own fallback before a playlist's slug is known) from
	// a non-library route both satisfied `!isAlbumRoutePath &&
	// !isPlaylistRoutePath`, so the two were indistinguishable and the write
	// took the cheap same-shape branch, which leaves the router mounting
	// whichever route file it last saw. The next Back/Forward or real
	// navigation that disagrees with that stale belief tears the workspace
	// down mid-session. This is the pairing #265's S7 had to get right for
	// removing ensureLibraryWorkspaceRoute to be safe.
	it('1354_rule_31: crosses through goto when the target is the Library and the write starts from a non-library route', async () => {
		replaceHistoryEntry('/settings/voices');

		await writeLibraryHistory(libraryRootState(), LIBRARY_ROUTE_PATH, 'push');

		expect(goto).toHaveBeenCalledWith(LIBRARY_ROUTE_PATH, {
			replace: false,
			reset: false,
			state: stampedLibrary(libraryRootState())
		});
	});
});

// SvelteKit's start writes its own entry over the one a page loads onto
// (issue #1165).
describe('a page load', () => {
	const playlistState: LibraryHistoryState = {
		...libraryRootState(),
		surface: 'detail',
		collection: { kind: 'playlist', id: 'p1' },
		scrollAnchor: 480
	};

	beforeEach(() => {
		mountAddressRoute('/playlist/p', playlistState);
	});

	it('puts the library its entry carried back onto the entry once the router started', async () => {
		await reloadLibraryPage();

		expect(historyEntry()).toEqual(playlistState);
		expect(location.pathname).toBe('/playlist/p');
		const loadedOnto = `${location.origin}/playlist/p`;
		const writes = vi.mocked(replaceState).mock.calls;
		expect(writes).toEqual([
			[loadedOnto, { entry: { id: expect.any(Number) } }],
			[loadedOnto, stampedLibrary(playlistState)]
		]);
		expect(new Set(writes.map(([, state]) => state.entry?.id)).size).toBe(1);
	});

	// Issue #1263: only history the controller has moving holds a write.
	it('writes within the task before the router reports its start, and the start keeps that newer library', async () => {
		const reportRouterStarted = reloadLibraryPageBeforeRouterStarts();
		const scrolled = { ...playlistState, scrollAnchor: 960 };
		void writeLibraryHistory(scrolled, '/playlist/p', 'replace');
		expect(historyEntry()).toEqual(scrolled);
		await landed(reportRouterStarted());
		expect(historyEntry()).toEqual(scrolled);
		expect(standingHistoryEntry()?.id).toBeDefined();
	});
});

describe('openSongAddress', () => {
	it('makes the library restore the addressed song on a tab that knows nothing else', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		mountAddressRoute('/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(historyEntry().songId).toBe('s9');
		expect(historyEntry().collection).toEqual({ kind: 'album', id: 'a9' });
		expect(get(selectedSongId)).toBe('s9');
	});

	it('finds a later song page and restores its canonical address', async () => {
		fetchSongs
			.mockResolvedValueOnce({
				items: [
					song({
						title: 'Tide',
						album_title: 'Nachtstrom',
						generation_count: 0,
						id: 's-other',
						slug: 'other',
						album_id: 'a9'
					})
				],
				total: 2,
				offset: 0,
				limit: 200,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [
					song({
						title: 'Tide',
						generation_count: 0,
						id: 's9',
						slug: 'tide',
						album_id: 'a9',
						album_title: 'Remote'
					})
				],
				total: 2,
				offset: 200,
				limit: 200,
				has_more: false
			});
		mountAddressRoute('/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(window.location.pathname).toBe('/album/a9/tide');
		expect(get(selectedSongId)).toBe('s9');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a9' });
	});

	it('reports an unknown song slug within a known album, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		mountAddressRoute('/album/a9/ghost-song');

		await expect(openSongAddress('a9', 'ghost-song')).resolves.toBe('unknown-song');

		expect(get(selectedSongId)).toBeNull();
		expect(historyEntry()).toBeNull();
	});

	it('reports an unknown album even when the song lookup also comes back empty', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		mountAddressRoute('/album/ghost/tide');

		await expect(openSongAddress('ghost', 'tide')).resolves.toBe('unknown-album');

		expect(get(selectedSongId)).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed song', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a9' },
			songId: 's9',
			scrollAnchor: 320
		};
		mountAddressRoute('/album/a9/tide', restored);

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(historyEntry().scrollAnchor).toBe(320);
	});

	it('opens a song address on the tab last shown for that song', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		showSongTab('s9', 'takes');
		detailTab.set('edit');
		mountAddressRoute('/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(historyEntry().detailTab).toBe('takes');
		expect(get(detailTab)).toBe('takes');
	});

	it.each([
		['takes', 'takes'],
		['cowriter', 'cowriter'],
		['generations', 'takes'],
		['write', 'edit']
	] as const)(
		'reopens a reloaded song on the tab its %s history entry was left on (%s)',
		async (leftOn, restored) => {
			fetchSongs.mockResolvedValueOnce({
				...emptyPage([
					song({
						title: 'Tide',
						generation_count: 0,
						id: 's9',
						slug: 'tide',
						album_id: 'a9',
						album_title: 'Remote'
					})
				]),
				limit: 200
			});
			mountAddressRoute('/album/a9/tide', {
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'a9' },
				songId: 's9',
				detailTab: leftOn as never
			});
			await reloadLibraryPage();

			await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

			expect(get(detailTab)).toBe(restored);
			expect(rememberedSongTab('s8')).toBe('edit');
		}
	);

	it('seeds the take named by the take query and opens Takes', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		mountAddressRoute('/album/a9/tide?gen=g1');

		await expect(openSongAddress('a9', 'tide', 'g1')).resolves.toBe('found');

		expect(get(selectedGenerationId)).toBe('g1');
		expect(get(detailTab)).toBe('takes');
	});
});

// The album a song belongs to is the queue its takes play in (#997): a song
// reached by its address must stand in its album exactly as one opened from
// the album's track list does.
describe('a song opened from its address sets its album', () => {
	it.each([
		{
			way: 'a deep link',
			open: async () => {
				fetchSongs.mockResolvedValueOnce({
					...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', generation_count: 0 })]),
					limit: 200
				});
				mountAddressRoute('/album/a9/tide');
				await openSongAddress('a9', 'tide');
			}
		},
		{
			way: 'a reload',
			open: async () => {
				replaceHistoryEntry('/album/a9/s9', {
					...libraryRootState(),
					surface: 'detail',
					collection: { kind: 'album', id: 'a9' },
					songId: 's9'
				});
				await hydrateLibraryFromHistory();
			}
		}
	])('through $way', async ({ open }) => {
		await open();

		expect(get(selectedSongId)).toBe('s9');
		expect(get(selectedAlbumId)).toBe('a9');
	});

	it('leaves the album of a song tapped while that restore still waited', async () => {
		let resolveAlbum: ((value: AlbumItem) => void) | undefined;
		fetchAlbum.mockImplementationOnce(
			() =>
				new Promise<AlbumItem>((resolve) => {
					resolveAlbum = resolve;
				})
		);
		const tide = song({ id: 's9', album_id: 'a9', generation_count: 0 });
		fetchSongs.mockImplementation(async (albumId: string | null) => ({
			...emptyPage(albumId === 'a2' ? [] : [tide]),
			limit: 200
		}));
		songList.set([tide]);
		const restore = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'album', id: 'a9' },
			songId: 's9'
		});
		await vi.waitFor(() => expect(resolveAlbum).toBeTypeOf('function'));

		await selectSong('s2', song({ id: 's2', album_id: 'a2', generation_count: 0 }));
		resolveAlbum?.(album({ id: 'a9' }));
		await restore;

		expect(get(selectedSongId)).toBe('s2');
		expect(get(selectedAlbumId)).toBe('a2');
	});
});

describe('openTakeAddress', () => {
	it.each([
		{ typed: '/album/a9/tide/take/3', form: 'its own form' },
		{ typed: '/album/a9/tide/take/03', form: 'another form of the same number' }
	])(
		'makes the library restore the addressed take on a tab that knows nothing else, typed in $form',
		async ({ typed }) => {
			fetchSongs.mockResolvedValueOnce({
				...emptyPage([
					song({
						title: 'Tide',
						id: 's9',
						slug: 'tide',
						album_id: 'a9',
						album_title: 'Remote',
						generation_count: 1,
						generations: [
							generation({
								song_id: 's9',
								mp3_path: '/audio/g1.mp3',
								seed: 1,
								generation_number: 3
							})
						]
					})
				]),
				limit: 200
			});
			mountAddressRoute(typed);

			await expect(openTakeAddress('a9', 'tide', 3)).resolves.toBe('found');

			expect(location.pathname).toBe('/album/a9/tide/take/3');
			expect(historyEntry().songId).toBe('s9');
			expect(historyEntry().generationId).toBe('g1');
			expect(historyEntry().collection).toEqual({ kind: 'album', id: 'a9' });
			expect(get(selectedSongId)).toBe('s9');
			expect(get(selectedGenerationId)).toBe('g1');
			expect(get(detailTab)).toBe('takes');
		}
	);

	it('loads the rest of the song generations to find a take the listing did not carry yet', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					album_title: 'Nachtstrom',
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					generation_count: 2,
					generations: [generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 })]
				})
			]),
			limit: 200
		});
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 2,
				generations: [
					generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 }),
					generation({
						song_id: 's9',
						mp3_path: '/audio/g1.mp3',
						seed: 1,
						id: 'g2',
						generation_number: 2
					})
				]
			})
		);
		mountAddressRoute('/album/a9/tide/take/2');

		await expect(openTakeAddress('a9', 'tide', 2)).resolves.toBe('found');

		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(get(selectedGenerationId)).toBe('g2');
	});

	it('reports an unknown take number within a known song, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					album_title: 'Nachtstrom',
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					generation_count: 1,
					generations: [generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 })]
				})
			]),
			limit: 200
		});
		mountAddressRoute('/album/a9/tide/take/9');

		await expect(openTakeAddress('a9', 'tide', 9)).resolves.toBe('unknown-take');

		expect(get(selectedSongId)).toBeNull();
		expect(historyEntry()).toBeNull();
	});

	it('reports an unknown song slug within a known album, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					title: 'Tide',
					generation_count: 0,
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote'
				})
			]),
			limit: 200
		});
		mountAddressRoute('/album/a9/ghost-song/take/1');

		await expect(openTakeAddress('a9', 'ghost-song', 1)).resolves.toBe('unknown-song');

		expect(get(selectedSongId)).toBeNull();
	});

	it('reports an unknown album even when the song lookup also comes back empty', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		mountAddressRoute('/album/ghost/tide/take/1');

		await expect(openTakeAddress('ghost', 'tide', 1)).resolves.toBe('unknown-album');

		expect(get(selectedSongId)).toBeNull();
	});
});

describe('resolveLegacySongQueryAddress', () => {
	it('resolves a bare legacy song id onto the song address', async () => {
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				id: 's9',
				slug: 'tide',
				album_id: 'a9'
			})
		);

		await expect(resolveLegacySongQueryAddress('s9', null)).resolves.toEqual({
			kind: 'found',
			path: '/album/a9/tide',
			droppedUnknownTake: false
		});
	});

	it('resolves a legacy song+gen id pair onto the take address by number', async () => {
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 1,
				generations: [
					generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1, generation_number: 3 })
				]
			})
		);

		await expect(resolveLegacySongQueryAddress('s9', 'g1')).resolves.toEqual({
			kind: 'found',
			path: '/album/a9/tide/take/3',
			droppedUnknownTake: false
		});
	});

	it('drops an unknown generation id, lands on the song address, and flags the drop -- the song still exists', async () => {
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 1,
				generations: [generation({ song_id: 's9', mp3_path: '/audio/g1.mp3', seed: 1 })]
			})
		);

		await expect(resolveLegacySongQueryAddress('s9', 'ghost-gen')).resolves.toEqual({
			kind: 'found',
			path: '/album/a9/tide',
			droppedUnknownTake: true
		});
	});

	it('upserts the resolved song into songList so the redirect target finds it without fetching again', async () => {
		fetchSong.mockResolvedValueOnce(
			song({
				title: 'Tide',
				album_title: 'Nachtstrom',
				generation_count: 0,
				id: 's9',
				slug: 'tide',
				album_id: 'a9'
			})
		);

		await resolveLegacySongQueryAddress('s9', null);

		expect(get(songList).some((item) => item.id === 's9' && item.slug === 'tide')).toBe(true);
	});

	it('reports an unknown song id as the same honest 404 an unknown slug gets', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchSong.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/songs/dead'));

		await expect(resolveLegacySongQueryAddress('dead', null)).resolves.toEqual({
			kind: 'unknown-song'
		});
	});

	it('propagates a failure that is not a missing song instead of calling it unknown', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchSong.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/songs/s9'));

		await expect(resolveLegacySongQueryAddress('s9', null)).rejects.toThrow('boom');
	});
});

describe('openAlbumAddress', () => {
	it('makes the library restore the addressed album on a tab that knows nothing else', async () => {
		mountAddressRoute('/album/a9');

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(historyEntry().collection).toEqual({ kind: 'album', id: 'a9' });
		expect(historyEntry().surface).toBe('detail');
	});

	it('reports an unknown slug without opening anything', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		mountAddressRoute('/album/ghost');

		await expect(openAlbumAddress('ghost')).resolves.toBe('unknown');

		expect(get(openCollection)).toBeNull();
		expect(historyEntry()).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed album', async () => {
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a9' },
			scrollAnchor: 320
		};
		mountAddressRoute('/album/a9', restored);

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(historyEntry().scrollAnchor).toBe(320);
	});

	it('lets the address overrule a restore state that opens a different album', async () => {
		mountAddressRoute('/album/a9', {
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'album', id: 'other' }
		});

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(historyEntry().collection).toEqual({ kind: 'album', id: 'a9' });
	});

	// History moved on while the route resolved its params (issue #1006, H3).
	it('mounts the route of the address history stands on when the params name another', async () => {
		const left = { ...libraryRootState(), surface: 'detail' as const, scrollAnchor: 640 };
		mountAddressRoute('/album/a9');
		replaceEntry('/album/a2', { library: { ...left, collection: { kind: 'album', id: 'a2' } } });

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(fakePage.url.pathname).toBe('/album/a2');
		expect(get(openCollection)).not.toEqual({ kind: 'album', id: 'a9' });
		expect(historyEntry()).toEqual({ ...left, collection: { kind: 'album', id: 'a2' } });
	});

	it('propagates a failure that is not a missing album instead of calling it unknown', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchAlbum.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/albums/a9'));
		mountAddressRoute('/album/a9');

		await expect(openAlbumAddress('a9')).rejects.toThrow('boom');
	});
});

describe('openPlaylistAddress', () => {
	it('makes the library restore the addressed playlist on a tab that knows nothing else', async () => {
		fetchPlaylists.mockResolvedValueOnce([
			playlistItem({ title: 'P', share_slug: null, id: 'p9', slug: 'friday-night' })
		]);
		fetchPlaylist.mockResolvedValueOnce(
			playlistDetail({
				slug: 'p',
				entry_count: 0,
				share_slug: null,
				id: 'p9',
				title: 'Friday Night'
			})
		);
		mountAddressRoute('/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(historyEntry().collection).toEqual({ kind: 'playlist', id: 'p9' });
		expect(historyEntry().surface).toBe('detail');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p9' });
	});

	it('reports an unknown slug without opening anything', async () => {
		fetchPlaylists.mockResolvedValueOnce([]);
		mountAddressRoute('/playlist/ghost');

		await expect(openPlaylistAddress('ghost')).resolves.toBe('unknown');

		expect(get(openCollection)).toBeNull();
		expect(historyEntry()).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed playlist', async () => {
		fetchPlaylists.mockResolvedValueOnce([
			playlistItem({ title: 'P', share_slug: null, id: 'p9', slug: 'friday-night' })
		]);
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'playlist' as const, id: 'p9' },
			scrollAnchor: 320
		};
		mountAddressRoute('/playlist/friday-night', restored);

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(historyEntry().scrollAnchor).toBe(320);
	});

	it('lets the address overrule a restore state that opens a different playlist', async () => {
		fetchPlaylists.mockResolvedValueOnce([
			playlistItem({ title: 'P', share_slug: null, id: 'p9', slug: 'friday-night' })
		]);
		mountAddressRoute('/playlist/friday-night', {
			...libraryRootState(),
			surface: 'detail',
			collection: { kind: 'playlist', id: 'other' }
		});

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(historyEntry().collection).toEqual({ kind: 'playlist', id: 'p9' });
	});

	it('propagates a failure that is not a missing playlist instead of calling it unknown', async () => {
		const { ApiError } = await import('#lib/api/fetch.ts');
		fetchPlaylists.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/playlists'));
		mountAddressRoute('/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).rejects.toThrow('boom');
	});

	it('reuses an already-loaded playlistList instead of fetching again', async () => {
		playlistList.set([
			playlistItem({ title: 'P', share_slug: null, id: 'p9', slug: 'friday-night' })
		]);
		fetchPlaylist.mockResolvedValueOnce(
			playlistDetail({
				slug: 'p',
				entry_count: 0,
				share_slug: null,
				id: 'p9',
				title: 'Friday Night'
			})
		);
		mountAddressRoute('/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(fetchPlaylists).not.toHaveBeenCalled();
	});
});

const SURFACE_ADDRESSES = [
	{
		name: 'openLibraryAddress',
		open: openLibraryAddress,
		path: LIBRARY_ROUTE_PATH,
		surface: 'browse'
	},
	{ name: 'openHomeAddress', open: openHomeAddress, path: HOME_ROUTE_PATH, surface: 'home' }
] as const;

// Resolves the address and the live stream's hydration of the same entry,
// the hydration held on its album read: the address finishes first while it
// is in flight, or after it has finished.
async function finishAddressAndHydration(
	open: () => Promise<unknown>,
	first: 'address' | 'hydration'
): Promise<void> {
	albumList.set([album({ id: 'a9' })]);
	let releaseHydration!: () => void;
	fetchAlbums.mockImplementation(
		() =>
			new Promise((resolve) => {
				releaseHydration = () => resolve(emptyPage([album({ id: 'a9' })]));
			})
	);
	const hydration = hydrateLibraryFromHistory();
	await vi.waitFor(() => expect(fetchAlbums).toHaveBeenCalledTimes(1));
	if (first === 'address') await open();
	releaseHydration();
	await hydration;
	if (first === 'hydration') await open();
}

describe.each(SURFACE_ADDRESSES)('$name (1354_rule_31)', ({ open, path, surface: own }) => {
	const root: LibraryHistoryState = { ...libraryRootState(), surface: own };

	it.each([own, 'playlists'] as const)(
		'resolves a cold address when %s is shown without adding an entry',
		async (shown) => {
			mountAddressRoute(path);
			librarySurface.set(shown);
			const length = historyLength();

			await expect(open()).resolves.toBe('found');

			expect(historyEntry()).toEqual(root);
			expect(get(librarySurface)).toBe(own);
			expect(get(selectedSongId)).toBeNull();
			expect(historyLength()).toBe(length);
		}
	);

	it.each([
		{ ...libraryRootState(), surface: 'playlists' as const },
		{ ...libraryRootState(), surface: own, songId: 's9' },
		{ foreign: true }
	])('replaces a foreign entry in place: %j', async (entry) => {
		mountAddressRoute(path, entry);
		librarySurface.set('playlists');
		const length = historyLength();

		await open();

		expect(historyEntry()).toEqual(root);
		expect(historyLength()).toBe(length);
		expect(location.pathname).toBe(path);
		expect(get(librarySurface)).toBe(own);
	});

	it.each(['address', 'hydration'] as const)(
		'defect:#1506 loads the listing once on a cold tab when the %s finishes first',
		async (first) => {
			mountAddressRoute(path);

			await finishAddressAndHydration(open, first);

			expect(fetchAlbums).toHaveBeenCalledTimes(1);
			expect(fetchSongs).toHaveBeenCalledTimes(1);
			expect(get(librarySurface)).toBe(own);
		}
	);

	it.each([own, 'playlists'] as const)(
		'keeps a matching rich entry when %s was shown',
		async (shown) => {
			const left = { ...root, query: 'Tide', sort: 'title' as const, scrollAnchor: 320 };
			mountAddressRoute(path, left);
			await applyLibraryHistory(left);
			librarySurface.set(shown);

			await open();

			expect(historyEntry()).toEqual(left);
			expect(get(searchQuery)).toBe(left.query);
			expect(get(librarySort)).toBe(left.sort);
			expect(get(libraryScrollAnchor)).toBe(left.scrollAnchor);
		}
	);

	it.each(
		[false, true].flatMap((withCollection) =>
			(['address', 'hydration'] as const).map((first) => ({ withCollection, first }))
		)
	)(
		'keeps rich state with collection=$withCollection when $first finishes first',
		async ({ withCollection, first }) => {
			const left: LibraryHistoryState = {
				...root,
				query: 'Tide',
				sort: 'title',
				scrollAnchor: 320,
				albumOffset: 1,
				collection: withCollection ? { kind: 'album', id: 'a9' } : null
			};
			mountAddressRoute(path, left);
			librarySurface.set('playlists');

			await finishAddressAndHydration(open, first);

			expect(historyEntry()).toEqual(left);
			expect(location.pathname).toBe(path);
			expect(get(librarySurface)).toBe(own);
			expect(get(openCollection)).toEqual(left.collection);
			expect(get(searchQuery)).toBe(left.query);
			expect(get(librarySort)).toBe(left.sort);
			expect(get(libraryScrollAnchor)).toBe(left.scrollAnchor);
		}
	);
});

// R1' (#1354 rule 31, #1506): `/` was the Library wall until Home took it, so
// a history from before the switch holds `{browse}` entries at `/`. The
// address decides: they read as Home, in whichever order the route and the
// stream's hydration finish, and nothing carries the tab to `/library`.
describe('1354_R1prime: an entry from before Home had its own address', () => {
	const staleEntry = (collection: LibraryHistoryState['collection']): LibraryHistoryState => ({
		...libraryRootState(),
		query: 'Tide',
		sort: 'title',
		albumOffset: 1,
		scrollAnchor: 320,
		collection
	});

	it.each([
		{ name: 'an empty one', stale: staleEntry(null) },
		{ name: 'one that keeps an album as the rail context', stale: staleEntry(albumSnapshot('a9')) },
		{ name: 'a song-bearing one', stale: { ...staleEntry(null), songId: 's9' } },
		{ name: 'a take-bearing one', stale: { ...staleEntry(null), songId: 's9', generationId: 'g9' } }
	])('reads $name at Home as the Home entry, keeping all but the wall scroll', ({ stale }) => {
		mountAddressRoute(HOME_ROUTE_PATH, stale);

		expect(historyEntry()).toEqual({ ...stale, surface: 'home', scrollAnchor: 0 });
	});

	it.each([
		{ surface: 'detail' as const, collection: albumSnapshot('a9'), pathname: '/album/a9' },
		{ surface: 'playlists' as const, collection: null, pathname: '/playlists' },
		{ surface: 'home' as const, collection: null, pathname: HOME_ROUTE_PATH },
		{ surface: 'browse' as const, collection: null, pathname: LIBRARY_ROUTE_PATH }
	])('leaves a $surface entry at $pathname as it was written', ({ pathname, ...written }) => {
		const entry = { ...staleEntry(null), ...written };
		mountAddressRoute(pathname, entry);

		expect(historyEntry()).toEqual(entry);
	});

	it('leaves an entry the library did not write alone', () => {
		mountAddressRoute(HOME_ROUTE_PATH, { foreign: true });

		expect(libraryHistoryEntry()).toEqual({ foreign: true });
	});

	it('reads a write held behind a step back as written, while the address still reads Home', async () => {
		mountAddressRoute(HOME_ROUTE_PATH, { ...libraryRootState(), surface: 'home' });
		const leaveMenu = holdLayer('menu', () => undefined);
		leaveMenu();

		void writeLibraryHistory(libraryRootState(), LIBRARY_ROUTE_PATH, 'push');

		expect(currentLibraryHistoryState()).toEqual(libraryRootState());
	});

	it.each(
		[null, albumSnapshot('a9')].flatMap((collection) =>
			(['address', 'hydration'] as const).map((first) => ({ collection, first }))
		)
	)(
		'stays at Home with collection=$collection when $first finishes first',
		async ({ collection, first }) => {
			const stale = staleEntry(collection);
			mountAddressRoute(HOME_ROUTE_PATH, stale);
			const length = historyLength();

			await finishAddressAndHydration(openHomeAddress, first);

			expect(location.pathname).toBe(HOME_ROUTE_PATH);
			expect(historyEntry()).toEqual({ ...stale, surface: 'home', scrollAnchor: 0 });
			expect(get(librarySurface)).toBe('home');
			expect(get(openCollection)).toEqual(collection);
			expect(get(libraryScrollAnchor)).toBe(0);
			expect(historyLength()).toBe(length);
		}
	);
});

describe('openPlaylistsAddress', () => {
	const playlistsPage: LibraryHistoryState = { ...libraryRootState(), surface: 'playlists' };

	it('makes the library show the Playlists page on a tab that knows nothing else', async () => {
		mountAddressRoute('/playlists');

		await expect(openPlaylistsAddress()).resolves.toBe('found');

		expect(historyEntry()).toEqual(playlistsPage);
		expect(location.pathname).toBe('/playlists');
		expect(get(librarySurface)).toBe('playlists');
	});

	it('shows the Playlists page a reload comes back onto with what its entry carried', async () => {
		const left = { ...playlistsPage, sort: 'title' as const, scrollAnchor: 320 };
		mountAddressRoute('/playlists', left);
		await reloadLibraryPage();

		await expect(openPlaylistsAddress()).resolves.toBe('found');

		expect(historyEntry()).toEqual(left);
		expect(get(librarySurface)).toBe('playlists');
	});

	it('lets the address overrule a restore state that shows another page', async () => {
		mountAddressRoute('/playlists', { ...libraryRootState(), scrollAnchor: 320 });

		await expect(openPlaylistsAddress()).resolves.toBe('found');

		expect(historyEntry()).toEqual(playlistsPage);
		expect(get(librarySurface)).toBe('playlists');
	});
});

// Issue #1263, from H3's review: history may move on before an address route
// resolves its params, or while it does. The params then name an address
// history has left, and the route of the address it stands on is mounted
// instead -- never a verdict about the address left behind.
describe('an address route whose history moves on', () => {
	const albumLeftFor = {
		...libraryRootState(),
		surface: 'detail' as const,
		collection: { kind: 'album' as const, id: 'a2' }
	};

	async function moveHistoryOn(): Promise<void> {
		await landed(replaceEntry(albumRoutePath('a2'), { library: albumLeftFor }));
	}

	const notFound = new ApiError(404, 'not found', '/api/lookup');
	const resolvers = [
		{
			route: 'album',
			mountedAt: '/album/ghost',
			lookup: fetchAlbum,
			lookupFindsNothing: async () => Promise.reject(notFound),
			resolve: () => openAlbumAddress('ghost')
		},
		{
			route: 'song',
			mountedAt: '/album/a9/ghost',
			lookup: fetchSongs,
			lookupFindsNothing: async () => emptyPage(),
			resolve: () => openSongAddress('a9', 'ghost')
		},
		{
			route: 'take',
			mountedAt: '/album/a9/ghost/take/1',
			lookup: fetchSongs,
			lookupFindsNothing: async () => emptyPage(),
			resolve: () => openTakeAddress('a9', 'ghost', 1)
		},
		{
			route: 'playlist',
			mountedAt: '/playlist/ghost',
			lookup: fetchPlaylists,
			lookupFindsNothing: async () => [],
			resolve: () => openPlaylistAddress('ghost')
		}
	];

	it.each(resolvers)(
		'mounts the $route route over the address history moved on to before it resolved',
		async ({ mountedAt, lookup, resolve }) => {
			mountAddressRoute(mountedAt);
			await moveHistoryOn();

			await expect(resolve()).resolves.toBe('found');

			expect(lookup).not.toHaveBeenCalled();
			expect(fakePage.url.pathname).toBe(albumRoutePath('a2'));
			expect(historyEntry()).toEqual(albumLeftFor);
		}
	);

	it.each(resolvers)(
		'mounts the $route route over the address history moved on to while it resolved, instead of calling it unknown',
		async ({ mountedAt, lookup, lookupFindsNothing, resolve }) => {
			mountAddressRoute(mountedAt);
			lookup.mockImplementationOnce(async () => {
				await moveHistoryOn();
				return lookupFindsNothing();
			});

			await expect(resolve()).resolves.toBe('found');

			expect(fakePage.url.pathname).toBe(albumRoutePath('a2'));
			expect(historyEntry()).toEqual(albumLeftFor);
		}
	);

	it.each(resolvers)(
		'mounts the $route route over the address history moved on to while its lookup failed, instead of calling it unreachable',
		async ({ mountedAt, lookup, resolve }) => {
			mountAddressRoute(mountedAt);
			lookup.mockImplementationOnce(async () => {
				await moveHistoryOn();
				throw new ApiError(500, 'boom', '/api/lookup');
			});

			await expect(resolve()).resolves.toBe('found');

			expect(fakePage.url.pathname).toBe(albumRoutePath('a2'));
			expect(historyEntry()).toEqual(albumLeftFor);
		}
	);

	it('mounts the route of the address history moved on to before the Playlists page resolved', async () => {
		mountAddressRoute('/playlists');
		await moveHistoryOn();

		await expect(openPlaylistsAddress()).resolves.toBe('found');

		expect(fakePage.url.pathname).toBe(albumRoutePath('a2'));
		expect(get(librarySurface)).not.toBe('playlists');
		expect(historyEntry()).toEqual(albumLeftFor);
	});

	it.each(resolvers)(
		'resolves nothing for the $route route mounted over its address under the page the router kept',
		async ({ mountedAt, lookup, resolve }) => {
			mountAddressRoute(mountedAt);
			await landed(replaceEntry(mountedAt, { library: albumLeftFor }));
			await mountRouteUnderKeptPage();

			await expect(resolve()).resolves.toBe('found');

			expect(lookup).not.toHaveBeenCalled();
			expect(location.pathname).toBe(mountedAt);
			expect(historyEntry()).toEqual(albumLeftFor);
		}
	);
});

describe('the place the wall returns from', () => {
	type LibrarySurface = Parameters<typeof setLibrarySurface>[0];
	const album: OpenCollection = { kind: 'album', id: 'a2' };
	const playlist: OpenCollection = { kind: 'playlist', id: 'p1' };

	it.each<{
		change: string;
		from: LibrarySurface;
		open: OpenCollection | null;
		to: LibrarySurface;
		returnedFrom: OpenCollection | null;
	}>([
		{
			change: 'an album page to the Library wall',
			from: 'detail',
			open: album,
			to: 'browse',
			returnedFrom: album
		},
		{
			change: 'a playlist page to the Playlists page',
			from: 'detail',
			open: playlist,
			to: 'playlists',
			returnedFrom: playlist
		},
		{
			change: 'an album page to Home',
			from: 'detail',
			open: album,
			to: 'home',
			returnedFrom: null
		},
		{
			change: 'Home to the Library wall',
			from: 'home',
			open: album,
			to: 'browse',
			returnedFrom: null
		},
		{
			change: 'the wall to itself',
			from: 'browse',
			open: album,
			to: 'browse',
			returnedFrom: null
		},
		{
			change: 'a page without a collection to the wall',
			from: 'detail',
			open: null,
			to: 'browse',
			returnedFrom: null
		}
	])('1354_rule_12: $change names $returnedFrom', ({ from, open, to, returnedFrom }) => {
		librarySurface.set(from);
		setOpenCollection(open);

		setLibrarySurface(to);

		expect(takePlaceReturnedFrom()).toEqual(returnedFrom);
	});

	it('1354_rule_12: names the place to one wall only', () => {
		librarySurface.set('detail');
		setOpenCollection(album);
		setLibrarySurface('browse');

		expect(takePlaceReturnedFrom()).toEqual(album);
		expect(takePlaceReturnedFrom()).toBeNull();
	});

	it('1354_rule_12: forgets the place when the surface changes again before the wall takes it', () => {
		librarySurface.set('detail');
		setOpenCollection(album);
		setLibrarySurface('browse');
		setLibrarySurface('home');

		expect(takePlaceReturnedFrom()).toBeNull();
	});

	it('1354_rule_12: keeps the place when the same surface is applied twice', () => {
		librarySurface.set('detail');
		setOpenCollection(album);
		setLibrarySurface('browse');
		setLibrarySurface('browse');

		expect(takePlaceReturnedFrom()).toEqual(album);
	});

	it('1354_rule_12: Back onto the wall names the album left although the wall entry holds none', async () => {
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			collection: albumSnapshot('a2')
		});

		await applyLibraryHistory(libraryRootState());

		expect(get(openCollection)).toBeNull();
		expect(takePlaceReturnedFrom()).toEqual(album);
	});
});
