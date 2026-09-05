import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type {
	AlbumItem,
	GenerationItem,
	PlaylistDetailItem,
	PlaylistItem,
	SongItem
} from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { LIBRARY_HISTORY_KIND } from '$lib/constants';
import { openCollection } from '$lib/stores/collection';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	loadLibraryBrowse,
	resetLibrarySearchForTests
} from '$lib/stores/librarySearch';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import {
	playlistList,
	playlistLoad,
	resetPlaylists,
	selectedPlaylistDetail
} from '$lib/stores/playlists';
import { openSharesInventory, resetShares, sharesViewOpen } from '$lib/stores/shares';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const searchLibrary = vi.fn();
const fetchShares = vi.fn();

// Only the route-shape crossing suite below drives a write that actually
// crosses (every other test in this file sets window.location to the write's
// own target first, so its write is same-shape and never reaches this) --
// mocked the same way navigation.test.ts does, so a crossing write's `goto`
// call moves the URL like the real one does.
vi.mock('$app/navigation', () => ({
	goto: vi.fn((url: string, options?: { replaceState?: boolean }) => {
		if (options?.replaceState) history.replaceState(null, '', url);
		else history.pushState(null, '', url);
		return Promise.resolve();
	})
}));

vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args),
	fetchShares: (...args: unknown[]) => fetchShares(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));
// player.ts's ensureGenerationsLoaded, which openTakeAddress uses to resolve
// a take number against the song's full generations, fetches through this
// module's fetchSong rather than $lib/api/songs's -- both share the fetchSong
// spy below so a test only has to program one mocked response either way.
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn()
}));

import { goto } from '$app/navigation';
import { albumRoutePath, songRoutePath } from '$lib/routes/addresses';

import {
	albumIsExpanded,
	applyLibraryHistory,
	captureLibraryScroll,
	detailTab,
	hydrateLibraryFromHistory,
	isLibraryHistoryState,
	libraryHistoryUrl,
	librarySurface,
	openAlbumAddress,
	openPlaylistAddress,
	openSongAddress,
	openTakeAddress,
	resolveLegacySongQueryAddress,
	libraryRootState,
	libraryScrollAnchor,
	resetLibraryContextForTests,
	snapshotLibraryHistory,
	writeLibraryHistory
} from './libraryContext';

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: overrides.id ?? 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
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
		share_slug: null,
		...overrides
	};
}

function playlistDetail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'P',
		slug: 'p',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [],
		...overrides
	};
}

function playlistItem(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'P',
		slug: 'p',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's9',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: '/audio/g1.mp3',
		wav_path: null,
		seed: 1,
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
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function emptyPage<T>(items: T[] = []) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: false };
}

beforeEach(() => {
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchAlbum.mockReset();
	fetchAlbums.mockReset();
	fetchSong.mockReset();
	fetchSongs.mockReset();
	searchLibrary.mockReset();
	fetchShares.mockReset();
	fetchShares.mockResolvedValue(emptyPage());
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue(playlistDetail());
	fetchAlbums.mockResolvedValue(emptyPage());
	fetchSongs.mockResolvedValue({ ...emptyPage(), limit: 200 });
	searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchAlbum.mockResolvedValue(album({ id: 'a9', title: 'Remote' }));
	fetchSong.mockResolvedValue(song({ id: 's9', album_id: 'a9', album_title: 'Remote' }));
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetShares();
	resetPlaylists();
	searchQuery.set('');
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	playlistLoad.set({ status: 'idle', error: null });
	history.replaceState(null, '', '/');
	vi.mocked(goto).mockClear();
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetShares();
	resetPlaylists();
});

