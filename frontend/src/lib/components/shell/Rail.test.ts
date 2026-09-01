import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { openCollection, setOpenCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { albumList } from '$lib/stores/libraryData';
import { playlistList, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';

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
vi.mock('$lib/api/client', () => ({
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false }),
	fetchAlbum: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
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
	localStorage.clear();
	resetLibraryContextForTests();
	albumList.set([]);
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetLibraryContextForTests();
	resetPlaylists();
});

describe('Rail', () => {
	it('renders the brand, the LIBRARY and PLAYLISTS groups, the settings disclosure, and the user row', async () => {
		albumList.set([
			{
				id: 'a1',
				title: 'A',
				artist: '',
				subtitle: '',
				year: '',
				colors: {},
				song_count: 0,
				picked_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00',
				is_archived: false
			}
		]);
		const target = await render();
		expect(requireElement(target, '.brand').textContent).toBe('Hallucinai');
		// Scoped to the top-level group toggles: a nested album row is also a
		// `button.disclose` (RailLibraryGroup's per-album disclosure), so an
		// unscoped query would pick it up between Library, Playlists, and
		// Settings.
		const groupRows = target.querySelectorAll<HTMLElement>('.rail-group > .disclose-row');
		expect(groupRows[0]?.textContent).toContain('Library');
		expect(groupRows[0]?.querySelector('.meta')?.textContent).toBe('1');
		expect(groupRows[1]?.textContent).toContain('Playlists');
		expect(groupRows[2]?.textContent).toContain('Settings');
		expect(target.textContent).toContain('felix');
	});

	it('acts as the Library link when the brand wordmark is clicked, keeping the open collection', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		const target = await render();
		const brand = requireElement<HTMLButtonElement>(target, '.brand');
		// Named after what it is (the wordmark), not what it does -- GitHub's own
		// logo pattern -- so it never collides with the LIBRARY group's own
		// "Library" name in an accessible-name lookup (both live in the same
		// mobile drawer).
		expect(brand.hasAttribute('aria-label')).toBe(false);
		expect(brand.textContent).toBe('Hallucinai');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('browse');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('scrolls the LIBRARY and PLAYLISTS groups, pinning Settings and the user row below them', async () => {
		const target = await render();
		const scroll = requireElement(target, '.rail-scroll');
		const scrolledToggles = scroll.querySelectorAll(
			'.rail-group > .disclose-row > button.disclose'
		);
		expect(scrolledToggles).toHaveLength(2);
		const scrolledTitles = scroll.querySelectorAll(
			'.rail-group > .disclose-row > button.group-title'
		);
		expect(scrolledTitles[0]?.textContent?.trim()).toBe('Library');
		expect(scrolledTitles[1]?.textContent?.trim()).toBe('Playlists');
		expect(scroll.textContent).not.toContain('Settings');

		const settingsPin = requireElement(target, '.rail-settings-pin');
		const settingsToggle = settingsPin.querySelector(
			'.rail-group > .disclose-row > button.disclose'
		);
		expect(settingsToggle?.textContent).toContain('Settings');

		const bottom = requireElement(target, '.rail-bottom');
		expect(bottom.textContent).toContain('felix');
		expect(target.querySelector('.rail-scroll ~ .rail-settings-pin ~ .rail-bottom')).not.toBeNull();
	});

	it('does not collapse an open playlist when an album row is expanded by its own chevron -- Library and Playlists do not share a slot', async () => {
		albumList.set([
			{
				id: 'a1',
				title: 'Nachtstrom',
				artist: '',
				subtitle: '',
				year: '',
				colors: {},
				song_count: 0,
				picked_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00',
				is_archived: false
			}
		]);
		playlistList.set([
			{
				id: 'p1',
				title: 'Night Drive',
				slug: 'night-drive',
				entry_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00'
			}
		]);
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00',
			entries: []
		});
		const target = await render();
		const playlistPanel = requireElement<HTMLDivElement>(target, '.playlist-songs');
		expect(playlistPanel.getAttribute('data-open')).toBe('true');

		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		albumToggle.click();
		await tick();

		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');
		expect(playlistPanel.getAttribute('data-open')).toBe('true');
	});

	it('marks the open album and the open playlist with the same row-active highlight', async () => {
		albumList.set([
			{
				id: 'a1',
				title: 'Nachtstrom',
				artist: '',
				subtitle: '',
				year: '',
				colors: {},
				song_count: 0,
				picked_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00',
				is_archived: false
			},
			{
				id: 'a2',
				title: 'Sonnwendfeuer',
				artist: '',
				subtitle: '',
				year: '',
				colors: {},
				song_count: 0,
				picked_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00',
				is_archived: false
			}
		]);
		playlistList.set([
			{
				id: 'p1',
				title: 'Night Drive',
				slug: 'night-drive',
				entry_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00'
			},
			{
				id: 'p2',
				title: 'Morning Run',
				slug: 'morning-run',
				entry_count: 0,
				is_shared: false,
				share_slug: null,
				created_at: '2026-01-01T00:00:00+00:00'
			}
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		selectedPlaylistDetail.set(null);
		const target = await render();

		const albumLabels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		const playlistLabels = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		expect(albumLabels).toHaveLength(2);
		expect(playlistLabels).toHaveLength(2);

		// The open album is marked, its sibling is not -- no third state, same
		// as the open playlist below.
		expect(albumLabels[0]?.classList.contains('row-active')).toBe(true);
		expect(albumLabels[1]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[1]?.classList.contains('row-active')).toBe(false);

		setOpenCollection({ kind: 'playlist', id: 'p2' });
		await tick();

		expect(albumLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(albumLabels[1]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[0]?.classList.contains('row-active')).toBe(false);
		expect(playlistLabels[1]?.classList.contains('row-active')).toBe(true);
	});
});
