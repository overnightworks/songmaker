import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem, ShareInventoryItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_ALBUMS_EMPTY,
	LIBRARY_PLAYLISTS_EMPTY,
	LIBRARY_SHARES_OPEN_LABEL,
	LIBRARY_SHARES_UNSHARE_LABEL,
	collectionRowPlayLabel
} from '$lib/constants';
import { discardDraft, loadSongData, setDraftLyrics } from '$lib/stores/editor';
import { libraryFilter, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { pendingDirtyNavigation } from '$lib/stores/navigation';
import { openCollection } from '$lib/stores/collection';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { albumList, songList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';
import { resetShares } from '$lib/stores/shares';

const fetchPlaylists = vi.fn();
const fetchShares = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const unshareAlbum = vi.fn();
const unarchiveAlbum = vi.fn();

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
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
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	// Exercised by loadSongContext's hydrateGenerationFailure fire-and-forget
	// call whenever a test drives a real selectSong through this component.
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null }),
	// Exercised by stores/editor.ts's loadSongData -- the dirty-draft test
	// below drives that directly to arrange a dirty draft on the open song.
	fetchVersions: vi.fn().mockResolvedValue([]),
	createPlaylist: vi.fn().mockResolvedValue({
		id: 'new-playlist',
		title: 'Playlist',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00'
	}),
	unshareAlbum: (...args: unknown[]) => unshareAlbum(...args),
	unarchiveAlbum: (...args: unknown[]) => unarchiveAlbum(...args),
	unshareSong: vi.fn(),
	unsharePlaylist: vi.fn(),
	unshareGeneration: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import LibraryWall from './LibraryWall.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Local Album',
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

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p-local',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function shareItem(overrides: Partial<ShareInventoryItem> = {}): ShareInventoryItem {
	return {
		type: 'album',
		id: 'a-local',
		title: 'Local Album',
		public_path: '/share/abc',
		is_archived: false,
		...overrides
	} as ShareInventoryItem;
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's-tide',
		slug: 'tide',
		title: 'Tide',
		album_id: 'a-local',
		album_title: 'Local Album',
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

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchShares
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
	fetchAlbum.mockReset();
	fetchAlbums
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
	fetchSong.mockReset();
	fetchSongs
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false });
	unshareAlbum.mockReset().mockResolvedValue(undefined);
	unarchiveAlbum.mockReset();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetShares();
	resetPlaylists();
	albumList.set([album()]);
	songList.set([]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	discardDraft();
	pendingDirtyNavigation.set(null);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetShares();
	resetPlaylists();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target, props: { oncreate: vi.fn() } }));
	await tick();
	return target;
}

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

describe('LibraryWall filter chips', () => {
	it('is single-select and switches with arrow keys', async () => {
		const root = await render();
		const albumsChip = requireElement<HTMLButtonElement>(root, '#library-filter-albums');
		const playlistsChip = requireElement<HTMLButtonElement>(root, '#library-filter-playlists');
		expect(albumsChip.getAttribute('aria-checked')).toBe('true');
		expect(playlistsChip.getAttribute('aria-checked')).toBe('false');

		albumsChip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		await tick();
		expect(get(libraryFilter)).toBe('playlists');
	});

	it('shows the playlists wall when the Playlists chip is picked', async () => {
		playlistList.set([playlist()]);
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.textContent).toContain('Night Drive');
		expect(root.querySelector('.search')).toBeNull();
	});

	it('shows an empty state for a filter with nothing in it', async () => {
		albumList.set([]);
		const root = await render();
		expect(root.textContent).toContain(LIBRARY_ALBUMS_EMPTY);
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.textContent).toContain(LIBRARY_PLAYLISTS_EMPTY);
	});
});