describe('albumIsExpanded', () => {
	it('expands search groups with song hits only', () => {
		expect(albumIsExpanded({ searching: false, songHits: 2 })).toBe(false);
		expect(albumIsExpanded({ searching: true, songHits: 1 })).toBe(true);
		expect(albumIsExpanded({ searching: true, songHits: 0 })).toBe(false);
	});
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
			detailTab: 'write'
		});
		expect(isLibraryHistoryState(snap)).toBe(true);
	});

	it('does not snapshot a previous search page count onto a new query', () => {
		searchQuery.set('new');
		librarySearch.set({
			q: 'old',
			status: 'ready',
			error: null,
			items: [
				{ type: 'album', album: album({ id: 'a1' }) },
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

	it('keeps the shares inventory outside the mixed library history', async () => {
		openSharesInventory();
		const state = { ...snapshotLibraryHistory(2), scrollAnchor: 240 };

		await applyLibraryHistory(state);

		expect(get(sharesViewOpen)).toBe(true);
		expect(get(libraryScrollAnchor)).toBe(240);
		expect(state).not.toHaveProperty('filter');
	});
});

describe('applyLibraryHistory', () => {
	it('hydrates an album collection that is not yet loaded', async () => {
		const state = { ...libraryRootState(), collection: { kind: 'album' as const, id: 'a9' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a9' });
		expect(get(albumList).some((a) => a.id === 'a9')).toBe(true);
	});

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
		fetchPlaylist.mockResolvedValueOnce(playlistDetail({ id: 'p1', title: 'Night Drive' }));
		const state = { ...libraryRootState(), collection: { kind: 'playlist' as const, id: 'p1' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistDetail)?.title).toBe('Night Drive');
	});

	it('clears a playlist collection that no longer exists', async () => {
		const { ApiError } = await import('$lib/api/fetch');
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
		fetchPlaylist.mockResolvedValueOnce(playlistDetail({ id: 'p2', title: 'Second' }));
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
		resolveFirst?.(playlistDetail({ id: 'p1', title: 'First' }));
		await first;
		expect(get(selectedPlaylistDetail)?.id).toBe('p2');
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
		resolveAlbum?.(album({ id: 'a1' }));
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
		fetchSong.mockResolvedValueOnce(song({ id: 's2', album_id: 'a9' }));

		const first = applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's1' });
		await vi.waitFor(() => expect(rejectSong).toBeTypeOf('function'));
		const second = applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's2' });
		await expect(second).resolves.toBe(true);
		rejectSong?.(new ApiError(404, 'gone', '/api/songs/s1'));
		await expect(first).resolves.toBe(false);

		expect(get(selectedSongId)).toBe('s2');
	});

	it('fetches the selected song when retained takes are fewer than generation_count', async () => {
		songList.set([
			song({
				id: 's9',
				album_id: 'a9',
				generation_count: 2,
				generations: [generation({ id: 'g1', song_id: 's9' })]
			})
		]);
		fetchSong.mockResolvedValueOnce(
			song({
				id: 's9',
				album_id: 'a9',
				generation_count: 2,
				generations: [
					generation({ id: 'g1', song_id: 's9' }),
					generation({ id: 'g2', song_id: 's9' })
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
		const { ApiError } = await import('$lib/api/fetch');
		fetchSong.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/songs/s9'));
		await applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's9' });
		expect(get(selectedSongId)).toBe('s9');

		fetchSong.mockRejectedValueOnce(new ApiError(404, 'gone', '/api/songs/s9'));
		await applyLibraryHistory({ ...libraryRootState(), surface: 'detail', songId: 's9' });
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
	});

	it('defaults a missing detailTab to the write tab without failing restore', async () => {
		const { detailTab: recordedTab, ...withoutDetailTab } = libraryRootState();
		expect(recordedTab).toBe('write');
		detailTab.set('takes');
		await applyLibraryHistory(withoutDetailTab);
		expect(get(detailTab)).toBe('write');
		expect(get(librarySurface)).toBe('browse');
	});

	it('maps a pre-#100 detailTab (generations/edit/chat) to the new write/takes tabs', async () => {
		detailTab.set('takes');
		await applyLibraryHistory({ ...libraryRootState(), detailTab: 'generations' as never });
		expect(get(detailTab)).toBe('takes');
		await applyLibraryHistory({ ...libraryRootState(), detailTab: 'edit' as never });
		expect(get(detailTab)).toBe('write');
		await applyLibraryHistory({ ...libraryRootState(), detailTab: 'chat' as never });
		expect(get(detailTab)).toBe('write');
	});
});

describe('hydrateLibraryFromHistory', () => {
	it('replaces history after hydrate so a deleted playlist is not replayed', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		history.replaceState(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'p-gone' }
			},
			'',
			'/'
		);
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/playlists/p-gone'));
		await hydrateLibraryFromHistory();
		expect(history.state.collection).toBeNull();
		expect(history.state.surface).toBe('browse');
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
		songList.set([song({ id: 's1', slug: 'tide', album_id: 'anfield' })]);

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
				id: 's1',
				slug: 'tide',
				album_id: 'anfield',
				generations: [generation({ id: 'g1', song_id: 's1', generation_number: 3 })]
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
		songList.set([song({ id: 's1', slug: 'tide', album_id: 'anfield' })]);

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

	it('addresses the library itself while an album is only the rail context', () => {
		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'browse',
				collection: { kind: 'album', id: 'anfield' }
			})
		).toBe('/');
	});

	it('addresses an open playlist by its slug, not its id', () => {
		playlistList.set([playlistItem({ id: 'p1', slug: 'friday-night' })]);

		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'p1' }
			})
		).toBe('/playlist/friday-night');
	});

	it('falls back to the library while the open playlist is not yet in playlistList', () => {
		expect(
			libraryHistoryUrl({
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'p1' }
			})
		).toBe('/');
	});
});

