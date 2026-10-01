import {
	historyEntry,
	historyLength,
	pressBack,
	pressForward,
	reloadLibraryPage,
	replaceHistoryEntry,
	watchBack
} from '$lib/test-utils/library-history';
import {
	makeAlbum as album,
	makeGeneration as generation,
	makePlaylist as playlistItem,
	makeSong as song
} from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, type Writable } from 'svelte/store';
import { mount, tick, unmount } from 'svelte';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { fakePage, reportedNavigations, startFakeRouter } from '$lib/test-utils/app-navigation';
import SongDetailView from '$lib/components/SongDetailView.svelte';

import { resetLibrarySearchForTests, searchQuery } from '$lib/stores/librarySearch';
import {
	captureLibraryScroll,
	currentLibraryHistoryState,
	detailTab,
	isLibraryHistoryState,
	libraryHistoryStepsLanded,
	libraryScrollAnchor,
	librarySurface,
	openPlaylistAddress,
	openSongAddress,
	resetLibraryContextForTests
} from '$lib/stores/libraryContext';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList, updateSongInList } from '$lib/stores/libraryData';
import {
	closeNowPlaying,
	dockNowPlaying,
	expandNowPlaying,
	nowPlayingDockable,
	nowPlayingOpen,
	nowPlayingSurface,
	openNowPlaying,
	selectedGenerationId,
	selectedSongId
} from '$lib/stores/player';
import { resetPlaylists, selectedPlaylistId, updatePlaylistInList } from '$lib/stores/playlists';
import {
	activeJobs,
	generationFailures,
	removeJob,
	resetGenerationFailures
} from '$lib/stores/jobs';
import { closeSidebar, sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import { setDesktopNowPlayingSurface } from '$lib/stores/playbackSettings';
import { ApiError, NetworkError } from '$lib/api/fetch';
import {
	API_ERROR_GENERIC_MESSAGE,
	DIALOG_CANCEL_LABEL,
	EDITOR_SAVE_FAILED,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	EDITOR_UNSAVED_TITLE,
	SONG_LINK_NOT_FOUND_TOAST,
	LIBRARY_HISTORY_KIND,
	TAKES_ERROR,
	TAKES_RETRY_LABEL
} from '$lib/constants';
import type { SongItem } from '$lib/api/types';

const fetchSong = vi.fn();
const fetchAlbum = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLastFailedGeneration = vi.fn();
const fetchActiveGeneration = vi.fn();

// goto actually changes the URL (via the History API, like the real
// SvelteKit goto) so tests can assert the landed-on route, not just that
// goto was called with some argument (see issue #264's done-when).
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/loras', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/loras')>()),
	listLoras: vi.fn().mockResolvedValue([])
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => fetchLastFailedGeneration(...args),
	fetchActiveGeneration: (...args: unknown[]) => fetchActiveGeneration(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn(),
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn()
}));

import {
	albumTrackNeighbors,
	backToCollection,
	followAppPageLink,
	followShellLayers,
	goBack,
	initNavigation,
	isLibraryWorkspacePath,
	openAlbum,
	openCollectionEntry,
	openLibraryWall,
	openPlaylist,
	openRailSearchTarget,
	pendingDirtyNavigation,
	persistLibraryHistory,
	resetNavigationForTests,
	navigateToSongTab,
	openEditTab,
	revealPlayingSong,
	selectNeighborSong,
	selectSong
} from './navigation';
import { closeTopLayer, historyLayerState } from '$lib/stores/layers';
import {
	discardDraft,
	editLyrics,
	isDirty,
	loadSongData,
	setDraftLyrics
} from '$lib/stores/editor';
import { updateSong } from '$lib/api/client';
import { dialogHistoryLayer } from '$lib/utils/dialog-history-layer';
import { libraryRootState } from '$lib/stores/libraryContext';
import { toasts } from '$lib/stores/toast';

function navigableSongDefaults(): Partial<SongItem> {
	return { title: 'Tide', album_title: 'Nachtstrom', generations: [generation()] };
}

let stopFollowingShellLayers: () => void = () => undefined;

beforeEach(() => {
	fetchSong.mockReset();
	fetchAlbum.mockReset();
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchLastFailedGeneration.mockReset();
	fetchLastFailedGeneration.mockResolvedValue({ job: null });
	fetchActiveGeneration.mockReset().mockResolvedValue(null);
	resetGenerationFailures();
	vi.mocked(updateSong).mockReset();
	toasts.set([]);
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue({
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: []
	});
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	resetNavigationForTests();
	stopFollowingShellLayers = followShellLayers();
	searchQuery.set('');
	albumList.set([
		album({ share_slug: null }),
		album({ id: 'a2', title: 'Other', share_slug: null })
	]);
	songList.set([song({ ...navigableSongDefaults(), slug: 's1' })]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	// Must run after selectedSongId is cleared: the album/song-list reset
	// above briefly recomputes `selectedSong` against the previous test's
	// stale selectedSongId and re-derives openCollection through the
	// selectedSong subscription in navigation.ts before this line clears it.
	resetCollectionForTests();
	replaceHistoryEntry('/');
	startFakeRouter();
	vi.mocked(goto).mockClear();
});

afterEach(() => {
	stopFollowingShellLayers();
	for (const { job } of get(activeJobs)) removeJob(job.id);
	vi.unstubAllGlobals();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	resetCollectionForTests();
});

// The options a library write that crosses a route boundary navigates with:
// the library travels as the page state of the entry (issue #1165).
function crossingWrite(replaceState: boolean) {
	return {
		replaceState,
		noScroll: true,
		keepFocus: true,
		state: { library: expect.objectContaining({ kind: LIBRARY_HISTORY_KIND }) }
	};
}

describe('isLibraryWorkspacePath', () => {
	it('is the home path and every album, song, and playlist address', () => {
		expect(isLibraryWorkspacePath('/')).toBe(true);
		expect(isLibraryWorkspacePath('/album/anfield')).toBe(true);
		expect(isLibraryWorkspacePath('/album/anfield/stadion-lauf-a')).toBe(true);
		expect(isLibraryWorkspacePath('/playlist/friday-night')).toBe(true);
		expect(isLibraryWorkspacePath('/settings')).toBe(false);
	});

	// Issue #269 (and #275 one segment deeper): writeLibraryHistory's crossing
	// check must leave an album address alone rather than route every write
	// through '/', or opening a song from an album would take a detour
	// through the wall on the way there.
	it('goes straight from an album address to the song, without a detour', async () => {
		replaceHistoryEntry('/album/a1');
		await selectSong('s1');
		expect(vi.mocked(goto).mock.calls.map((call) => call[0])).toEqual(['/album/a1/s1']);
	});
});

// A history write that changes the route pattern (/ <-> /album/<slug>) must
// navigate, not just move the address bar: shallow routing leaves the router
// mounting the route it last saw, and the next Back/Forward or real
// navigation that disagrees tears the workspace down mid-session. The
// interaction with the router is the contract here, so it is asserted directly.
// A crossing pushed from a library page stands in history at once, and the
// router mounts its route by writing over that entry (issue #1165).
describe('history writes across the route boundary (issue #269)', () => {
	it('opens an album address through the router', async () => {
		replaceHistoryEntry('/', libraryRootState());
		await openAlbum('a1');
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1', crossingWrite(true));
		expect(window.location.pathname).toBe('/album/a1');
		expect(historyEntry().collection).toEqual({ kind: 'album', id: 'a1' });
	});

	it('leaves an album address through the router', async () => {
		await openAlbum('a1');
		vi.mocked(goto).mockClear();
		await openLibraryWall();
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/', crossingWrite(true));
		expect(window.location.pathname).toBe('/');
		expect(historyEntry().surface).toBe('browse');
	});

	it('writes the mixed library scroll position inside one route straight to history', async () => {
		await selectSong('s1');
		vi.mocked(goto).mockClear();

		captureLibraryScroll(240);
		persistLibraryHistory();

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(historyEntry().scrollAnchor).toBe(240);
		expect(historyEntry()).not.toHaveProperty('filter');
	});

	it('keeps a second write behind the crossing one it follows', async () => {
		replaceHistoryEntry('/album/a1');
		songList.set([song({ ...navigableSongDefaults(), slug: 's1', generations: [generation()] })]);

		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		selectedGenerationId.set('g1');
		persistLibraryHistory();

		// Pinning the take crosses a second time (issue #281: the take is its
		// own route file too), queued behind the song's own crossing write.
		await vi.waitFor(() => expect(historyEntry().generationId).toBe('g1'));
		expect(window.location.pathname + window.location.search).toBe('/album/a1/s1/take/1');
	});

	// Issue #275: an album address becomes a song address one segment deeper
	// (/album/x -> /album/x/y), which is a route-file boundary too -- the
	// naive isAlbumRoutePath boolean stays true on both sides of it, so the
	// crossing check must tell the two shapes apart, not just "under /album/".
	it('crosses through the router from an album address to a song inside it', async () => {
		await openAlbum('a1');
		vi.mocked(goto).mockClear();

		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));

		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1/s1', crossingWrite(true));
		expect(window.location.pathname).toBe('/album/a1/s1');
	});

	// Issue #1165: the song shows the moment it opens, a task before the router
	// has loaded its route, and a Back pressed then must step once.
	it('lands a Back pressed while the song route still loads on the album it was opened from', async () => {
		await openAlbum('a1');
		const album = historyEntry();
		vi.mocked(goto).mockImplementationOnce(() => new Promise<void>(() => undefined));

		void selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		await pressBack();

		expect(window.location.pathname).toBe('/album/a1');
		expect(historyEntry()).toEqual(album);
	});

	// An address its route stated as unknown or unreachable wrote no library
	// state, so Back onto it must load that route again to state it once more
	// instead of applying the wall under its address.
	it('crosses from an address without a library entry by one navigation Back loads again', async () => {
		replaceHistoryEntry('/album/a1');
		startFakeRouter();
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);

		await openPlaylist('p1');
		await pressBack();

		expect(reportedNavigations.at(-1)).toEqual({ type: 'popstate', pathname: '/album/a1' });
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/playlist/night-drive', crossingWrite(false));
	});

	// Moving between two songs of the same open album stays the same route
	// file (/album/[slug]/[song]/+page.svelte matches both), so it is the
	// frequent-churn case, not a crossing.
	it('writes a song-to-song move inside the same album straight to history', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2' })
		]);
		await openAlbum('a1');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		vi.mocked(goto).mockClear();

		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a1/s2');
	});

	// #275-review bycatch, pinned here as issue #281 promised: a song-to-song
	// move across album boundaries is still the same route file
	// (/album/[slug]/[song]/+page.svelte matches both, whichever album the
	// slug names), so it stays frequent-churn shallow routing too -- only the
	// route.id shape decides a crossing, never which resource it names.
	it('writes a song-to-song move across album boundaries straight to history too', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2', album_id: 'a2' })
		]);
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		vi.mocked(goto).mockClear();

		await selectSong(
			's2',
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2', album_id: 'a2' })
		);

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a2/s2');
	});

	// Issue #281: a take address is one segment deeper than its song's own
	// (/album/x/y -> /album/x/y/take/n), a route-file boundary again -- the
	// same isSongRoutePath boolean stays true on both sides, so this crossing
	// check must tell song and take apart too, not just album and song.
	it('crosses through the router from a song address to one of its takes', async () => {
		songList.set([song({ ...navigableSongDefaults(), slug: 's1' })]);
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		vi.mocked(goto).mockClear();

		selectedGenerationId.set('g1');
		persistLibraryHistory();

		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/s1/take/1'));
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1/s1/take/1', crossingWrite(true));
	});

	// Moving between two takes of the same open song stays the same route
	// file (/take/[n] matches both, whichever number it names), so it is the
	// frequent-churn case, not a crossing -- the same rule the album<->song
	// and song<->song cases above already carry one segment shallower.
	it('writes a take-to-take move inside the same song straight to history', async () => {
		songList.set([
			song({
				...navigableSongDefaults(),
				slug: 's1',
				generations: [generation(), generation({ id: 'g2', generation_number: 2 })]
			})
		]);
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		selectedGenerationId.set('g1');
		persistLibraryHistory();
		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/s1/take/1'));
		vi.mocked(goto).mockClear();

		selectedGenerationId.set('g2');
		persistLibraryHistory();

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a1/s1/take/2');
	});

	// Issue #286: /playlist/<slug> is its own route file, a sibling of /
	// and /album/<slug> rather than nested under it -- opening one from an
	// album address must cross through the router the same way the album
	// <-> song boundary already does above.
	it('crosses through the router from an album address to a playlist', async () => {
		await openAlbum('a1');
		vi.mocked(goto).mockClear();
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);

		await openPlaylist('p1');

		expect(vi.mocked(goto)).toHaveBeenCalledWith('/playlist/night-drive', crossingWrite(true));
		expect(window.location.pathname).toBe('/playlist/night-drive');
	});

	// Moving between two open playlists stays the same route file
	// (/playlist/[slug] matches both), so it is the frequent-churn case, not
	// a crossing -- the same rule album<->album and song<->song already
	// carry (Playlist<->Playlist is the one pair the crossing matrix does
	// not cross).
	it('writes a playlist-to-playlist move straight to history, not through the router', async () => {
		fetchPlaylists.mockResolvedValue([
			playlistItem({ share_slug: null }),
			playlistItem({ share_slug: null, id: 'p2', slug: 'morning-run', title: 'Morning Run' })
		]);
		await openPlaylist('p1');
		vi.mocked(goto).mockClear();

		await openPlaylist('p2');

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/playlist/morning-run');
	});
});

