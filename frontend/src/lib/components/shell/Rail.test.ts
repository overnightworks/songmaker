import { makeSong } from '#lib/test-utils/factories.ts';
import { modifiedClicks } from '#lib/test-utils/modified-clicks.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { goto } from '$app/navigation';
import { openCollection, setOpenCollection } from '#lib/stores/collection.ts';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import { librarySurface, resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { albumList } from '#lib/stores/libraryData.ts';
import { railTreeQuery } from '#lib/stores/librarySearch.ts';
import { pendingDirtyNavigation } from '#lib/stores/navigation.ts';
import {
	playlistList,
	resetPlaylistsForTests,
	selectedPlaylistDetail
} from '#lib/stores/playlists.ts';
import { railCollapsed, railWidth, RAIL_MAX_WIDTH_PX, RAIL_MIN_WIDTH_PX } from '#lib/stores/ui.ts';
import {
	buildAlbum as album,
	buildPlaylist as playlist,
	buildPlaylistDetail as detail,
	createComponentMount,
	requireElement
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('#lib/api/library.ts', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('#lib/api/albums.ts', async () =>
	(await import('./rail-test-fixtures')).railAlbumsApiMock()
);
vi.mock('#lib/api/songs.ts', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
vi.mock('#lib/api/client.ts', async () =>
	(await import('./rail-test-fixtures')).railClientApiMock()
);

import Rail from './Rail.svelte';

const { render, cleanup } = createComponentMount(Rail);
let collapsedMounted: ReturnType<typeof mount> | undefined;

async function renderCollapsedRail(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	collapsedMounted = mount(Rail, {
		target,
		props: { collapsed: true }
	});
	await tick();
	return target;
}

function findButtonByText(root: ParentNode, text: string): HTMLButtonElement {
	const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((candidate) =>
		candidate.textContent?.includes(text)
	);
	if (!button) throw new Error(`Expected a button named ${text}`);
	return button;
}

function firePointer(
	target: EventTarget,
	type: 'pointerdown' | 'pointermove' | 'pointerup',
	clientY: number,
	timeStamp: number
): void {
	const event = new PointerEvent(type, {
		pointerId: 1,
		pointerType: 'mouse',
		button: 0,
		bubbles: true,
		cancelable: true,
		clientY
	});
	Object.defineProperty(event, 'timeStamp', { value: timeStamp, configurable: true });
	target.dispatchEvent(event);
}

function fireClick(target: EventTarget): void {
	target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
}

function fireRailResizePointer(
	target: EventTarget,
	type: 'pointerdown' | 'pointermove' | 'pointerup',
	clientX: number
): void {
	target.dispatchEvent(
		new PointerEvent(type, {
			pointerId: 1,
			pointerType: 'mouse',
			button: 0,
			bubbles: true,
			cancelable: true,
			clientX
		})
	);
}

function stubMomentumTiming(): void {
	vi.stubGlobal(
		'requestAnimationFrame',
		vi.fn(() => 1)
	);
	vi.stubGlobal('cancelAnimationFrame', vi.fn());
	vi.stubGlobal('performance', { now: () => 0 });
}

async function openRailGroup(root: ParentNode, index: number): Promise<void> {
	const disclosure = root.querySelectorAll<HTMLButtonElement>(
		'.rail-group > .disclose-row > button.disclose'
	)[index];
	if (!disclosure) throw new Error('Expected the Library disclosure');
	if (disclosure.getAttribute('aria-expanded') === 'false') disclosure.click();
	await tick();
}

beforeEach(() => {
	discardDraft();
	loadSongData(makeSong());
	localStorage.clear();
	railWidth.set(264);
	railCollapsed.set(false);
	resetLibraryContextForTests();
	selectedSongId.set(null);
	railTreeQuery.set('');
	albumList.set([]);
	replaceHistoryEntry('/');
});

afterEach(async () => {
	await cleanup();
	if (collapsedMounted) await unmount(collapsedMounted);
	collapsedMounted = undefined;
	resetLibraryContextForTests();
	selectedSongId.set(null);
	railTreeQuery.set('');
	resetPlaylistsForTests();
	discardDraft();
	pendingDirtyNavigation.set(null);
	vi.mocked(goto).mockClear();
	vi.unstubAllGlobals();
});

describe('Rail', () => {
	it('renders the brand, the LIBRARY and PLAYLISTS groups, and the settings disclosure, and no account row', async () => {
		albumList.set([album({ id: 'a1', title: 'A' })]);
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
		expect(target.querySelector('.rail-bottom, .user-row, .collapsed-account')).toBeNull();
	});

	it('renders the only search field directly beneath the brand', async () => {
		const target = await render();
		const searchFields = target.querySelectorAll('input[type="search"]');
		expect(searchFields).toHaveLength(1);
		expect(searchFields[0]?.getAttribute('placeholder')).toBe('Search or go to…');
		expect(target.querySelector('.rail-top + .rail-search-region .rail-search')).not.toBeNull();
	});

	it('reduces the rail to labelled group icons when collapsed', async () => {
		const target = await renderCollapsedRail();
		const rail = requireElement<HTMLElement>(target, '.rail');

		expect(rail.classList.contains('rail-collapsed')).toBe(true);
		expect(
			requireElement<HTMLButtonElement>(rail, '.rail-collapse').getAttribute('aria-label')
		).toBe('Expand rail');
		expect(rail.querySelector('.rail-search-region')).not.toBeNull();
		expect(rail.querySelectorAll<HTMLInputElement>('input[type="search"]')).toHaveLength(1);
		for (const label of ['Library', 'Playlists', 'Settings']) {
			const group = Array.from(rail.querySelectorAll<HTMLButtonElement>('.disclose')).find(
				(button) => button.getAttribute('aria-label') === label
			);
			expect(group?.getAttribute('title')).toBe(label);
		}
		expect(rail.querySelector('input[type="range"]')).toBeNull();
	});

	it('resizes from its accessible handle without moving focus or the rail scroll anchor', async () => {
		const target = await render();
		const handle = requireElement<HTMLInputElement>(target, 'input[type="range"]');
		const scroll = requireElement<HTMLElement>(target, '.rail-scroll');
		scroll.scrollTop = 48;

		expect(handle.getAttribute('aria-label')).toBe('Resize rail');
		expect(handle.min).toBe(String(RAIL_MIN_WIDTH_PX));
		expect(handle.max).toBe(String(RAIL_MAX_WIDTH_PX));
		handle.focus();
		fireRailResizePointer(handle, 'pointerdown', 264);
		fireRailResizePointer(window, 'pointermove', RAIL_MAX_WIDTH_PX + 40);
		fireRailResizePointer(window, 'pointerup', RAIL_MAX_WIDTH_PX + 40);
		await tick();

		expect(get(railWidth)).toBe(RAIL_MAX_WIDTH_PX);
		expect(document.activeElement).toBe(handle);
		expect(scroll.scrollTop).toBe(48);
	});

	it('resizes in keyboard steps and clamps the focused handle', async () => {
		const target = await render();
		const handle = requireElement<HTMLInputElement>(target, 'input[type="range"]');
		railWidth.set(RAIL_MAX_WIDTH_PX);
		handle.focus();

		handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		expect(get(railWidth)).toBe(RAIL_MAX_WIDTH_PX);
		handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
		expect(get(railWidth)).toBe(RAIL_MAX_WIDTH_PX - 8);
		railWidth.set(RAIL_MIN_WIDTH_PX);
		handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
		expect(get(railWidth)).toBe(RAIL_MIN_WIDTH_PX);
		expect(document.activeElement).toBe(handle);
	});

	it.each(['/', '/library', '/album/a1', '/settings'])(
		'1354_rule_40: Home leads the pages and is current only at /, standing at %s',
		async (path) => {
			replaceHistoryEntry(path);
			librarySurface.set('home');
			openCollection.set({ kind: 'album', id: 'a1' });
			const target = await render();
			const links = target.querySelectorAll<HTMLAnchorElement>(
				'.rail-scroll > a, .rail-scroll a.page-link'
			);
			expect(Array.from(links, (link) => link.textContent?.trim())).toEqual([
				'Home',
				'Library 0',
				'Playlists 0'
			]);
			expect(links[0]?.getAttribute('href')).toBe('/');
			expect(links[0]?.getAttribute('aria-current')).toBe(path === '/' ? 'page' : null);
		}
	);

	it.each([
		{ path: '/', surface: 'home', label: 'Home' },
		{ path: '/library', surface: 'browse', label: 'Library 0' },
		{ path: '/playlists', surface: 'playlists', label: 'Playlists 0' }
	] as const)(
		'1354_rule_40: $label current mark follows song visibility at $path',
		async ({ path, surface, label }) => {
			replaceHistoryEntry(path);
			librarySurface.set(surface);
			const target = await render();
			const currentLabels = () =>
				Array.from(target.querySelectorAll('a.rail-page-link[aria-current="page"]'), (link) =>
					link.textContent?.trim()
				);
			expect(currentLabels()).toEqual([label]);
			selectedSongId.set('unresolved-song');
			await tick();
			expect(currentLabels()).toEqual([]);
			selectedSongId.set(null);
			await tick();
			expect(currentLabels()).toEqual([label]);
		}
	);

	it.each(modifiedClicks)('1354_rule_40: Home preserves browser handling for %o', async (mouse) => {
		replaceHistoryEntry('/library');
		librarySurface.set('browse');
		setDraftLyrics('unsaved draft');
		const target = await render();
		let preventedByHome = true;
		target.addEventListener('click', (event) => {
			preventedByHome = event.defaultPrevented;
			event.preventDefault();
		});
		requireElement<HTMLAnchorElement>(target, 'a.home-link').dispatchEvent(
			new MouseEvent('click', { bubbles: true, cancelable: true, ...mouse })
		);
		await tick();
		expect(preventedByHome).toBe(false);
		expect(location.pathname).toBe('/library');
		expect(get(librarySurface)).toBe('browse');
		expect(get(pendingDirtyNavigation)).toBeNull();
	});

	it.each(['home', 'browse', 'detail'] as const)(
		'1354_rule_40: Home is not current over an unresolved song on %s',
		async (surface) => {
			replaceHistoryEntry('/?song=missing');
			librarySurface.set(surface);
			selectedSongId.set('missing');
			const target = await render();
			expect(requireElement(target, 'a.home-link').getAttribute('aria-current')).toBeNull();
		}
	);

	it.each([false, true])(
		'1354_rule_40: Home opens through the dirty guard, dirty=%s',
		async (dirty) => {
			replaceHistoryEntry('/album/a1');
			librarySurface.set('detail');
			if (dirty) setDraftLyrics('unsaved draft');
			const target = await render();
			requireElement<HTMLAnchorElement>(target, 'a.home-link').click();
			await tick();
			await Promise.resolve();
			expect(get(pendingDirtyNavigation) !== null).toBe(dirty);
			expect(get(librarySurface)).toBe(dirty ? 'detail' : 'home');
		}
	);

	it.each([false, true])(
		'1354_rule_28: page titles follow this rail collapse state, collapsed=%s',
		async (collapsed) => {
			railCollapsed.set(true);
			const target = collapsed ? await renderCollapsedRail() : await render();
			for (const link of target.querySelectorAll<HTMLAnchorElement>('a.home-link, a.page-link')) {
				expect(link.hasAttribute('title')).toBe(collapsed);
				const icon = requireElement<SVGElement>(link, 'svg');
				expect(icon.getAttribute('width')).toBe('14');
				expect(icon.getAttribute('height')).toBe('14');
				expect(icon.closest('[aria-hidden="true"]')).not.toBeNull();
			}
		}
	);

	it('1354_rule_40: acts as the Home link when the brand wordmark is clicked, keeping the open collection', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		const target = await render();
		const brand = requireElement<HTMLButtonElement>(target, '.brand');
		// Named after what it is (the wordmark), not what it does -- GitHub's own
		// logo pattern -- so it never collides with the LIBRARY group's own
		// "Library" name in an accessible-name lookup.
		expect(brand.hasAttribute('aria-label')).toBe(false);
		expect(brand.textContent).toBe('Hallucinai');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('home');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('scrolls the LIBRARY and PLAYLISTS groups, pinning Settings below them', async () => {
		const target = await render();
		const scroll = requireElement(target, '.rail-scroll');
		const scrolledGroups = scroll.querySelectorAll('.rail-group > .disclose-row');
		expect(scrolledGroups).toHaveLength(2);
		expect(scrolledGroups[0]?.querySelector('.group-title')?.textContent?.trim()).toBe('Library');
		expect(scrolledGroups[1]?.querySelector('.group-title')?.textContent?.trim()).toBe('Playlists');
		expect(scroll.textContent).not.toContain('Settings');

		const settingsPin = requireElement(target, '.rail-settings-pin');
		const settingsToggle = settingsPin.querySelector(
			'.rail-group > .disclose-row > button.disclose'
		);
		expect(settingsToggle?.textContent).toContain('Settings');
	});

	it('opens an album through the kinetic rail click', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		const albumButton = findButtonByText(target, 'Sonnwendfeuer');

		fireClick(albumButton);

		await vi.waitFor(() => {
			expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
		});
	});

	it('does not open an album after dragging the kinetic rail', async () => {
		stubMomentumTiming();
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		const scroll = requireElement<HTMLElement>(target, '.rail-scroll');
		scroll.style.flexDirection = 'column';
		Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true });
		Object.defineProperty(scroll, 'scrollHeight', { value: 400, configurable: true });

		firePointer(scroll, 'pointerdown', 200, 1000);
		firePointer(scroll, 'pointermove', 150, 1010);
		firePointer(scroll, 'pointerup', 150, 1040);
		fireClick(findButtonByText(target, 'Sonnwendfeuer'));
		await tick();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('does not open an album when a click catches the rail momentum', async () => {
		stubMomentumTiming();
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Morning Run' })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		const target = await render();
		await openRailGroup(target, 0);
		await openRailGroup(target, 1);
		const scroll = requireElement<HTMLElement>(target, '.rail-scroll');
		scroll.style.flexDirection = 'column';
		Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true });
		Object.defineProperty(scroll, 'scrollHeight', { value: 400, configurable: true });

		firePointer(scroll, 'pointerdown', 200, 1000);
		firePointer(scroll, 'pointermove', 150, 1010);
		firePointer(scroll, 'pointerup', 150, 1040);
		fireClick(findButtonByText(target, 'Sonnwendfeuer'));
		firePointer(scroll, 'pointerdown', 150, 1100);
		firePointer(scroll, 'pointerup', 150, 1100);
		fireClick(findButtonByText(target, 'Morning Run'));
		await tick();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens a playlist through the kinetic rail click', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Morning Run' })
		]);
		const target = await render();
		await openRailGroup(target, 1);

		fireClick(findButtonByText(target, 'Morning Run'));

		await vi.waitFor(() => {
			expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p2' });
		});
	});

	it('keeps PLAYLISTS open when the word Library returns to the wall', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
		playlistList.set([playlist({ id: 'p1', title: 'Night Drive', entry_count: 0 })]);
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			detail({ id: 'p1', title: 'Night Drive', entry_count: 0, entries: [] })
		);
		const target = await render();
		const playlistPanel = requireElement<HTMLDivElement>(target, '.playlist-songs');
		expect(playlistPanel.getAttribute('data-open')).toBe('true');

		requireElement<HTMLAnchorElement>(target, 'a.page-link').click();
		await vi.waitFor(() => expect(get(librarySurface)).toBe('browse'));
		await tick();

		expect(playlistPanel.getAttribute('data-open')).toBe('true');
	});

	it('marks the open album and the open playlist alike, as the current page', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Sonnwendfeuer' })
		]);
		playlistList.set([
			playlist({ id: 'p1', title: 'Morning Run', entry_count: 0 }),
			playlist({ id: 'p2', title: 'Night Drive', entry_count: 0 })
		]);
		setOpenCollection({ kind: 'album', id: 'a1' });
		librarySurface.set('detail');
		selectedPlaylistDetail.set(null);
		const target = await render();

		const albumLabels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		const playlistLabels = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		expect(albumLabels).toHaveLength(2);
		expect(playlistLabels).toHaveLength(2);

		const currentPages = () =>
			[...albumLabels, ...playlistLabels].map((row) => row.getAttribute('aria-current'));

		// The open album is marked, its sibling is not -- no third state, same
		// as the open playlist below.
		expect(currentPages()).toEqual(['page', null, null, null]);

		setOpenCollection({ kind: 'playlist', id: 'p2' });
		await tick();

		expect(currentPages()).toEqual([null, null, null, 'page']);
	});

	it.each([
		{ kind: 'album', id: 'a1', rowSelector: '.album-label' },
		{ kind: 'playlist', id: 'p1', rowSelector: '.playlist-label' }
	] as const)(
		'marks no $kind as the current page on the wall, which keeps the $kind open last',
		async ({ kind, id, rowSelector }) => {
			albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
			playlistList.set([playlist({ id: 'p1', title: 'Morning Run', entry_count: 0 })]);
			setOpenCollection({ kind, id });
			librarySurface.set('detail');
			const target = await render();
			const openRow = requireElement<HTMLButtonElement>(target, rowSelector);
			expect(openRow.getAttribute('aria-current')).toBe('page');

			librarySurface.set('browse');
			await tick();

			expect(openRow.getAttribute('aria-current')).toBeNull();
		}
	);
});