describe('LibraryWall selection', () => {
	it('opens an album collection when its tile is clicked', async () => {
		const root = await render();
		const tile = requireElement<HTMLButtonElement>(root, '.wall-tile-body');
		tile.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-local' });
	});

	it("shows the album's own song and pick counts, not a recount of the loaded songs", async () => {
		// The tile must not recount picks from songList: only the songs already
		// loaded are there, which is why every tile read "0 picks" (#141/2).
		songList.set([song({ id: 's1', album_id: 'a-local', generations: [] })]);
		albumList.set([album({ song_count: 2, picked_count: 1 })]);
		const root = await render();
		expect(root.querySelector('.tile-subtitle')?.textContent).toBe('2 songs · 1 pick');
	});

	it('plays the album from the tile play control without opening it', async () => {
		const root = await render();
		const play = requireElement<HTMLButtonElement>(root, '.wall-tile-play');
		play.click();
		await tick();
		expect(get(openCollection)).toBeNull();
	});

	it('names every wall play control after the collection it starts', async () => {
		playlistList.set([playlist()]);
		const root = await render();
		expect(requireElement(root, '.wall-tile-play').getAttribute('aria-label')).toBe(
			collectionRowPlayLabel('Local Album')
		);

		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();

		expect(requireElement(root, '.wall-tile-play').getAttribute('aria-label')).toBe(
			collectionRowPlayLabel('Night Drive')
		);
	});
});

describe('LibraryWall archived filter', () => {
	it('loads and shows archived albums only after the Archived toggle is picked', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album({ id: 'a-archived', title: 'Archived Album', is_archived: true })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		expect(root.textContent).not.toContain('Archived Album');

		requireElement<HTMLButtonElement>(root, 'button[aria-pressed]').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(fetchAlbums).toHaveBeenCalledWith(0, expect.any(Number), { archived: true });
		expect(root.textContent).toContain('Archived Album');
		expect(root.textContent).not.toContain('Local Album');
	});

	it('unarchives a tile, moving it out of the archived list and back into the library', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album({ id: 'a-archived', title: 'Archived Album', is_archived: true })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		unarchiveAlbum.mockResolvedValue(
			album({ id: 'a-archived', title: 'Archived Album', is_archived: false })
		);
		const root = await render();
		requireElement<HTMLButtonElement>(root, 'button[aria-pressed]').click();
		await tick();
		await Promise.resolve();
		await tick();

		requireElement<HTMLButtonElement>(root, '.wall-tile-unarchive').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(unarchiveAlbum).toHaveBeenCalledWith('a-archived');
		expect(root.textContent).not.toContain('Archived Album');
		expect(get(albumList).some((a) => a.id === 'a-archived')).toBe(true);
	});
});

describe('LibraryWall sort', () => {
	it('persists the sort choice to history', async () => {
		const root = await render();
		const before = history.state?.index ?? 0;
		const select = requireElement<HTMLSelectElement>(root, '.sort-select');
		select.value = 'oldest';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		const state = history.state as { index: number; sort: string } | null;
		expect(state?.index).toBe(before);
		expect(state?.sort).toBe('oldest');
	});
});

describe('LibraryWall create actions', () => {
	it('creates and opens a new playlist', async () => {
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		requireElement<HTMLButtonElement>(root, '.new-btn[aria-label="New playlist"]').click();
		await tick();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'new-playlist' });
		expect(get(libraryFilter)).toBe('playlists');
	});

	it('calls oncreate for the album create action', async () => {
		const oncreate = vi.fn();
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(LibraryWall, { target, props: { oncreate } }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.new-btn[aria-label="New album"]').click();
		expect(oncreate).toHaveBeenCalledTimes(1);
	});

	it('shows only the create action for the active filter, never both at once', async () => {
		const root = await render();
		expect(root.querySelector('.new-btn[aria-label="New album"]')).not.toBeNull();
		expect(root.querySelector('.new-btn[aria-label="New playlist"]')).toBeNull();

		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.querySelector('.new-btn[aria-label="New album"]')).toBeNull();
		expect(root.querySelector('.new-btn[aria-label="New playlist"]')).not.toBeNull();

		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		expect(root.querySelector('.new-btn')).toBeNull();
	});
});