describe('the address an open album carries (issue #269)', () => {
	it('sets the album address when an album is opened', async () => {
		await openAlbum('a1');
		expect(window.location.pathname).toBe('/album/a1');
	});

	it('sets the song address when a song is opened, and the album address when it is left', async () => {
		await openAlbum('a1');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		expect(window.location.pathname).toBe('/album/a1/s1');
		backToCollection();
		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1'));
	});

	it('gives the wall back the home address when the album is only the rail context', async () => {
		await openAlbum('a1');
		await openLibraryWall();
		expect(window.location.pathname).toBe('/');
	});
});

describe('the address an open playlist carries (issue #286)', () => {
	it('sets the playlist address when a playlist is opened', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);
		await openPlaylist('p1');
		expect(window.location.pathname).toBe('/playlist/night-drive');
	});

	it('gives the wall back the home address when the playlist is only the rail context', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);
		await openPlaylist('p1');
		await openLibraryWall();
		expect(window.location.pathname).toBe('/');
	});
});

// The open song's address names it by slug (issue #275). A rename changes
// that slug server-side, and SongDetailView writes the renamed song straight
// back into songList (see onRenameSong) -- the same write every other song
// edit (lyrics, prompt, cover) already makes. This is the one place that can
// tell a slug change apart from those and pull the address along.
describe("a rename pulls the open song's address along (issue #275)", () => {
	it('replaces the address when the open song is renamed', async () => {
		await openAlbum('a1');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		const indexBeforeRename = historyEntry().index;
		vi.mocked(goto).mockClear();

		updateSongInList('s1', (s) => ({ ...s, slug: 'renamed' }));

		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/renamed'));
		expect(historyEntry().index).toBe(indexBeforeRename);
	});

	it('leaves the address alone for an edit that is not a rename', async () => {
		await openAlbum('a1');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		vi.mocked(goto).mockClear();

		updateSongInList('s1', (s) => ({ ...s, lyrics: 'a new verse' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a1/s1');
	});

	it("leaves a legacy ?song= address alone -- redirecting it onto its canonical address is (library)/+page.svelte's job (issue #284), not this rename-follow", async () => {
		replaceHistoryEntry('/?song=s1');
		selectedSongId.set('s1');

		updateSongInList('s1', (s) => ({ ...s, slug: 'renamed' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname + window.location.search).toBe('/?song=s1');
	});
});

// The open playlist's address names it by slug (issue #286), and a rename
// changes that slug server-side (unique_playlist_slug follows the title) --
// the same gap syncSongAddressToRename closes for songs above, mirrored here
// via updatePlaylistInList, the playlist equivalent of updateSongInList.
describe("a rename pulls the open playlist's address along (issue #286)", () => {
	it('replaces the address when the open playlist is renamed', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);
		await openPlaylist('p1');
		const indexBeforeRename = historyEntry().index;
		vi.mocked(goto).mockClear();

		updatePlaylistInList('p1', (p) => ({ ...p, slug: 'renamed' }));

		await vi.waitFor(() => expect(window.location.pathname).toBe('/playlist/renamed'));
		expect(historyEntry().index).toBe(indexBeforeRename);
	});

	it('leaves the address alone for an edit that is not a rename', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem({ share_slug: null })]);
		await openPlaylist('p1');
		vi.mocked(goto).mockClear();

		updatePlaylistInList('p1', (p) => ({ ...p, entry_count: 3 }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/playlist/night-drive');
	});
});

describe('openAlbum / openPlaylist', () => {
	it.each([
		['album', () => openAlbum('a1')],
		['playlist', () => openPlaylist('p1')]
	])('returns from a %s to the same mixed library and its saved scroll', async (_kind, open) => {
		captureLibraryScroll(240);

		await open();
		await openLibraryWall();

		expect(get(librarySurface)).toBe('browse');
		expect(get(libraryScrollAnchor)).toBe(240);
		expect(historyEntry()).toMatchObject({ surface: 'browse', scrollAnchor: 240 });
		expect(historyEntry()).not.toHaveProperty('filter');
	});

	it('opens an album collection and pushes one history entry', async () => {
		const before = historyEntry()?.index ?? 0;
		await openAlbum('a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(librarySurface)).toBe('detail');
		expect(historyEntry().index).toBe(before + 1);
	});

	it('opens a playlist collection and pushes one history entry', async () => {
		const before = historyEntry()?.index ?? 0;
		await openPlaylist('p1');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistId)).toBe('p1');
		expect(historyEntry().index).toBe(before + 1);
	});

	it('clears the open song when a new collection opens', async () => {
		await selectSong('s1');
		await openAlbum('a2');
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
	});
});

// #264 first gave this its own guard (ensureLibraryWorkspaceRoute), a
// precondition every entry point below had to call before writing history.
// Issue #265's S7 removed that guard once writeLibraryHistory's own crossing
// check (libraryRouteShape's 'external' shape, libraryContext.ts) was proven
// to reach the router for every one of these writes on its own -- these
// tests pin the crossing behaviour directly instead of the removed guard's
// call.
describe('opening a collection from off the library route', () => {
	it('openAlbum leaves settings for the album address with the album open', async () => {
		replaceHistoryEntry('/settings/voices');
		await openAlbum('a1');
		expect(window.location.pathname).toBe('/album/a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(librarySurface)).toBe('detail');
	});

	it('openPlaylist lands on the library route with the playlist open', async () => {
		replaceHistoryEntry('/settings/voices');
		await openPlaylist('p1');
		expect(window.location.pathname).toBe('/');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(librarySurface)).toBe('detail');
	});

	// The Rail keeps rendering the open album's tracks on every route (issue
	// #264's review found selectSong missing the same guard as openAlbum):
	// clicking a track from Settings must land on the library route too.
	it('selectSong lands on the song address with the song selected', async () => {
		replaceHistoryEntry('/settings/voices');
		selectSong('s1');
		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s1'));
		expect(window.location.pathname).toBe('/album/a1/s1');
	});

	// The one pairing removing the guard put at risk: openLibraryWall's own
	// write always targets '/', and before libraryRouteShape gained its
	// 'external' shape, '/settings/voices' and '/' both fell into the same
	// 'root' bucket (neither is an album or playlist address), so this write
	// would have taken the cheap same-shape branch -- a raw `history.
	// pushState` that changes the address bar to '/' while SvelteKit's router
	// stays mounted on Settings' route file underneath it.
	it('openLibraryWall leaves settings for the wall through a navigation, not shallow routing', async () => {
		replaceHistoryEntry('/settings/voices');
		await openLibraryWall();
		expect(window.location.pathname).toBe('/');
		expect(get(librarySurface)).toBe('browse');
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/', crossingWrite(false));
	});
});

// Back and Forward between the library and an app page (issue #1165): every
// library entry is the router's own, so the router navigates between the two
// pages instead of only moving the address.
describe('Back and Forward across an app page', () => {
	const SETTINGS = '/settings/voices' as const;

	function lastNavigation(): { type: string; pathname: string } | undefined {
		return reportedNavigations.at(-1);
	}

	beforeEach(() => {
		fetchPlaylists.mockResolvedValue([
			playlistItem({ share_slug: null }),
			playlistItem({ share_slug: null, id: 'p2', slug: 'morning-run', title: 'Morning Run' })
		]);
	});

	it('Back from Settings returns to the playlist left, and Forward to Settings', async () => {
		await openPlaylist('p1');
		captureLibraryScroll(320);
		persistLibraryHistory();
		const left = historyEntry();
		await goto(resolve(SETTINGS));

		await pressBack();

		expect(lastNavigation()).toEqual({ type: 'popstate', pathname: '/playlist/night-drive' });
		expect(location.pathname).toBe('/playlist/night-drive');
		expect(historyEntry()).toEqual(left);

		await pressForward();

		expect(lastNavigation()).toEqual({ type: 'popstate', pathname: SETTINGS });
		expect(location.pathname).toBe(SETTINGS);
	});

	// The second playlist is shallow routing over the first one's page, so Back
	// loads that page's route; its address route yields to the entry.
	it('Back from Settings onto a playlist opened over another shows the one left', async () => {
		await openPlaylist('p1');
		await openPlaylist('p2');
		await goto(resolve(SETTINGS));

		await pressBack();

		expect(fakePage.url.pathname).toBe('/playlist/night-drive');
		expect(location.pathname).toBe('/playlist/morning-run');
		await expect(openPlaylistAddress('night-drive')).resolves.toBe('found');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p2' });
		expect(historyEntry().collection).toEqual({ kind: 'playlist', id: 'p2' });
	});

	// SvelteKit cannot tell two entries of one navigation apart after a reload,
	// so Back between them is a navigation of its own there, and shallow
	// otherwise.
	it.each([
		{ reloaded: false, navigation: { type: 'goto', pathname: '/playlist/night-drive' } },
		{ reloaded: true, navigation: { type: 'popstate', pathname: '/playlist/night-drive' } }
	])(
		'Back onto a playlist another was opened over reports $navigation.type (reloaded: $reloaded)',
		async ({ reloaded, navigation }) => {
			await openPlaylist('p1');
			await openPlaylist('p2');
			if (reloaded) await reloadLibraryPage();

			await pressBack();

			expect(lastNavigation()).toEqual(navigation);
			expect(location.pathname).toBe('/playlist/night-drive');
			expect(historyEntry().collection).toEqual({ kind: 'playlist', id: 'p1' });
		}
	);

	it('Back from Settings after a reload returns to the playlist with what it showed', async () => {
		await openPlaylist('p1');
		captureLibraryScroll(480);
		persistLibraryHistory();
		const left = historyEntry();
		await reloadLibraryPage();
		await goto(resolve(SETTINGS));

		await pressBack();

		expect(lastNavigation()).toEqual({ type: 'popstate', pathname: '/playlist/night-drive' });
		expect(historyEntry()).toEqual(left);
	});
});

describe.each([
	['openAlbum', () => openAlbum('a1')],
	['openPlaylist', () => openPlaylist('p1')],
	['openLibraryWall', () => openLibraryWall()]
])('%s closes the rail drawer', (_name, action) => {
	it('closes an open drawer instead of leaving it over the new surface', async () => {
		toggleSidebar();
		expect(get(sidebarOpen)).toBe(true);
		await action();
		expect(get(sidebarOpen)).toBe(false);
	});
});

describe('selectSong keeps the rail context pinned to the song album', () => {
	it('opens a song and sets the collection to that song album, even with no prior collection', async () => {
		expect(get(openCollection)).toBeNull();
		await selectSong('s1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('switches the collection when the open collection is a different album', async () => {
		await openAlbum('a2');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('switches the collection when a playlist was open (song open beats playlist context)', async () => {
		await openPlaylist('p1');
		expect(get(openCollection)?.kind).toBe('playlist');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(selectedPlaylistId)).toBeNull();
	});

	it('leaves the collection untouched when it already matches the song album', async () => {
		await openAlbum('a1');
		const stateBefore = get(openCollection);
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		expect(get(openCollection)).toBe(stateBefore);
	});

	it('pushes a new history entry per selectSong call', async () => {
		const before = historyEntry()?.index ?? 0;
		await selectSong('s1');
		expect(historyEntry().index).toBe(before + 1);
	});

	it('pushes a new history entry when opening the first song from the album interior', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2' })
		]);
		await openAlbum('a1');
		const afterOpen = historyEntry().index;
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		expect(historyEntry().index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s1');
	});

	it('replaces the current history entry when moving to another song already inside the open collection', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2' })
		]);
		await openAlbum('a1');
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		const afterFirstSong = historyEntry().index;
		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));
		expect(historyEntry().index).toBe(afterFirstSong);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('pushes a new history entry when the song is outside the open collection', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2', album_id: 'a2' })
		]);
		await openAlbum('a1');
		const afterOpen = historyEntry().index;
		await selectSong(
			's2',
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2', album_id: 'a2' })
		);
		expect(historyEntry().index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('lands back on the album, not the wall, after opening two tracks in a row (issue #99)', async () => {
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2' })
		]);
		const wallIndex = historyEntry()?.index ?? 0;
		await openAlbum('a1');
		const albumIndex = historyEntry().index;
		expect(albumIndex).toBe(wallIndex + 1);
		await selectSong('s1', song({ ...navigableSongDefaults(), slug: 's1' }));
		const track1Index = historyEntry().index;
		expect(track1Index).toBe(albumIndex + 1);
		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));
		expect(historyEntry().index).toBe(track1Index);
	});
});

