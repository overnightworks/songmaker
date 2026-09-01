import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { openCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { albumList } from '$lib/stores/libraryData';

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
		expect(scrolledToggles[0]?.textContent).toContain('Library');
		expect(scrolledToggles[1]?.textContent).toContain('Playlists');
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
});