// libraryRouteShape itself is not exported -- writeLibraryHistory's own
// crossing decision (goto vs. a raw synchronous write) is the observable
// behaviour, so that is what these pin. Central to issue #265's S7: since
// ensureLibraryWorkspaceRoute (#264) was removed, writeLibraryHistory is the
// only thing left that can catch a write landing on a library address from a
// non-library route (Settings, login, a share page) -- and it can only catch
// it if leaving such a route always counts as a crossing, every time,
// regardless of which of the five library shapes the write lands on.
describe('writeLibraryHistory route-shape crossing (issue #265 S7)', () => {
	it('crosses through goto for a write that changes which route file is mounted', async () => {
		history.replaceState(null, '', albumRoutePath('a1'));

		await writeLibraryHistory(libraryRootState(), songRoutePath('a1', 's1'), 'push');

		expect(goto).toHaveBeenCalledWith(songRoutePath('a1', 's1'), {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
	});

	// A song-to-song move across album boundaries stays the 'album' shape on
	// both sides -- only the route-file depth decides a crossing, never which
	// album or song the address names.
	it('stays a raw write for same-shape churn, never touching the router', async () => {
		history.replaceState(null, '', albumRoutePath('a1'));

		await writeLibraryHistory(libraryRootState(), albumRoutePath('a2'), 'replace');

		expect(goto).not.toHaveBeenCalled();
		expect(history.state).toEqual(libraryRootState());
	});

	// The one pairing that used to fail silently before 'external' became its
	// own shape: a write landing on '/' (openLibraryWall's target, or
	// openPlaylist's own '/' fallback before a playlist's slug is known) from
	// a non-library route both satisfied `!isAlbumRoutePath &&
	// !isPlaylistRoutePath`, so the two were indistinguishable and the write
	// took the cheap same-shape branch -- a raw `history.pushState` that
	// changes the address bar to '/' while the router stays mounted on
	// whichever route file it last saw. The next Back/Forward or real
	// navigation that disagrees with that stale belief tears the workspace
	// down mid-session. This is the pairing #265's S7 had to get right for
	// removing ensureLibraryWorkspaceRoute to be safe.
	it('crosses through goto when the target is "/" and the write starts from a non-library route', async () => {
		history.replaceState(null, '', '/settings/voices');

		await writeLibraryHistory(libraryRootState(), '/', 'push');

		expect(goto).toHaveBeenCalledWith('/', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
	});
});

describe('openSongAddress', () => {
	it('makes the library restore the addressed song on a tab that knows nothing else', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(history.state.songId).toBe('s9');
		expect(history.state.collection).toEqual({ kind: 'album', id: 'a9' });
		expect(get(selectedSongId)).toBe('s9');
	});

	it('finds a later song page and restores its canonical address', async () => {
		fetchSongs
			.mockResolvedValueOnce({
				items: [song({ id: 's-other', slug: 'other', album_id: 'a9' })],
				total: 2,
				offset: 0,
				limit: 200,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })],
				total: 2,
				offset: 200,
				limit: 200,
				has_more: false
			});
		history.replaceState(null, '', '/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(window.location.pathname).toBe('/album/a9/tide');
		expect(get(selectedSongId)).toBe('s9');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a9' });
	});

	it('reports an unknown song slug within a known album, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/ghost-song');

		await expect(openSongAddress('a9', 'ghost-song')).resolves.toBe('unknown-song');

		expect(get(selectedSongId)).toBeNull();
		expect(history.state).toBeNull();
	});

	it('reports an unknown album even when the song lookup also comes back empty', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		history.replaceState(null, '', '/album/ghost/tide');

		await expect(openSongAddress('ghost', 'tide')).resolves.toBe('unknown-album');

		expect(get(selectedSongId)).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed song', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })]),
			limit: 200
		});
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a9' },
			songId: 's9',
			scrollAnchor: 320
		};
		history.replaceState(restored, '', '/album/a9/tide');

		await expect(openSongAddress('a9', 'tide')).resolves.toBe('found');

		expect(history.state.scrollAnchor).toBe(320);
	});

	it('seeds the take named by the take query and opens Takes', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/tide?gen=g1');

		await expect(openSongAddress('a9', 'tide', 'g1')).resolves.toBe('found');

		expect(get(selectedGenerationId)).toBe('g1');
		expect(get(detailTab)).toBe('takes');
	});
});