describe('opening a song recovers its generation state', () => {
	it('tracks a running generation independently of the failure lookup', async () => {
		const job = {
			id: 'running-job',
			type: 'generate',
			status: 'running',
			progress: 0.5,
			take_index: 1,
			take_count: 2,
			remaining_time_estimate: 60,
			error: null,
			error_type: null,
			started_at: null,
			completed_at: null
		};
		vi.stubGlobal(
			'EventSource',
			vi.fn().mockImplementation(() => ({ close: vi.fn() }))
		);
		fetchLastFailedGeneration.mockReturnValue(new Promise(() => {}));
		fetchActiveGeneration.mockResolvedValue(job);

		await selectSong('s1');

		expect(get(activeJobs)).toEqual([{ job, songId: 's1' }]);
		expect(fetchActiveGeneration).toHaveBeenCalledWith('s1');
	});

	it.each([
		{
			failure: 'with no network answer',
			error: new NetworkError('/api/songs/s1/active-generation', new TypeError('Failed to fetch')),
			shown: API_ERROR_GENERIC_MESSAGE
		},
		{
			failure: 'refused by the server',
			error: new ApiError(503, 'Generation service unavailable', '/api/songs/s1/active-generation'),
			shown: 'Generation service unavailable'
		}
	])(
		'says $shown once when the active generation lookup fails $failure, keeping the song open',
		async ({ error, shown }) => {
			fetchActiveGeneration.mockRejectedValue(error);

			await selectSong('s1');

			expect(get(selectedSongId)).toBe('s1');
			expect(get(toasts)).toEqual([expect.objectContaining({ type: 'error', message: shown })]);
		}
	);

	it('shows the cause of the last failed generation for a song opened after reload', async () => {
		fetchLastFailedGeneration.mockResolvedValue({
			job: {
				id: 'j1',
				type: 'generate',
				status: 'failed',
				progress: 0,
				error: 'boom',
				error_type: null,
				started_at: null,
				completed_at: '2026-01-02T00:00:00+00:00'
			}
		});
		await selectSong('s1');
		await vi.waitFor(() => expect(fetchLastFailedGeneration).toHaveBeenCalledWith('s1'));
		await vi.waitFor(() => expect(get(generationFailures).s1).toBe('boom'));
	});

	it('shows nothing when the API reports no failure to hydrate (e.g. a newer take supersedes it)', async () => {
		fetchLastFailedGeneration.mockResolvedValue({ job: null });
		await selectSong('s1');
		await vi.waitFor(() => expect(fetchLastFailedGeneration).toHaveBeenCalledWith('s1'));
		expect(get(generationFailures).s1).toBeUndefined();
	});
});

