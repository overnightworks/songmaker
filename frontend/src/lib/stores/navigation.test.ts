import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';

import { searchQuery } from '$lib/stores/filter';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import {
	captureLibraryScroll,
	detailTab,
	isLibraryHistoryState,
	libraryScrollAnchor,
	librarySurface,
	resetLibraryContextForTests
} from '$lib/stores/libraryContext';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList, updateSongInList } from '$lib/stores/libraryData';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { resetPlaylists, selectedPlaylistId, updatePlaylistInList } from '$lib/stores/playlists';
import { generationFailures } from '$lib/stores/jobs';
import { sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import { ApiError } from '$lib/api/fetch';
import { SONG_LINK_NOT_FOUND_TOAST } from '$lib/constants';
import type { GenerationItem, PlaylistItem, SongItem } from '$lib/api/types';

const fetchSong = vi.fn();
const fetchAlbum = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLastFailedGeneration = vi.fn();

// goto actually changes the URL (via the History API, like the real
// SvelteKit goto) so tests can assert the landed-on route, not just that
// goto was called with some argument (see issue #264's done-when).
vi.mock('$app/navigation', () => ({
	goto: vi.fn((url: string, options?: { replaceState?: boolean }) => {
		if (options?.replaceState) history.replaceState(null, '', url);
		else history.pushState(null, '', url);
		return Promise.resolve();
	})
}));
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
vi.mock('$lib/api/client', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => fetchLastFailedGeneration(...args),
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
	goBack,
	initNavigation,
	isLibraryWorkspacePath,
	loadSongContext,
	openAlbum,
	openCollectionEntry,
	openLibraryCreate,
	openLibraryWall,
	openPlaylist,
	openRailSearchTarget,
	pendingDirtyNavigation,
	persistLibraryHistory,
	resetNavigationForTests,
	revealPlayingSong,
	revealSharedTake,
	selectNeighborSong,
	selectSong
} from './navigation';
import { discardDraft, editLyrics, loadSongData, setDraftLyrics } from '$lib/stores/editor';
import { updateSong } from '$lib/api/client';
import { libraryRootState } from '$lib/stores/libraryContext';
import { toasts } from '$lib/stores/toast';

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
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
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
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [generation()],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function playlistItem(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

beforeEach(() => {
	fetchSong.mockReset();
	fetchAlbum.mockReset();
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchLastFailedGeneration.mockReset();
	fetchLastFailedGeneration.mockResolvedValue({ job: null });
	generationFailures.set({});
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
	searchQuery.set('');
	albumList.set([album('a1', 'Nachtstrom'), album('a2', 'Other')]);
	songList.set([song()]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	// Must run after selectedSongId is cleared: the album/song-list reset
	// above briefly recomputes `selectedSong` against the previous test's
	// stale selectedSongId and re-derives openCollection through the
	// selectedSong subscription in navigation.ts before this line clears it.
	resetCollectionForTests();
	history.replaceState(null, '', '/');
	vi.mocked(goto).mockClear();
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	resetCollectionForTests();
});

function album(id: string, title: string) {
	return {
		id,
		title,
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false
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
		history.replaceState(null, '', '/album/a1');
		await selectSong('s1');
		expect(vi.mocked(goto).mock.calls.map((call) => call[0])).toEqual(['/album/a1/s1']);
	});
});

// A history write that changes the route pattern (/ <-> /album/<slug>) must
// reach SvelteKit's router, not just the address bar: a raw write leaves the
// router mounting the route it last saw, and the next Back/Forward or real
// navigation that disagrees tears the workspace down mid-session. The
// interaction with the router is the contract here, so it is asserted directly.
describe('history writes across the route boundary (issue #269)', () => {
	it('opens an album address through the router', async () => {
		await openAlbum('a1');
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
		expect(window.location.pathname).toBe('/album/a1');
		expect(history.state.collection).toEqual({ kind: 'album', id: 'a1' });
	});

	it('leaves an album address through the router', async () => {
		await openAlbum('a1');
		vi.mocked(goto).mockClear();
		await openLibraryWall();
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
		expect(window.location.pathname).toBe('/');
		expect(history.state.surface).toBe('browse');
	});

	it('writes the mixed library scroll position inside one route straight to history', async () => {
		await selectSong('s1');
		vi.mocked(goto).mockClear();

		captureLibraryScroll(240);
		persistLibraryHistory();

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(history.state.scrollAnchor).toBe(240);
		expect(history.state).not.toHaveProperty('filter');
	});

	it('keeps a second write behind the crossing one it follows', async () => {
		history.replaceState(null, '', '/album/a1');
		songList.set([song({ id: 's1', album_id: 'a1', generations: [generation()] })]);

		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		selectedGenerationId.set('g1');
		persistLibraryHistory();

		// Pinning the take crosses a second time (issue #281: the take is its
		// own route file too), queued behind the song's own crossing write.
		await vi.waitFor(() => expect(history.state.generationId).toBe('g1'));
		expect(window.location.pathname + window.location.search).toBe('/album/a1/s1/take/1');
	});

	// Issue #275: an album address becomes a song address one segment deeper
	// (/album/x -> /album/x/y), which is a route-file boundary too -- the
	// naive isAlbumRoutePath boolean stays true on both sides of it, so the
	// crossing check must tell the two shapes apart, not just "under /album/".
	it('crosses through the router from an album address to a song inside it', async () => {
		await openAlbum('a1');
		vi.mocked(goto).mockClear();

		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));

		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1/s1', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
		expect(window.location.pathname).toBe('/album/a1/s1');
	});

	// Moving between two songs of the same open album stays the same route
	// file (/album/[slug]/[song]/+page.svelte matches both), so it is the
	// frequent-churn case, not a crossing.
	it('writes a song-to-song move inside the same album straight to history', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		await openAlbum('a1');
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		vi.mocked(goto).mockClear();

		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a1/s2');
	});

	// #275-review bycatch, pinned here as issue #281 promised: a song-to-song
	// move across album boundaries is still the same route file
	// (/album/[slug]/[song]/+page.svelte matches both, whichever album the
	// slug names), so it stays the frequent-churn raw write too -- only the
	// route.id shape decides a crossing, never which resource it names.
	it('writes a song-to-song move across album boundaries straight to history too', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a2' })]);
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		vi.mocked(goto).mockClear();

		await selectSong('s2', song({ id: 's2', album_id: 'a2' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a2/s2');
	});

	// Issue #281: a take address is one segment deeper than its song's own
	// (/album/x/y -> /album/x/y/take/n), a route-file boundary again -- the
	// same isSongRoutePath boolean stays true on both sides, so this crossing
	// check must tell song and take apart too, not just album and song.
	it('crosses through the router from a song address to one of its takes', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' })]);
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		vi.mocked(goto).mockClear();

		selectedGenerationId.set('g1');
		persistLibraryHistory();

		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/s1/take/1'));
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/album/a1/s1/take/1', {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	});

	// Moving between two takes of the same open song stays the same route
	// file (/take/[n] matches both, whichever number it names), so it is the
	// frequent-churn case, not a crossing -- the same rule the album<->song
	// and song<->song cases above already carry one segment shallower.
	it('writes a take-to-take move inside the same song straight to history', async () => {
		songList.set([
			song({
				id: 's1',
				album_id: 'a1',
				generations: [
					generation({ id: 'g1', generation_number: 1 }),
					generation({ id: 'g2', generation_number: 2 })
				]
			})
		]);
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
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
		fetchPlaylists.mockResolvedValueOnce([playlistItem()]);

		await openPlaylist('p1');

		expect(vi.mocked(goto)).toHaveBeenCalledWith('/playlist/night-drive', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
		expect(window.location.pathname).toBe('/playlist/night-drive');
	});

	// Moving between two open playlists stays the same route file
	// (/playlist/[slug] matches both), so it is the frequent-churn case, not
	// a crossing -- the same rule album<->album and song<->song already
	// carry (Playlist<->Playlist is the one pair the crossing matrix does
	// not cross).
	it('writes a playlist-to-playlist move straight to history, not through the router', async () => {
		fetchPlaylists.mockResolvedValue([
			playlistItem({ id: 'p1', slug: 'night-drive' }),
			playlistItem({ id: 'p2', slug: 'morning-run', title: 'Morning Run' })
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
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
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
		fetchPlaylists.mockResolvedValueOnce([playlistItem()]);
		await openPlaylist('p1');
		expect(window.location.pathname).toBe('/playlist/night-drive');
	});

	it('gives the wall back the home address when the playlist is only the rail context', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem()]);
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
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		const indexBeforeRename = history.state.index;
		vi.mocked(goto).mockClear();

		updateSongInList('s1', (s) => ({ ...s, slug: 'renamed' }));

		await vi.waitFor(() => expect(window.location.pathname).toBe('/album/a1/renamed'));
		expect(history.state.index).toBe(indexBeforeRename);
	});

	it('leaves the address alone for an edit that is not a rename', async () => {
		await openAlbum('a1');
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		vi.mocked(goto).mockClear();

		updateSongInList('s1', (s) => ({ ...s, lyrics: 'a new verse' }));

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(window.location.pathname).toBe('/album/a1/s1');
	});

	it("leaves a legacy ?song= address alone -- redirecting it onto its canonical address is (library)/+page.svelte's job (issue #284), not this rename-follow", async () => {
		history.replaceState(null, '', '/?song=s1');
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
		fetchPlaylists.mockResolvedValueOnce([playlistItem()]);
		await openPlaylist('p1');
		const indexBeforeRename = history.state.index;
		vi.mocked(goto).mockClear();

		updatePlaylistInList('p1', (p) => ({ ...p, slug: 'renamed' }));

		await vi.waitFor(() => expect(window.location.pathname).toBe('/playlist/renamed'));
		expect(history.state.index).toBe(indexBeforeRename);
	});

	it('leaves the address alone for an edit that is not a rename', async () => {
		fetchPlaylists.mockResolvedValueOnce([playlistItem()]);
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
		expect(history.state).toMatchObject({ surface: 'browse', scrollAnchor: 240 });
		expect(history.state).not.toHaveProperty('filter');
	});

	it('opens an album collection and pushes one history entry', async () => {
		const before = history.state?.index ?? 0;
		await openAlbum('a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(librarySurface)).toBe('detail');
		expect(history.state.index).toBe(before + 1);
	});

	it('opens a playlist collection and pushes one history entry', async () => {
		const before = history.state?.index ?? 0;
		await openPlaylist('p1');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistId)).toBe('p1');
		expect(history.state.index).toBe(before + 1);
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
		history.replaceState(null, '', '/settings/voices');
		await openAlbum('a1');
		expect(window.location.pathname).toBe('/album/a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(librarySurface)).toBe('detail');
	});

	it('openPlaylist lands on the library route with the playlist open', async () => {
		history.replaceState(null, '', '/settings/voices');
		await openPlaylist('p1');
		expect(window.location.pathname).toBe('/');
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(librarySurface)).toBe('detail');
	});

	// The Rail keeps rendering the open album's tracks on every route (issue
	// #264's review found selectSong missing the same guard as openAlbum):
	// clicking a track from Settings must land on the library route too.
	it('selectSong lands on the song address with the song selected', async () => {
		history.replaceState(null, '', '/settings/voices');
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
	it('openLibraryWall leaves settings for the wall through the router, not a raw history write', async () => {
		history.replaceState(null, '', '/settings/voices');
		await openLibraryWall();
		expect(window.location.pathname).toBe('/');
		expect(get(librarySurface)).toBe('browse');
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/', {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
	});
});

describe.each([
	['openAlbum', () => openAlbum('a1')],
	['openPlaylist', () => openPlaylist('p1')],
	['openLibraryWall', () => openLibraryWall()],
	['openLibraryCreate', () => openLibraryCreate()]
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
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('switches the collection when a playlist was open (song open beats playlist context)', async () => {
		await openPlaylist('p1');
		expect(get(openCollection)?.kind).toBe('playlist');
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(selectedPlaylistId)).toBeNull();
	});

	it('leaves the collection untouched when it already matches the song album', async () => {
		await openAlbum('a1');
		const stateBefore = get(openCollection);
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toBe(stateBefore);
	});

	it('opens the editor on Write, the only tab a compact layout starts on', async () => {
		// #141/13: Takes was the landing tab, which hid the editor behind a tab
		// switch on every phone-width open.
		detailTab.set('takes');
		await selectSong('s1');
		expect(get(detailTab)).toBe('write');
	});

	it('pushes a new history entry per selectSong call', async () => {
		const before = history.state?.index ?? 0;
		await selectSong('s1');
		expect(history.state.index).toBe(before + 1);
	});

	it('pushes a new history entry when opening the first song from the album interior', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		await openAlbum('a1');
		const afterOpen = history.state.index;
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(history.state.index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s1');
	});

	it('replaces the current history entry when moving to another song already inside the open collection', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		await openAlbum('a1');
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		const afterFirstSong = history.state.index;
		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(afterFirstSong);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('pushes a new history entry when the song is outside the open collection', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a2' })]);
		await openAlbum('a1');
		const afterOpen = history.state.index;
		await selectSong('s2', song({ id: 's2', album_id: 'a2' }));
		expect(history.state.index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('lands back on the album, not the wall, after opening two tracks in a row (issue #99)', async () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		const wallIndex = history.state?.index ?? 0;
		await openAlbum('a1');
		const albumIndex = history.state.index;
		expect(albumIndex).toBe(wallIndex + 1);
		await selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		const track1Index = history.state.index;
		expect(track1Index).toBe(albumIndex + 1);
		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(track1Index);
	});
});

describe('opening a song recovers its failure banner', () => {
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

describe('loadSongContext (dead song link, issue #237)', () => {
	it('clears the selection and shows a not-found toast for a dead song, without throwing', async () => {
		selectedSongId.set('dead');
		fetchSong.mockRejectedValue(new ApiError(404, 'Song not found', '/api/songs/dead'));

		await expect(loadSongContext('dead')).resolves.toBeUndefined();

		expect(get(selectedSongId)).toBeNull();
		expect(
			get(toasts).some((t) => t.type === 'error' && t.message === SONG_LINK_NOT_FOUND_TOAST)
		).toBe(true);
	});

	it('propagates a non-404 error instead of swallowing it', async () => {
		selectedSongId.set('s-broken');
		fetchSong.mockRejectedValue(new ApiError(500, 'Boom', '/api/songs/s-broken'));

		await expect(loadSongContext('s-broken')).rejects.toThrow('Boom');

		expect(get(selectedSongId)).toBe('s-broken');
		expect(get(toasts)).toHaveLength(0);
	});

	it('leaves a valid song selection untouched', async () => {
		selectedSongId.set('s2');
		fetchSong.mockResolvedValue(song({ id: 's2', album_id: 'a1' }));

		await expect(loadSongContext('s2')).resolves.toBeUndefined();

		expect(get(selectedSongId)).toBe('s2');
		expect(get(toasts)).toHaveLength(0);
	});

	it('keeps a newer song selection when an earlier dead-link lookup finishes late', async () => {
		let rejectLookup: ((reason: Error) => void) | undefined;
		songList.set([
			song({
				id: 's1',
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

		const loadingDeadLink = loadSongContext('s1');
		await vi.waitFor(() => expect(fetchSong).toHaveBeenCalledWith('s1'));
		selectedSongId.set('s2');
		rejectLookup!(new ApiError(404, 'Song not found', '/api/songs/s1'));
		await expect(loadingDeadLink).resolves.toBeUndefined();

		expect(get(selectedSongId)).toBe('s2');
		expect(get(toasts)).toHaveLength(0);
	});
});

describe('selectNeighborSong', () => {
	it('replaces the current history entry instead of pushing', async () => {
		await selectSong('s1');
		const afterFirst = history.state.index;
		await selectNeighborSong(song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(afterFirst);
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
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('runs the deferred switch on Discard', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		songList.set([song({ id: 's1' }), song({ id: 's2', album_id: 'a1' })]);

		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		discardDraft();
		await get(pendingDirtyNavigation)?.();
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s2');
	});

	it('stays put on Cancel', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('defers backToCollection and openLibraryWall the same way', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
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
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await selectNeighborSong(song({ id: 's2', album_id: 'a1' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('defers revealPlayingSong the same way', async () => {
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await revealPlayingSong(song({ id: 's2', album_id: 'a1' }), 'g2');

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
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		history.replaceState(null, '', '/settings/voices');
		vi.mocked(goto).mockClear();

		await revealPlayingSong(song({ id: 's2', album_id: 'a1' }), 'g2');

		expect(window.location.pathname).toBe('/settings/voices');
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	// Issue #265 review of #264: onOpenShare's shared-take branch used to
	// await selectSong and then set selectedGenerationId as a follow-up step
	// -- guardDirtyNavigation resolves that promise the instant it parks a
	// dirty draft, so the pin ran against the still-open old song a microtask
	// later. revealSharedTake folds both into one guarded action instead.
	it('defers revealSharedTake the same way, without pinning the take against the old song', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await revealSharedTake('s2', 'g2');

		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('never prompts when the draft is clean', async () => {
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));

		await selectSong('s2', song({ id: 's2', album_id: 'a1' }));

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
		const backSpy = vi.spyOn(history, 'back').mockImplementation(() => undefined);
		goBack();
		expect(backSpy).toHaveBeenCalledTimes(1);
		backSpy.mockRestore();
	});

	it('returns to the wall and clears selection when there is no predecessor', async () => {
		await selectSong('s1');
		history.replaceState(null, '', '/');
		goBack();
		expect(get(librarySurface)).toBe('browse');
		expect(get(selectedSongId)).toBeNull();
	});

	it('leaves the create surface for the wall when there is no predecessor', () => {
		librarySurface.set('create');
		goBack();
		expect(get(librarySurface)).toBe('browse');
	});

	it('keeps the create surface while the browser returns to its predecessor', () => {
		history.replaceState({ ...libraryRootState(), index: 1, surface: 'create' }, '', '/');
		librarySurface.set('create');
		const backSpy = vi.spyOn(history, 'back').mockImplementation(() => undefined);

		goBack();

		expect(backSpy).toHaveBeenCalledTimes(1);
		expect(get(librarySurface)).toBe('create');
		backSpy.mockRestore();
	});
});

describe('revealPlayingSong', () => {
	it('opens the song at its own address, then crosses again to the take', async () => {
		history.replaceState(null, '', '/');
		await revealPlayingSong(song({ id: 's1' }), 'g1');
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
		history.replaceState(null, '', '/settings');
		await revealPlayingSong(song({ id: 's1' }), 'g1');
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
	it('auto-saves a dirty draft before applying a browser-back navigation', async () => {
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		vi.mocked(updateSong).mockResolvedValue(song({ id: 's1', lyrics: 'unsaved edit' }));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(updateSong).toHaveBeenCalledWith(
			's1',
			expect.objectContaining({ lyrics: 'unsaved edit' })
		);
		cleanup();
	});

	it('saves a dirty draft once when two popstates fire before the first save settles', async () => {
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		let resolveSave: (value: SongItem) => void = () => undefined;
		vi.mocked(updateSong).mockReturnValue(
			new Promise((resolve) => {
				resolveSave = resolve;
			})
		);

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(updateSong).toHaveBeenCalledTimes(1));
		expect(get(selectedSongId)).toBe('s1');
		resolveSave(song({ id: 's1', lyrics: 'unsaved edit' }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(updateSong).toHaveBeenCalledTimes(1);
		cleanup();
	});

	it('still applies the browser-back navigation when the auto-save fails', async () => {
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		vi.mocked(updateSong).mockRejectedValue(new Error('Network error'));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(get(toasts).some((t) => t.type === 'error')).toBe(true);
		cleanup();
	});

	it('does not attempt a save on browser-back when the draft is clean', async () => {
		history.replaceState(null, '', '/');
		await openAlbum('a1');
		await selectSong('s1');
		loadSongData(song({ id: 's1' }));

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
		history.replaceState(null, '', '/album/ghost');

		const cleanup = initNavigation();

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(history.state).toBeNull();
		cleanup();
	});

	it('still seeds a default root entry on a genuinely cold "/" visit', async () => {
		history.replaceState(null, '', '/');

		const cleanup = initNavigation();

		await vi.waitFor(() => expect(isLibraryHistoryState(history.state)).toBe(true));
		cleanup();
	});
});

describe('openRailSearchTarget', () => {
	it('uses the Library action for the Library page target', async () => {
		history.replaceState(null, '', '/');
		selectedSongId.set('s1');
		librarySurface.set('detail');
		toggleSidebar();

		await openRailSearchTarget({ kind: 'page', href: '/' });

		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
		expect(get(sidebarOpen)).toBe(false);
	});

	it('opens one page target and closes the rail drawer', async () => {
		history.replaceState(null, '', '/');
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
			song({ id: 's1', track_number: 1 }),
			song({ id: 's2', track_number: 2 }),
			song({ id: 's3', track_number: 3 })
		];
		expect(albumTrackNeighbors('s2', songs)).toEqual({ previous: songs[0], next: songs[2] });
		expect(albumTrackNeighbors('s1', songs)).toEqual({ previous: null, next: songs[1] });
		expect(albumTrackNeighbors('s3', songs)).toEqual({ previous: songs[1], next: null });
	});
});