describe('openTakeAddress', () => {
	it('makes the library restore the addressed take on a tab that knows nothing else', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					album_title: 'Remote',
					generation_count: 1,
					generations: [generation({ id: 'g1', song_id: 's9', generation_number: 3 })]
				})
			]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/tide/take/3');

		await expect(openTakeAddress('a9', 'tide', 3)).resolves.toBe('found');

		expect(history.state.songId).toBe('s9');
		expect(history.state.generationId).toBe('g1');
		expect(history.state.collection).toEqual({ kind: 'album', id: 'a9' });
		expect(get(selectedSongId)).toBe('s9');
		expect(get(selectedGenerationId)).toBe('g1');
		expect(get(detailTab)).toBe('takes');
	});

	it('loads the rest of the song generations to find a take the listing did not carry yet', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					generation_count: 2,
					generations: [generation({ id: 'g1', song_id: 's9', generation_number: 1 })]
				})
			]),
			limit: 200
		});
		fetchSong.mockResolvedValueOnce(
			song({
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 2,
				generations: [
					generation({ id: 'g1', song_id: 's9', generation_number: 1 }),
					generation({ id: 'g2', song_id: 's9', generation_number: 2 })
				]
			})
		);
		history.replaceState(null, '', '/album/a9/tide/take/2');

		await expect(openTakeAddress('a9', 'tide', 2)).resolves.toBe('found');

		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(get(selectedGenerationId)).toBe('g2');
	});

	it('reports an unknown take number within a known song, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([
				song({
					id: 's9',
					slug: 'tide',
					album_id: 'a9',
					generation_count: 1,
					generations: [generation({ id: 'g1', song_id: 's9', generation_number: 1 })]
				})
			]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/tide/take/9');

		await expect(openTakeAddress('a9', 'tide', 9)).resolves.toBe('unknown-take');

		expect(get(selectedSongId)).toBeNull();
		expect(history.state).toBeNull();
	});

	it('reports an unknown song slug within a known album, without opening anything', async () => {
		fetchSongs.mockResolvedValueOnce({
			...emptyPage([song({ id: 's9', slug: 'tide', album_id: 'a9', album_title: 'Remote' })]),
			limit: 200
		});
		history.replaceState(null, '', '/album/a9/ghost-song/take/1');

		await expect(openTakeAddress('a9', 'ghost-song', 1)).resolves.toBe('unknown-song');

		expect(get(selectedSongId)).toBeNull();
	});

	it('reports an unknown album even when the song lookup also comes back empty', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		history.replaceState(null, '', '/album/ghost/tide/take/1');

		await expect(openTakeAddress('ghost', 'tide', 1)).resolves.toBe('unknown-album');

		expect(get(selectedSongId)).toBeNull();
	});
});

describe('resolveLegacySongQueryAddress', () => {
	it('resolves a bare legacy song id onto the song address', async () => {
		fetchSong.mockResolvedValueOnce(song({ id: 's9', slug: 'tide', album_id: 'a9' }));

		await expect(resolveLegacySongQueryAddress('s9', null)).resolves.toEqual({
			kind: 'found',
			path: '/album/a9/tide',
			droppedUnknownTake: false
		});
	});

	it('resolves a legacy song+gen id pair onto the take address by number', async () => {
		fetchSong.mockResolvedValueOnce(
			song({
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 1,
				generations: [generation({ id: 'g1', song_id: 's9', generation_number: 3 })]
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
				id: 's9',
				slug: 'tide',
				album_id: 'a9',
				generation_count: 1,
				generations: [generation({ id: 'g1', song_id: 's9', generation_number: 1 })]
			})
		);

		await expect(resolveLegacySongQueryAddress('s9', 'ghost-gen')).resolves.toEqual({
			kind: 'found',
			path: '/album/a9/tide',
			droppedUnknownTake: true
		});
	});

	it('upserts the resolved song into songList so the redirect target finds it without fetching again', async () => {
		fetchSong.mockResolvedValueOnce(song({ id: 's9', slug: 'tide', album_id: 'a9' }));

		await resolveLegacySongQueryAddress('s9', null);

		expect(get(songList).some((item) => item.id === 's9' && item.slug === 'tide')).toBe(true);
	});

	it('reports an unknown song id as the same honest 404 an unknown slug gets', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchSong.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/songs/dead'));

		await expect(resolveLegacySongQueryAddress('dead', null)).resolves.toEqual({
			kind: 'unknown-song'
		});
	});

	it('propagates a failure that is not a missing song instead of calling it unknown', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchSong.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/songs/s9'));

		await expect(resolveLegacySongQueryAddress('s9', null)).rejects.toThrow('boom');
	});
});