describe('song selection (dead song link, issue #237)', () => {
	it('clears the selection and shows a not-found toast for a dead song, without throwing', async () => {
		selectedSongId.set('dead');
		fetchSong.mockRejectedValue(new ApiError(404, 'Song not found', '/api/songs/dead'));

		await selectSong('dead');
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(get(selectedSongId)).toBeNull();
		expect(
			get(toasts).some((t) => t.type === 'error' && t.message === SONG_LINK_NOT_FOUND_TOAST)
		).toBe(true);
	});

	it.each([
		[new ApiError(500, 'Song loading failed', '/api/songs/s1'), 'Song loading failed'],
		[new TypeError('generations is not iterable'), TAKES_ERROR],
		[null, TAKES_ERROR]
	])(
		'shows the context-loading error with retry in Takes without a toast or clearing selection (%s)',
		async (error, message) => {
			songList.set([song({ ...navigableSongDefaults(), generations: [], generation_count: 2 })]);
			fetchSong.mockRejectedValue(error);
			const target = document.createElement('div');
			document.body.append(target);
			const view = mount(SongDetailView, { target });
			try {
				await selectSong('s1');
				await tick();

				await vi.waitFor(() => {
					const alerts = target.querySelectorAll('[role="alert"]');
					expect(alerts).toHaveLength(1);
					expect(alerts[0]).toHaveTextContent(message);
					expect(alerts[0].querySelector('button')?.getAttribute('aria-label')).toBe(
						TAKES_RETRY_LABEL
					);
				});
				expect(get(toasts)).toEqual([]);
				expect(get(selectedSongId)).toBe('s1');
			} finally {
				await unmount(view);
				target.remove();
			}
		}
	);

	it('leaves a valid song selection untouched', async () => {
		selectedSongId.set('s2');
		fetchSong.mockResolvedValue(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));

		await selectSong('s2');

		expect(get(selectedSongId)).toBe('s2');
		expect(get(toasts)).toHaveLength(0);
	});

	it('keeps a newer song selection when an earlier dead-link lookup finishes late', async () => {
		let rejectLookup: ((reason: Error) => void) | undefined;
		songList.set([
			song({
				...navigableSongDefaults(),
				slug: 's1',
				generation_count: 2,
				generations: [generation()]
			})
		]);
		fetchSong.mockImplementationOnce(
			() =>
				new Promise((_, reject) => {
					rejectLookup = reject;
				})
		);
		selectedSongId.set('s1');

		await selectSong('s1');
		await vi.waitFor(() => expect(fetchSong).toHaveBeenCalledWith('s1'));
		selectedSongId.set('s2');
		if (!rejectLookup) {
			throw new Error('Expected the song lookup to expose its rejection callback');
		}
		rejectLookup(new ApiError(404, 'Song not found', '/api/songs/s1'));
		await vi.waitFor(() => expect(fetchSong).toHaveBeenCalledWith('s1'));
		await Promise.resolve();

		expect(get(selectedSongId)).toBe('s2');
		expect(get(toasts)).toHaveLength(0);
	});
});

describe('the tab a song opens on (issue #1047)', () => {
	const secondSong = () => song({ ...navigableSongDefaults(), slug: 's2', id: 's2' });

	it('opens a song never opened this session on Edit', async () => {
		detailTab.set('takes');
		await selectSong('s1');
		expect(get(detailTab)).toBe('edit');
	});

	it('reopens a song on the tab last chosen for it', async () => {
		await selectSong('s1');
		navigateToSongTab('takes');
		await selectSong('s2', secondSong());
		expect(get(detailTab)).toBe('edit');
		await selectSong('s1');
		expect(get(detailTab)).toBe('takes');
	});

	it('records the chosen tab in the open history entry so a reload restores it', async () => {
		await selectSong('s1');
		const address = window.location.pathname;
		navigateToSongTab('takes');
		expect(historyEntry().detailTab).toBe('takes');
		expect(window.location.pathname).toBe(address);
	});

	it('keeps the current tab when stepping to the previous or next song', async () => {
		await selectSong('s1');
		navigateToSongTab('takes');
		await selectNeighborSong(secondSong());
		expect(get(detailTab)).toBe('takes');
	});

	it('opens the playing song from Now Playing on its remembered tab', async () => {
		await selectSong('s1');
		navigateToSongTab('takes');
		await selectSong('s2', secondSong());
		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's1' }), 'g1');
		expect(get(detailTab)).toBe('takes');
	});

	it('remembers Edit when an action moves the open song back onto it', async () => {
		await selectSong('s1');
		navigateToSongTab('takes');
		openEditTab();
		await selectSong('s2', secondSong());
		await selectSong('s1');
		expect(get(detailTab)).toBe('edit');
	});
});

describe('selectNeighborSong', () => {
	it('replaces the current history entry instead of pushing', async () => {
		await selectSong('s1');
		const afterFirst = historyEntry().index;
		await selectNeighborSong(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));
		expect(historyEntry().index).toBe(afterFirst);
		expect(get(selectedSongId)).toBe('s2');
	});
});

