import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { openCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { libraryBrowse } from '$lib/stores/librarySearch';
import { albumList, songList } from '$lib/stores/player';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '$lib/stores/playlists';
import { RAIL_SUMMARY_LOADING } from '$lib/constants';

function readyLibraryBrowseState() {
	return {
		status: 'ready' as const,
		error: null,
		albumHasMore: false,
		songHasMore: false,
		albumOffset: 0,
		songOffset: 0
	};
}

vi.mock('$app/navigation', () => ({
	goto: vi.fn().mockResolvedValue(undefined),
	afterNavigate: vi.fn()
}));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
const fetchPlaylists = vi.fn().mockResolvedValue([]);
vi.mock('$lib/api/client', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: vi.fn()
}));

import Rail from './Rail.svelte';

let mounted: ReturnType<typeof mount> | undefined;
const onlogout = vi.fn();

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Rail, { target, props: { username: 'felix', onlogout } });
	await tick();
	return target;
}

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	resetLibraryContextForTests();
	resetPlaylistsForTests();
	albumList.set([]);
	songList.set([]);
	playlistList.set([]);
	// Most tests below aren't about the initial-load flash — seed both lists
	// as already settled so the summary renders immediately, like a real
	// session past its first mount.
	libraryBrowse.set(readyLibraryBrowseState());
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetLibraryContextForTests();
	resetPlaylistsForTests();
});

describe('Rail', () => {
	it('renders the brand, library summary, settings link, and user row', async () => {
		albumList.set([
			{
				id: 'a1',
				title: 'A',
				artist: '',
				subtitle: '',
				year: '',
				colors: {},
				song_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00'
			}
		]);
		playlistLoad.set({ status: 'ready', error: null });
		const target = await render();
		expect(requireElement(target, '.brand').textContent).toBe('Hallucinai');
		expect(target.textContent).toContain('1 album');
		expect(requireElement<HTMLAnchorElement>(target, 'a[href="/settings"]')).toBeTruthy();
		expect(target.textContent).toContain('felix');
	});

	it('opens the wall and keeps the open collection when Library is clicked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		const before = history.state?.index ?? 0;
		const target = await render();
		requireElement<HTMLButtonElement>(target, '.library-link').click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('browse');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(history.state.index).toBeGreaterThan(before);
	});

	it('loads the playlist count on mount instead of showing 0 until the Playlists chip is visited', async () => {
		fetchPlaylists.mockResolvedValue([
			{
				id: 'p1',
				title: 'Night Drive',
				entry_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00'
			}
		]);
		const target = await render();
		await vi.waitFor(() => expect(get(playlistLoad).status).toBe('ready'));
		await tick();
		expect(target.textContent).toContain('1 playlist');
	});

	it('acts as the Library link when the brand wordmark is clicked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		const target = await render();
		const brand = requireElement<HTMLButtonElement>(target, '.brand');
		expect(brand.getAttribute('aria-label')).toBe('Library');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('browse');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('shows a loading placeholder instead of 0 albums · 0 playlists before either list has settled', async () => {
		libraryBrowse.set({ ...readyLibraryBrowseState(), status: 'idle' });
		albumList.set([]);
		playlistList.set([]);
		const target = await render();
		expect(target.textContent).toContain(RAIL_SUMMARY_LOADING);
		expect(target.textContent).not.toContain('0 album');

		fetchPlaylists.mockResolvedValue([]);
		libraryBrowse.set(readyLibraryBrowseState());
		await vi.waitFor(() => expect(get(playlistLoad).status).toBe('ready'));
		await tick();
		expect(target.textContent).toContain('0 albums');
		expect(target.textContent).toContain('0 playlists');
	});
});