describe('openAlbumAddress', () => {
	it('makes the library restore the addressed album on a tab that knows nothing else', async () => {
		history.replaceState(null, '', '/album/a9');

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(history.state.collection).toEqual({ kind: 'album', id: 'a9' });
		expect(history.state.surface).toBe('detail');
	});

	it('reports an unknown slug without opening anything', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/albums/ghost'));
		history.replaceState(null, '', '/album/ghost');

		await expect(openAlbumAddress('ghost')).resolves.toBe('unknown');

		expect(get(openCollection)).toBeNull();
		expect(history.state).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed album', async () => {
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a9' },
			scrollAnchor: 320
		};
		history.replaceState(restored, '', '/album/a9');

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(history.state.scrollAnchor).toBe(320);
	});

	it('lets the address overrule a restore state that opens a different album', async () => {
		history.replaceState(
			{ ...libraryRootState(), surface: 'detail', collection: { kind: 'album', id: 'other' } },
			'',
			'/album/a9'
		);

		await expect(openAlbumAddress('a9')).resolves.toBe('found');

		expect(history.state.collection).toEqual({ kind: 'album', id: 'a9' });
	});

	it('propagates a failure that is not a missing album instead of calling it unknown', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchAlbum.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/albums/a9'));

		await expect(openAlbumAddress('a9')).rejects.toThrow('boom');
	});
});

describe('openPlaylistAddress', () => {
	it('makes the library restore the addressed playlist on a tab that knows nothing else', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ id: 'p9', slug: 'friday-night' })]);
		fetchPlaylist.mockResolvedValueOnce(playlistDetail({ id: 'p9', title: 'Friday Night' }));
		history.replaceState(null, '', '/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(history.state.collection).toEqual({ kind: 'playlist', id: 'p9' });
		expect(history.state.surface).toBe('detail');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p9' });
	});

	it('reports an unknown slug without opening anything', async () => {
		fetchPlaylists.mockResolvedValueOnce([]);
		history.replaceState(null, '', '/playlist/ghost');

		await expect(openPlaylistAddress('ghost')).resolves.toBe('unknown');

		expect(get(openCollection)).toBeNull();
		expect(history.state).toBeNull();
	});

	it('keeps a richer restore state that already opens the addressed playlist', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ id: 'p9', slug: 'friday-night' })]);
		const restored = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'playlist' as const, id: 'p9' },
			scrollAnchor: 320
		};
		history.replaceState(restored, '', '/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(history.state.scrollAnchor).toBe(320);
	});

	it('lets the address overrule a restore state that opens a different playlist', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ id: 'p9', slug: 'friday-night' })]);
		history.replaceState(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'playlist', id: 'other' }
			},
			'',
			'/playlist/friday-night'
		);

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(history.state.collection).toEqual({ kind: 'playlist', id: 'p9' });
	});

	it('propagates a failure that is not a missing playlist instead of calling it unknown', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchPlaylists.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/playlists'));

		await expect(openPlaylistAddress('friday-night')).rejects.toThrow('boom');
	});

	it('reuses an already-loaded playlistList instead of fetching again', async () => {
		playlistList.set([playlistItem({ id: 'p9', slug: 'friday-night' })]);
		fetchPlaylist.mockResolvedValueOnce(playlistDetail({ id: 'p9', title: 'Friday Night' }));
		history.replaceState(null, '', '/playlist/friday-night');

		await expect(openPlaylistAddress('friday-night')).resolves.toBe('found');

		expect(fetchPlaylists).not.toHaveBeenCalled();
	});
});