describe('backToCollection', () => {
	it('leaves the song and returns to the open collection detail', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		backToCollection();
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('detail');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('falls back to the wall when there is no open collection', async () => {
		await selectSong('s1');
		openCollection.set(null);
		backToCollection();
		expect(get(librarySurface)).toBe('browse');
	});
});

describe('a dirty draft guards song switch / leave', () => {
	afterEach(() => {
		discardDraft();
	});

	it('defers selectSong instead of switching while the draft is dirty', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('runs the deferred switch on Discard', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');
		songList.set([
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2' })
		]);

		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));
		discardDraft();
		await get(pendingDirtyNavigation)?.();
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s2');
	});

	it('stays put on Cancel', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('defers backToCollection and openLibraryWall the same way', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		backToCollection();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
		pendingDirtyNavigation.set(null);

		await openLibraryWall();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('defers selectNeighborSong the same way', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectNeighborSong(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('defers revealPlayingSong the same way', async () => {
		replaceHistoryEntry('/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }), 'g2');

		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	// Issue #265's S7 (review of #264): revealPlayingSong used to navigate to
	// the library workspace via ensureLibraryWorkspaceRoute *before*
	// guardDirtyNavigation ran, so Cancel on the confirm still left the person
	// pushed off whatever route they were on -- e.g. Repaint/Cover from
	// Now Playing while Settings is open (the draft and the playing take are
	// independent of the current route). The guard must run first, so parking
	// leaves the route untouched.
	it('does not navigate off the current route before the dirty-draft confirm resolves', async () => {
		replaceHistoryEntry('/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');
		replaceHistoryEntry('/settings/voices');
		vi.mocked(goto).mockClear();

		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }), 'g2');

		expect(window.location.pathname).toBe('/settings/voices');
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	// Issue #265 review of #264: onOpenShare's shared-take branch used to
	// await selectSong and then set selectedGenerationId as a follow-up step
	// -- guardDirtyNavigation resolves that promise the instant it parks a
	// dirty draft, so the pin ran against the still-open old song a microtask
	// later. Revealing the playing song keeps both changes in one guarded action.
	it('defers revealing a playing take the same way, without pinning the take against the old song', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }), 'g2');

		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	describe.each([
		['an album', () => openAlbum('a2'), { kind: 'album', id: 'a2' }],
		['a playlist', () => openPlaylist('p1'), { kind: 'playlist', id: 'p1' }]
	] as const)('opening %s from the phone drawer (issue #1143)', (_name, open, opened) => {
		async function openFromTheDrawerWithADirtyDraft(): Promise<void> {
			await openAlbum('a1');
			await selectSong('s1');
			loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
			setDraftLyrics('unsaved edit');
			toggleSidebar();
			await open();
		}

		it('holds the leave for the unsaved-changes dialog and closes the drawer over it', async () => {
			await openFromTheDrawerWithADirtyDraft();

			expect(get(pendingDirtyNavigation)).not.toBeNull();
			expect(get(selectedSongId)).toBe('s1');
			expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
			expect(get(sidebarOpen)).toBe(false);
		});

		it('leaves on Discard', async () => {
			await openFromTheDrawerWithADirtyDraft();
			discardDraft();
			await get(pendingDirtyNavigation)?.();
			pendingDirtyNavigation.set(null);

			expect(get(selectedSongId)).toBeNull();
			expect(get(openCollection)).toEqual(opened);
		});

		it('stays with the draft on Keep editing', async () => {
			await openFromTheDrawerWithADirtyDraft();
			pendingDirtyNavigation.set(null);

			expect(get(selectedSongId)).toBe('s1');
			expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
			expect(get(editLyrics)).toBe('unsaved edit');
		});
	});

	describe.each([
		[
			'a Settings row',
			() => followAppPageLink(new MouseEvent('click', { button: 0 }), '/settings/playback')
		],
		['a page search hit', () => openRailSearchTarget({ kind: 'page', href: '/settings/playback' })]
	] as const)('leaving for an app page through %s (issue #1143)', (_name, leave) => {
		async function leaveWithADirtyDraft(): Promise<void> {
			await openAlbum('a1');
			await selectSong('s1');
			loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
			setDraftLyrics('unsaved edit');
			toggleSidebar();
			vi.mocked(goto).mockClear();
			await leave();
		}

		it('holds the leave for the unsaved-changes dialog and keeps the route', async () => {
			await leaveWithADirtyDraft();

			expect(get(pendingDirtyNavigation)).not.toBeNull();
			expect(window.location.pathname).toBe('/album/a1/s1');
			expect(vi.mocked(goto)).not.toHaveBeenCalled();
			expect(get(sidebarOpen)).toBe(false);
		});

		it('leaves for the page on Discard', async () => {
			await leaveWithADirtyDraft();
			discardDraft();
			await get(pendingDirtyNavigation)?.();
			pendingDirtyNavigation.set(null);

			expect(window.location.pathname).toBe('/settings/playback');
		});

		it('keeps the page address when Discard answers the dialog, which steps off its own entry first', async () => {
			const stopNavigation = initNavigation();
			try {
				await leaveWithADirtyDraft();
				const dialog = dialogHistoryLayer('confirm-dialog', () => undefined);
				dialog.hold(document.createElement('div'));
				await vi.waitFor(() => expect(historyEntry().layer).toBe('confirm-dialog'));
				const leave = get(pendingDirtyNavigation);
				pendingDirtyNavigation.set(null);
				const dialogEntryLeft = new Promise((landed) =>
					window.addEventListener('popstate', landed, { once: true })
				);
				let leaving: void | Promise<void> = undefined;

				dialog.answer(() => {
					discardDraft();
					leaving = leave?.();
				})();
				await Promise.all([dialogEntryLeft, leaving]);

				expect(window.location.pathname).toBe('/settings/playback');
			} finally {
				stopNavigation();
			}
		});
	});

	it('never prompts when the draft is clean', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));

		await selectSong('s2', song({ ...navigableSongDefaults(), slug: 's2', id: 's2' }));

		expect(get(selectedSongId)).toBe('s2');
		expect(get(pendingDirtyNavigation)).toBeNull();
	});
});

describe('openCollectionEntry', () => {
	it('goes back to the collection when a song inside it is open', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		openCollectionEntry({ kind: 'album', id: 'a1' });
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens the collection when no song is open', async () => {
		openCollectionEntry({ kind: 'playlist', id: 'p1' });
		await Promise.resolve();
		expect(get(openCollection)?.kind).toBe('playlist');
	});
});

describe('goBack', () => {
	it('defers to the browser history when a predecessor exists', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		const back = watchBack();
		goBack();
		expect(back.presses()).toBe(1);
		back.stop();
	});

	it('returns to the wall and clears selection when there is no predecessor', async () => {
		await selectSong('s1');
		replaceHistoryEntry('/');
		goBack();
		expect(get(librarySurface)).toBe('browse');
		expect(get(selectedSongId)).toBeNull();
	});
});

describe('revealPlayingSong', () => {
	it('opens the song at its own address, then crosses again to the take', async () => {
		replaceHistoryEntry('/');
		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's1' }), 'g1');
		// The song's own address crosses the route boundary once; the take is
		// its own route file too (issue #281), so pinning it crosses a second
		// time, queued behind the first.
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		await vi.waitFor(() =>
			expect(window.location.pathname + window.location.search).toBe('/album/a1/s1/take/1')
		);
		expect(vi.mocked(goto).mock.calls.map((call) => call[0])).toEqual([
			'/album/a1/s1',
			'/album/a1/s1/take/1'
		]);
	});

	// Issue #265's S7 removed the separate ensureLibraryWorkspaceRoute guard
	// (#264) that used to force a `goto('/')` detour before anything else ran;
	// writeLibraryHistory's own crossing check (libraryRouteShape's 'external'
	// shape) now reaches the router directly, so a reveal from off the
	// library route lands straight on the song's own address instead of
	// stopping at '/' first.
	it('crosses directly from another route to the song address, with no detour through /', async () => {
		replaceHistoryEntry('/settings');
		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's1' }), 'g1');
		await vi.waitFor(() =>
			expect(window.location.pathname + window.location.search).toBe('/album/a1/s1/take/1')
		);
		expect(vi.mocked(goto).mock.calls.map((call) => call[0])).toEqual([
			'/album/a1/s1',
			'/album/a1/s1/take/1'
		]);
	});
});

// A legacy `/?song=<uuid>` (and `&gen=<uuid>`) deep link used to be read and
// applied right here; since issue #284, (library)/+page.svelte owns that
// instead -- resolveLegacySongQueryAddress (libraryContext.test.ts) covers
// the id -> slug/number lookup and its unknown-song 404, and
// e2e/album-address.spec.ts covers the redirect landing on the real router.
describe('initNavigation', () => {
	it('applies the library a popstate lands on from its router entry', async () => {
		const cleanup = initNavigation();
		const album = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'album' as const, id: 'a2' }
		};

		window.dispatchEvent(
			new PopStateEvent('popstate', {
				state: {
					'sveltekit:history': 7,
					'sveltekit:navigation': 3,
					'sveltekit:states': { library: album }
				}
			})
		);

		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' }));
		expect(get(librarySurface)).toBe('detail');
		cleanup();
	});

	it('lands on the wall when Back reaches an entry of the removed create form', async () => {
		await openAlbum('a1');
		const cleanup = initNavigation();
		const createFormEntry = {
			...libraryRootState(),
			surface: 'create',
			collection: { kind: 'album' as const, id: 'a1' }
		};

		window.dispatchEvent(new PopStateEvent('popstate', { state: createFormEntry }));

		await vi.waitFor(() => expect(get(openCollection)).toBeNull());
		expect(get(librarySurface)).toBe('browse');
		cleanup();
	});

	it('does not attempt a save on browser-back when the draft is clean', async () => {
		replaceHistoryEntry('/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(updateSong).not.toHaveBeenCalled();
		cleanup();
	});

	// Issue #286 (found against a real stack, not jsdom -- see
	// playlist-address.spec.ts): a cold tab on an address route has no
	// LibraryHistoryState yet, same as a cold `/`, but every one of those
	// routes owns its own resolver (openAlbumAddress / openSongAddress /
	// openTakeAddress / openPlaylistAddress) that writes the real entry once
	// it lands -- found or, honestly, not. This branch used to seed a default
	// root entry unconditionally on that same "no state yet" signal, which
	// raced an *unknown* address (nothing else ever writes for it) and always
	// won once the live stream's own bootstrap finished, replacing the
	// intended 404 overlay with a crossing `goto('/')` back to the wall.
	it('does not seed a default root entry on an address route, leaving its own resolver the only writer', () => {
		replaceHistoryEntry('/album/ghost');

		const cleanup = initNavigation();

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(historyEntry()).toBeNull();
		cleanup();
	});

	it('still seeds a default root entry on a genuinely cold "/" visit', async () => {
		replaceHistoryEntry('/');

		const cleanup = initNavigation();

		await vi.waitFor(() => expect(isLibraryHistoryState(historyEntry())).toBe(true));
		cleanup();
	});
});