describe('LibraryWall shared filter', () => {
	it('opens a remote inventory album via fetchAlbum, then hydrateAndOpenAlbum', async () => {
		const remote = album({ id: 'a-remote', title: 'Remote Shared', is_shared: true });
		fetchAlbum.mockResolvedValue(remote);
		fetchShares.mockResolvedValue({
			items: [
				shareItem({
					id: 'a-remote',
					title: 'Remote Shared',
					public_path: '/share/remote'
				})
			],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();

		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_OPEN_LABEL} Remote Shared"]`
		).click();
		await Promise.resolve();
		await tick();

		expect(fetchAlbum).toHaveBeenCalledWith('a-remote');
		expect(get(albumList).some((item) => item.id === 'a-remote')).toBe(true);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-remote' });
	});

	// Regression coverage for issue #264's review: onOpenShare's generation
	// branch used to set selectedGenerationId right after firing selectSong
	// without awaiting it, so the still-pending song switch cleared the take
	// selection a microtask later (player.ts's selectSong resets it to null).
	// selectedSongId itself updates synchronously (well before the pin, which
	// waits on the song's own history write), so the wait below is on the pin
	// -- the later of the two -- rather than on the song id, or this could
	// pass on a song switch that never finishes pinning the take at all.
	it('opens a shared take with the song selected and that take pinned', async () => {
		songList.set([song({ id: 's-shared', title: 'Undertow', album_id: 'a-local' })]);
		fetchShares.mockResolvedValue({
			items: [
				shareItem({
					type: 'generation',
					id: 'g-shared',
					title: 'Undertow',
					song_id: 's-shared',
					generation_number: 3
				})
			],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();

		requireElement<HTMLButtonElement>(root, '.share-open').click();

		await vi.waitFor(() => expect(get(selectedGenerationId)).toBe('g-shared'));
		expect(get(selectedSongId)).toBe('s-shared');
	});

	// Regression coverage for issue #265's review of #264: a dirty draft on the
	// open song used to let the switch park while the take pin ran anyway
	// (selectSong's promise resolves the instant guardDirtyNavigation parks
	// it), so the pin landed on the still-open old song. revealSharedTake
	// folds the switch and the pin into one guarded action instead.
	it('parks a shared-take open behind a dirty draft, without pinning the take on the old song', async () => {
		songList.set([
			song({ id: 's-open', title: 'Open Song', album_id: 'a-local' }),
			song({ id: 's-shared', title: 'Undertow', album_id: 'a-local' })
		]);
		selectedSongId.set('s-open');
		loadSongData(song({ id: 's-open', title: 'Open Song', album_id: 'a-local' }));
		setDraftLyrics('unsaved edit');
		fetchShares.mockResolvedValue({
			items: [
				shareItem({
					type: 'generation',
					id: 'g-shared',
					title: 'Undertow',
					song_id: 's-shared',
					generation_number: 3
				})
			],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();

		requireElement<HTMLButtonElement>(root, '.share-open').click();
		await tick();

		expect(get(selectedSongId)).toBe('s-open');
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(pendingDirtyNavigation)).not.toBeNull();

		discardDraft();
		await get(pendingDirtyNavigation)?.();
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s-shared');
		expect(get(selectedGenerationId)).toBe('g-shared');
	});

	it('renders the share inventory with open and unshare actions', async () => {
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();
		expect(
			root.querySelector(`[aria-label="${LIBRARY_SHARES_OPEN_LABEL} Local Album"]`)
		).not.toBeNull();
		expect(root.querySelector(`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`)).not.toBeNull();
	});

	it('unshares on confirm: mutates the album, refreshes the inventory, and closes the dialog', async () => {
		albumList.set([album({ is_shared: true, share_slug: 'abc' })]);
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();
		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`
		).click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.confirm-btn').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(unshareAlbum).toHaveBeenCalledWith('a-local');
		expect(get(albumList).find((item) => item.id === 'a-local')?.is_shared).toBe(false);
		expect(document.body.querySelector('.confirm-btn')).toBeNull();
	});

	it('cancels without mutating the album when the dialog is dismissed', async () => {
		albumList.set([album({ is_shared: true, share_slug: 'abc' })]);
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();
		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`
		).click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.cancel-btn').click();
		await tick();

		expect(unshareAlbum).not.toHaveBeenCalled();
		expect(get(albumList).find((item) => item.id === 'a-local')?.is_shared).toBe(true);
	});
});

describe('LibraryWall toolbar consistency', () => {
	it('keeps search out of the wall for every filter', async () => {
		playlistList.set([playlist()]);
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();

		for (const id of ['albums', 'playlists', 'shared']) {
			requireElement<HTMLButtonElement>(root, `#library-filter-${id}`).click();
			await tick();
			await tick();
			expect(root.querySelector('.search'), `wall search for ${id}`).toBeNull();
		}
	});
});

describe('LibraryWall share count request storm (#139)', () => {
	it('does not refetch the share count on a fast remount', async () => {
		await render();
		expect(fetchShares).toHaveBeenCalledTimes(1);

		const first = mounted.pop();
		if (first) await unmount(first);

		await render();

		expect(fetchShares).toHaveBeenCalledTimes(1);
	});
});