// Browser or phone Back has already moved the address when the library hears
// it, so a dirty draft puts the song's entry back and asks the same
// unsaved-changes question as every other way out (issue #1143 U2): Back never
// saves or discards the draft by itself.
describe('Back with a dirty draft asks before it leaves (issue #1143)', () => {
	let target: HTMLElement;
	let view: ReturnType<typeof mount>;
	let stopNavigation: () => void;

	beforeEach(() => {
		stopNavigation = initNavigation();
		target = document.createElement('div');
		document.body.append(target);
		view = mount(SongDetailView, { target });
	});

	afterEach(async () => {
		discardDraft();
		await unmount(view);
		target.remove();
		stopNavigation();
	});

	async function editTheSongOpenedFrom(open: () => Promise<unknown>): Promise<void> {
		await open();
		await selectSong('s1');
		await libraryHistoryStepsLanded();
		await tick();
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');
	}

	function unsavedChangesDialog(): HTMLElement | null {
		return document.querySelector(`[role="dialog"][aria-label="${EDITOR_UNSAVED_TITLE}"]`);
	}

	async function pressBackAndSeeTheQuestion(): Promise<void> {
		await pressBack();
		await vi.waitFor(() => expect(unsavedChangesDialog()).not.toBeNull());
		await libraryHistoryStepsLanded();
	}

	function answer(label: string): void {
		const buttons = Array.from(unsavedChangesDialog()?.querySelectorAll('button') ?? []);
		const button = buttons.find((candidate) => candidate.textContent?.trim() === label);
		if (!button) throw new Error(`no "${label}" in the unsaved-changes dialog`);
		button.click();
	}

	async function expectOnTheSongWithItsDraft(): Promise<void> {
		await vi.waitFor(() => expect(historyEntry().layer).toBeUndefined());
		expect(window.location.pathname).toBe('/album/a1/s1');
		expect(historyEntry().songId).toBe('s1');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	}

	it('asks, with the address and entry back on the song and nothing saved', async () => {
		await editTheSongOpenedFrom(() => openAlbum('a1'));

		await pressBackAndSeeTheQuestion();

		expect(window.location.pathname).toBe('/album/a1/s1');
		expect(historyEntry().songId).toBe('s1');
		expect(get(selectedSongId)).toBe('s1');
		expect(updateSong).not.toHaveBeenCalled();
	});

	it('stays on the song with the draft on Cancel', async () => {
		await editTheSongOpenedFrom(() => openAlbum('a1'));
		await pressBackAndSeeTheQuestion();

		answer(DIALOG_CANCEL_LABEL);

		await vi.waitFor(() => expect(unsavedChangesDialog()).toBeNull());
		await expectOnTheSongWithItsDraft();
		expect(updateSong).not.toHaveBeenCalled();
	});

	it('leaves for the entry Back reached on Discard, without saving', async () => {
		await editTheSongOpenedFrom(() => openAlbum('a1'));
		await pressBackAndSeeTheQuestion();

		answer(EDITOR_UNSAVED_DISCARD_LABEL);

		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());
		expect(window.location.pathname).toBe('/album/a1');
		expect(historyEntry().songId).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(updateSong).not.toHaveBeenCalled();
	});

	it('saves the draft, then leaves for the entry Back reached, on Save', async () => {
		await editTheSongOpenedFrom(() => openAlbum('a1'));
		vi.mocked(updateSong).mockResolvedValue(
			song({ ...navigableSongDefaults(), slug: 's1', lyrics: 'unsaved edit' })
		);
		await pressBackAndSeeTheQuestion();

		answer(EDITOR_UNSAVED_SAVE_LABEL);

		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());
		expect(window.location.pathname).toBe('/album/a1');
		expect(updateSong).toHaveBeenCalledWith(
			's1',
			expect.objectContaining({ lyrics: 'unsaved edit' })
		);
	});

	// The question keeps its owner: the song stays open, so the next way out
	// asks again instead of parking with nobody to answer it.
	it('stays on the song when Save fails, and the next way out asks again', async () => {
		await editTheSongOpenedFrom(() => openAlbum('a1'));
		vi.mocked(updateSong).mockRejectedValue(
			new NetworkError('/api/songs/s1', new TypeError('Failed to fetch'))
		);
		await pressBackAndSeeTheQuestion();

		answer(EDITOR_UNSAVED_SAVE_LABEL);

		await vi.waitFor(() =>
			expect(get(toasts)).toEqual([
				expect.objectContaining({ type: 'error', message: EDITOR_SAVE_FAILED })
			])
		);
		await expectOnTheSongWithItsDraft();
		await openAlbum('a2');
		await vi.waitFor(() => expect(unsavedChangesDialog()).not.toBeNull());
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('asks on Back onto the app page the song was opened from, and Discard returns there', async () => {
		await editTheSongOpenedFrom(() => goto(resolve('/settings/playback')));

		await pressBackAndSeeTheQuestion();
		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/s1'));
		expect(get(selectedSongId)).toBe('s1');

		answer(EDITOR_UNSAVED_DISCARD_LABEL);

		await vi.waitFor(() => expect(window.location.pathname).toBe('/settings/playback'));
		expect(updateSong).not.toHaveBeenCalled();
	});

	// After a reload, Back onto the song opened before the one shown is a
	// router navigation, which resolves that song's address while the question
	// about the draft left behind is still open.
	it('keeps the song shown when the address route Back loads resolves while it asks', async () => {
		const tide = song({ ...navigableSongDefaults(), slug: 's1' });
		const other = song({ ...navigableSongDefaults(), id: 's2', slug: 's2', album_id: 'a2' });
		songList.set([tide, other]);
		fetchSong.mockResolvedValue(tide);
		await selectSong('s1');
		await selectSong('s2', other);
		await reloadLibraryPage();
		await tick();
		loadSongData(other);
		setDraftLyrics('unsaved edit');

		await pressBackAndSeeTheQuestion();
		await expect(openSongAddress('a1', 's1')).resolves.toBe('found');

		expect(get(selectedSongId)).toBe('s2');
		expect(window.location.pathname).toBe('/album/a2/s2');
		expect(unsavedChangesDialog()).not.toBeNull();
		expect(updateSong).not.toHaveBeenCalled();
	});
});

// On a phone the full Now Playing surface is a pushed screen, so the phone's
// own Back must leave it for the library it covers rather than for whatever
// entry sits below that library (issue #1002).
describe('full Now Playing owns one history entry', () => {
	const origins = [
		{
			origin: 'a playlist',
			open: () => openPlaylist('p1'),
			library: { collection: { kind: 'playlist', id: 'p1' }, songId: null }
		},
		{
			origin: 'a song opened from its album',
			open: async () => {
				await openAlbum('a1');
				await selectSong('s1');
			},
			library: { collection: { kind: 'album', id: 'a1' }, songId: 's1' }
		}
	];

	let stopNavigation: () => void = () => undefined;

	beforeEach(() => {
		nowPlayingDockable.set(false);
		stopNavigation = initNavigation();
	});

	afterEach(() => {
		stopNavigation();
		closeNowPlaying();
		nowPlayingDockable.set(false);
		setDesktopNowPlayingSurface('docked');
	});

	function libraryShown(): Record<string, unknown> {
		return {
			collection: get(openCollection),
			songId: get(selectedSongId),
			surface: get(librarySurface)
		};
	}

	it.each(origins)(
		'popstate while the compact Now Playing is open closes it and keeps the library state of $origin',
		async ({ open, library }) => {
			await open();
			const below = historyEntry().index;

			openNowPlaying('take');
			await pressBack();

			await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
			expect(libraryShown()).toEqual({ ...library, surface: 'detail' });
			expect(historyEntry()).toMatchObject({ index: below, ...library });
		}
	);

	it.each(origins)(
		'closing the compact Now Playing steps back off its entry onto $origin',
		async ({ open, library }) => {
			await open();
			const below = historyEntry().index;
			openNowPlaying('take');
			await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

			closeNowPlaying();

			await vi.waitFor(() => expect(historyEntry().index).toBe(below));
			expect(libraryShown()).toEqual({ ...library, surface: 'detail' });
		}
	);

	it('Back from the compact Now Playing leaves a dirty draft unsaved', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ ...navigableSongDefaults(), slug: 's1' }));
		setDraftLyrics('unsaved edit');
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

		await pressBack();

		await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
		expect(get(isDirty)).toBe(true);
		expect(updateSong).not.toHaveBeenCalled();
		discardDraft();
	});

	async function reloadBeforeNavigationStarts(): Promise<void> {
		persistLibraryHistory();
		stopNavigation();
		resetNavigationForTests();
		closeNowPlaying();
		await reloadLibraryPage();
	}

	it.each([
		{
			way: 'a reload',
			reach: async () => {
				await reloadBeforeNavigationStarts();
				stopNavigation = initNavigation();
			}
		},
		{
			way: 'Forward after Back closed it',
			reach: async () => {
				await pressBack();
				await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
				await pressForward();
			}
		}
	])('steps off the Now Playing entry it reaches by $way', async ({ reach }) => {
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

		await reach();

		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		expect(get(nowPlayingOpen)).toBe(false);
		expect(libraryShown()).toEqual({
			collection: { kind: 'playlist', id: 'p1' },
			songId: null,
			surface: 'detail'
		});
	});

	it('a reload on a sheet entry over Now Playing steps off both entries onto the playlist', async () => {
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('take');
		const sheet = historyLayerState('a-sheet', false);
		const leaveSheetOwner = sheet.subscribe(() => undefined);
		sheet.set(true);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

		await reloadBeforeNavigationStarts();
		stopNavigation = initNavigation();

		await vi.waitFor(() => {
			expect(historyEntry().index).toBe(below);
			expect(currentLibraryHistoryState()).toBe(historyEntry());
		});
		expect(get(nowPlayingOpen)).toBe(false);
		expect(libraryShown()).toEqual({
			collection: { kind: 'playlist', id: 'p1' },
			songId: null,
			surface: 'detail'
		});
		leaveSheetOwner();
	});

	it('stays on the playlist Back reaches from the Now Playing entry a reload left before navigation started', async () => {
		await openPlaylist('p1');
		const below = historyEntry().index;
		const playlistPath = location.pathname;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		await reloadBeforeNavigationStarts();
		await pressBack();

		stopNavigation = initNavigation();

		await vi.waitFor(() => expect(currentLibraryHistoryState()).toBe(historyEntry()));
		expect(historyEntry().index).toBe(below);
		expect(location.pathname).toBe(playlistPath);
	});

	it('Forward onto a Now Playing entry the library below has since outgrown shows the library of the entry it steps back onto', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		await pressBack();
		await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
		backToCollection();
		await vi.waitFor(() => expect(historyEntry()).toMatchObject({ index: below, songId: null }));
		await pressForward();

		const collectionEntry = {
			collection: { kind: 'album', id: 'a1' },
			songId: null
		};
		await vi.waitFor(() => {
			expect(historyEntry()).toMatchObject({ index: below, ...collectionEntry });
			expect(libraryShown()).toEqual({ ...collectionEntry, surface: 'detail' });
		});
	});

	it('opens the playing song from Now Playing straight on top of its origin', async () => {
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('take');

		closeNowPlaying();
		await revealPlayingSong(song({ ...navigableSongDefaults(), slug: 's1' }), 'g1');

		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({ index: below + 1, songId: 's1', generationId: 'g1' })
		);
		await pressBack();
		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({
				index: below,
				collection: { kind: 'playlist', id: 'p1' },
				songId: null
			})
		);
	});

	it('the docked desktop panel leaves no history entry behind', async () => {
		nowPlayingDockable.set(true);
		await openPlaylist('p1');
		const before = { length: historyLength(), index: historyEntry().index };

		openNowPlaying('queue');
		closeNowPlaying();

		expect({ length: historyLength(), index: historyEntry().index }).toEqual(before);
	});

	it.each([
		{
			way: 'expanded from the docked panel',
			open: () => {
				openNowPlaying('queue');
				expandNowPlaying();
			}
		},
		{
			way: 'opened straight onto the remembered full surface',
			open: () => {
				setDesktopNowPlayingSurface('full');
				openNowPlaying('queue');
			}
		}
	])(
		'Back from the full surface $way on the desktop docks it over the same playlist and remembers the panel',
		async ({ open }) => {
			nowPlayingDockable.set(true);
			await openPlaylist('p1');
			const below = historyEntry().index;
			open();
			await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

			await pressBack();

			await vi.waitFor(() => expect(get(nowPlayingSurface)).toBe('docked'));
			expect(localStorage.getItem('nowPlayingDesktopSurface')).toBe('docked');
			expect(historyEntry()).toMatchObject({
				index: below,
				collection: { kind: 'playlist', id: 'p1' }
			});
			expect(libraryShown()).toEqual({
				collection: { kind: 'playlist', id: 'p1' },
				songId: null,
				surface: 'detail'
			});
		}
	);

	it('docking the expanded panel steps back off its entry, so the next Back reaches the page before', async () => {
		nowPlayingDockable.set(true);
		await openAlbum('a1');
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('queue');
		expandNowPlaying();
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

		dockNowPlaying();
		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		await pressBack();

		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({
				index: below - 1,
				collection: { kind: 'album', id: 'a1' }
			})
		);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('the next Back after Back closed Now Playing reaches the page before', async () => {
		await openAlbum('a1');
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		await pressBack();
		await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));

		await pressBack();

		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' }));
		expect(historyEntry()).toMatchObject({ index: below - 1 });
	});

	it('a docked panel the window narrows into the full surface writes no history', async () => {
		nowPlayingDockable.set(true);
		await openPlaylist('p1');
		openNowPlaying('queue');
		const before = { length: historyLength(), index: historyEntry().index };

		nowPlayingDockable.set(false);
		await tick();

		expect(get(nowPlayingSurface)).toBe('full');
		expect({ length: historyLength(), index: historyEntry().index }).toEqual(before);
	});

	it('keeps its entry when the window grows room for the docked panel, and Back then docks it', async () => {
		await openPlaylist('p1');
		const below = historyEntry().index;
		openNowPlaying('queue');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		const opened = { length: historyLength(), index: historyEntry().index };

		nowPlayingDockable.set(true);
		await tick();
		expect({ length: historyLength(), index: historyEntry().index }).toEqual(opened);
		await pressBack();

		await vi.waitFor(() => expect(get(nowPlayingSurface)).toBe('docked'));
		expect(historyEntry().index).toBe(below);
	});
});

describe('the phone rail drawer owns one history entry', () => {
	let stopNavigation: () => void = () => undefined;

	beforeEach(async () => {
		stopNavigation = initNavigation();
		await openPlaylist('p1');
	});

	afterEach(() => {
		stopNavigation();
		closeSidebar();
	});

	async function openDrawer(): Promise<{ below: number; path: string }> {
		const below = historyEntry().index;
		const path = location.pathname;
		toggleSidebar();
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		return { below, path };
	}

	it('Back closes the drawer and keeps the address and the playlist', async () => {
		const { below, path } = await openDrawer();

		await pressBack();

		await vi.waitFor(() => expect(get(sidebarOpen)).toBe(false));
		expect(location.pathname).toBe(path);
		expect(historyEntry()).toMatchObject({
			index: below,
			collection: { kind: 'playlist', id: 'p1' }
		});
	});

	it('closing the drawer by its own control steps back off its entry', async () => {
		const { below, path } = await openDrawer();

		closeSidebar();

		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		expect(location.pathname).toBe(path);
	});

	it.each([
		{ way: 'a row that opens an album', go: () => openAlbum('a1') },
		{
			way: 'a rail search page target',
			go: () => openRailSearchTarget({ kind: 'page', href: '/settings/playback' })
		},
		{
			way: 'a Settings link',
			go: () => followAppPageLink(new MouseEvent('click', { button: 0 }), '/settings/voices')
		}
	])(
		'leaving the drawer by $way leaves no entry behind: one Back lands on the playlist entry',
		async ({ go }) => {
			const { below, path } = await openDrawer();

			await go();
			await vi.waitFor(() => expect(location.pathname).not.toBe(path));
			expect(get(sidebarOpen)).toBe(false);
			await pressBack();

			await vi.waitFor(() => expect(location.pathname).toBe(path));
			expect(historyEntry()).toMatchObject({
				index: below,
				collection: { kind: 'playlist', id: 'p1' }
			});
		}
	);

	// Issue #1165: a page written over the drawer's entry would keep that
	// entry's place among the router's navigations, and Back onto the playlist
	// would then move the address without loading the playlist's page.
	it('a Settings link pushes Settings over the playlist: Back navigates to the playlist, Forward to Settings', async () => {
		const { below, path } = await openDrawer();

		followAppPageLink(new MouseEvent('click', { button: 0 }), '/settings/voices');
		await vi.waitFor(() => expect(location.pathname).toBe('/settings/voices'));
		await pressBack();

		expect(reportedNavigations.at(-1)).toEqual({ type: 'popstate', pathname: path });
		expect(historyEntry()).toMatchObject({
			index: below,
			collection: { kind: 'playlist', id: 'p1' }
		});

		await pressForward();

		expect(reportedNavigations.at(-1)).toEqual({ type: 'popstate', pathname: '/settings/voices' });
	});
});

describe('a menu kept in historyLayerState owns one history entry while open', () => {
	let stopNavigation: () => void = () => undefined;
	const owners: Array<() => void> = [];

	beforeEach(async () => {
		stopNavigation = initNavigation();
		await openAlbum('a1');
		await openPlaylist('p1');
	});

	afterEach(() => {
		for (const leave of owners.splice(0)) leave();
		stopNavigation();
		closeNowPlaying();
	});

	function ownedMenu(id = 'a-menu'): Writable<boolean> {
		const menu = historyLayerState(id, false);
		owners.push(menu.subscribe(() => undefined));
		return menu;
	}

	async function openOnTopOfPlaylist(menu: Writable<boolean>): Promise<number> {
		const below = historyEntry().index;
		menu.set(true);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		return below;
	}

	function playlistStands(below: number): void {
		expect(historyEntry()).toMatchObject({
			index: below,
			collection: { kind: 'playlist', id: 'p1' },
			songId: null
		});
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
	}

	interface ShownLayer {
		open: () => void;
		isOpen: () => boolean;
	}

	function confirmDialog(): ShownLayer {
		let shown = false;
		const dialog = dialogHistoryLayer('confirm-dialog', () => (shown = false));
		return {
			open: () => {
				shown = true;
				owners.push(dialog.hold(document.createElement('div')) ?? (() => undefined));
			},
			isOpen: () => shown
		};
	}

	const layerKinds: Array<{ kind: string; layer: () => ShownLayer }> = [
		{
			kind: 'a menu',
			layer: () => {
				const menu = ownedMenu();
				return { open: () => menu.set(true), isOpen: () => get(menu) };
			}
		},
		{ kind: 'a dialog', layer: confirmDialog },
		{
			kind: 'the drawer',
			layer: () => ({ open: toggleSidebar, isOpen: () => get(sidebarOpen) })
		},
		{
			kind: 'full Now Playing',
			layer: () => ({ open: () => openNowPlaying('take'), isOpen: () => get(nowPlayingOpen) })
		}
	];

	describe.each([
		{ way: 'Escape', close: () => void closeTopLayer() },
		{ way: 'Back', close: pressBack }
	])('$way closes the topmost layer and nothing below it (issue #1182)', ({ close }) => {
		beforeEach(() => nowPlayingDockable.set(false));

		afterEach(closeSidebar);

		it.each(layerKinds)('closes $kind and keeps the playlist below it', async ({ layer }) => {
			const shown = layer();
			const below = historyEntry().index;
			shown.open();
			await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

			await close();

			await vi.waitFor(() => expect(historyEntry().index).toBe(below));
			expect(shown.isOpen()).toBe(false);
			playlistStands(below);
		});

		it('closes a menu over full Now Playing and leaves Now Playing open', async () => {
			const below = historyEntry().index;
			openNowPlaying('take');
			const menu = ownedMenu();
			menu.set(true);
			await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

			await close();

			await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
			expect(get(menu)).toBe(false);
			expect(get(nowPlayingOpen)).toBe(true);
		});
	});

	it('Back closes the open menu and keeps the playlist below it', async () => {
		const menu = ownedMenu();
		const below = await openOnTopOfPlaylist(menu);

		await pressBack();

		await vi.waitFor(() => expect(get(menu)).toBe(false));
		playlistStands(below);
	});

	it('closing the menu itself steps back off its entry, so one Back leaves the playlist', async () => {
		const menu = ownedMenu();
		const below = await openOnTopOfPlaylist(menu);

		menu.set(false);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		await pressBack();

		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' }));
		expect(historyEntry().index).toBe(below - 1);
	});

	it('a menu item that navigates leaves exactly one Back to the playlist', async () => {
		const menu = ownedMenu();
		const below = await openOnTopOfPlaylist(menu);

		menu.set(false);
		await selectSong('s1');
		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({ index: below + 1, songId: 's1' })
		);
		await pressBack();

		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());
		playlistStands(below);
	});

	it('an album row in the drawer over an open menu, which closes that menu, lands on the album and one Back leaves it', async () => {
		const menu = ownedMenu();
		const below = await openOnTopOfPlaylist(menu);
		toggleSidebar();
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

		const going = openAlbum('a1');
		menu.set(false);
		await going;
		await vi.waitFor(() => expect(currentLibraryHistoryState()).toBe(historyEntry()));

		expect(location.pathname).toBe('/album/a1');
		expect(historyEntry()).toMatchObject({ collection: { kind: 'album', id: 'a1' } });
		await pressBack();

		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' }));
		playlistStands(below);
	});

	it('open, close and open again in quick succession end on one entry that Back closes', async () => {
		const menu = ownedMenu();
		const below = historyEntry().index;

		menu.set(true);
		menu.set(false);
		menu.set(true);
		await vi.waitFor(() => expect(currentLibraryHistoryState()).toBe(historyEntry()));
		expect(historyEntry().index).toBe(below + 1);
		await pressBack();

		await vi.waitFor(() => expect(get(menu)).toBe(false));
		playlistStands(below);
	});

	it('Back over a sheet in Now Playing closes only the sheet; the next Back closes Now Playing', async () => {
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		const sheet = ownedMenu('a-sheet');
		sheet.set(true);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

		await pressBack();
		await vi.waitFor(() => expect(get(sheet)).toBe(false));
		expect(get(nowPlayingOpen)).toBe(true);
		await pressBack();

		await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
		playlistStands(below);
	});

	it('a sheet in Now Playing closed and opened again in quick succession keeps both entries for Back', async () => {
		const below = historyEntry().index;
		openNowPlaying('take');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));
		const sheet = ownedMenu('a-sheet');
		sheet.set(true);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

		sheet.set(false);
		sheet.set(true);
		await vi.waitFor(() => expect(currentLibraryHistoryState()).toBe(historyEntry()));
		expect(historyEntry().index).toBe(below + 2);
		await pressBack();
		await vi.waitFor(() => expect(get(sheet)).toBe(false));
		expect(get(nowPlayingOpen)).toBe(true);
		await pressBack();

		await vi.waitFor(() => expect(get(nowPlayingOpen)).toBe(false));
		playlistStands(below);
	});

	it('closing Now Playing under an open sheet closes the sheet and leaves both entries', async () => {
		const below = historyEntry().index;
		openNowPlaying('take');
		const sheet = ownedMenu('a-sheet');
		sheet.set(true);
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 2));

		closeNowPlaying();

		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		expect(get(sheet)).toBe(false);
		playlistStands(below);
	});

	it('a menu whose owner goes away while it is open leaves its entry', async () => {
		const menu = historyLayerState('a-menu', false);
		const leaveOwner = menu.subscribe(() => undefined);
		const below = await openOnTopOfPlaylist(menu);

		leaveOwner();

		await vi.waitFor(() => expect(historyEntry().index).toBe(below));
		playlistStands(below);
	});

	it('a playlist entry menu moving from one row to another keeps one entry', async () => {
		const entryMenu = historyLayerState<string | null>('an-entry-menu', null);
		owners.push(entryMenu.subscribe(() => undefined));
		const below = historyEntry().index;
		entryMenu.set('e1');
		await vi.waitFor(() => expect(historyEntry().index).toBe(below + 1));

		entryMenu.set('e2');
		await pressBack();

		await vi.waitFor(() => expect(get(entryMenu)).toBeNull());
		playlistStands(below);
	});
});

describe('overlays outside the library', () => {
	it('hold a layer Escape closes on /settings, and opening the drawer or a menu there writes no history', () => {
		replaceHistoryEntry('/settings/playback');
		const before = { length: historyLength(), state: historyEntry() };
		const menu = historyLayerState('a-menu', false);
		const leaveOwner = menu.subscribe(() => undefined);

		toggleSidebar();
		menu.set(true);

		expect({ length: historyLength(), state: historyEntry() }).toEqual(before);
		expect(closeTopLayer()).toBe(true);
		expect(get(menu)).toBe(false);
		expect(get(sidebarOpen)).toBe(true);
		expect(closeTopLayer()).toBe(true);
		expect(get(sidebarOpen)).toBe(false);
		expect(closeTopLayer()).toBe(false);
		leaveOwner();
	});
});

describe('openRailSearchTarget', () => {
	it('uses the Library action for the Library page target', async () => {
		replaceHistoryEntry('/');
		selectedSongId.set('s1');
		librarySurface.set('detail');
		toggleSidebar();

		await openRailSearchTarget({ kind: 'page', href: '/' });

		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
		expect(get(sidebarOpen)).toBe(false);
	});

	it('opens one page target and closes the rail drawer', async () => {
		replaceHistoryEntry('/');
		toggleSidebar();
		expect(get(sidebarOpen)).toBe(true);

		await openRailSearchTarget({ kind: 'page', href: '/settings/playback' });

		expect(get(sidebarOpen)).toBe(false);
		expect(window.location.pathname).toBe('/settings/playback');
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/settings/playback');
	});
});

describe('album track neighbors', () => {
	it('orders same-album tracks by track number without wrapping', () => {
		const songs = [
			song({ ...navigableSongDefaults(), slug: 's1' }),
			song({ ...navigableSongDefaults(), slug: 's2', id: 's2', track_number: 2 }),
			song({ ...navigableSongDefaults(), slug: 's3', id: 's3', track_number: 3 })
		];
		expect(albumTrackNeighbors('s2', songs)).toEqual({ previous: songs[0], next: songs[2] });
		expect(albumTrackNeighbors('s1', songs)).toEqual({ previous: null, next: songs[1] });
		expect(albumTrackNeighbors('s3', songs)).toEqual({ previous: songs[1], next: null });
	});
});
