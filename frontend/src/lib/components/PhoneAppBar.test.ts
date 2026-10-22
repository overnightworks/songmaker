import { backLabel } from '$lib/routes/pageBack';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { libraryAddressOverlayActive } from '$lib/stores/libraryAddressOverlay';
import { phoneAppBar } from '$lib/stores/ui';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import {
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	APP_NAME,
	HITBOX_FREQUENT_PX,
	HOME_PAGE_LABEL,
	RAIL_SEARCH_LABEL,
	SEARCH_OPEN_LABEL
} from '$lib/constants';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import type { Pathname } from '$app/types';
import {
	historyStandsStill,
	installHistoryController,
	loadHistoryPageForTests,
	pushEntry,
	resetHistoryControllerForTests,
	stampNavigatedEntry
} from '$lib/history/historyController';
import { HOME_ROUTE_PATH, LIBRARY_ROUTE_PATH } from '$lib/routes/addresses';
import { reportedNavigations, startFakeRouter } from '$lib/test-utils/app-navigation';
import { resetLayersForTests } from '$lib/stores/layers';
import { albumList, songList } from '$lib/stores/libraryData';
import { playlistList, resetPlaylistsForTests } from '$lib/stores/playlists';
import { resetRailSearchForTests } from '$lib/stores/railSearch';
import { railTreeQuery } from '$lib/stores/librarySearch';
import { buildAlbum, buildPlaylist, buildSong } from './shell/rail-test-fixtures';
import PhoneAppBar, { SEARCH_CLOSE_LABEL, SEARCH_SHEET_LABEL } from './PhoneAppBar.svelte';

vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());

const navigation = vi.hoisted(() => ({
	openAppPage: vi.fn(),
	openLibraryWall: vi.fn(),
	openRailSearchTarget: vi.fn()
}));
vi.mock('$lib/stores/navigation', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/navigation')>()),
	...navigation
}));

vi.mock('$lib/api/library', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/library')>()),
	searchLibrary: vi.fn(() => new Promise(() => undefined))
}));

const playlistsOnServer = vi.hoisted(() => ({ fetchPlaylists: vi.fn() }));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchPlaylists: playlistsOnServer.fetchPlaylists
}));

const mounted: Array<ReturnType<typeof mount>> = [];

const ACCOUNT_CIRCLE_NAME = `${ACCOUNT_MENU_LABEL} · felix`;

function renderBar(onlogout = vi.fn()): HTMLElement {
	const target = document.createElement('div');
	target.style.width = '390px';
	document.body.append(target);
	mounted.push(mount(PhoneAppBar, { target, props: { username: 'felix', onlogout } }));
	return target;
}

function expectFrequentHitbox(button: HTMLButtonElement, name: string): void {
	expect(button.dataset.hitbox).toBe('frequent');
	expect(minSquarePx(button, name)).toEqual({
		width: HITBOX_FREQUENT_PX,
		height: HITBOX_FREQUENT_PX
	});
}

function queryButton(root: ParentNode, name: string): HTMLButtonElement | null {
	try {
		return getByRoleButton(root, name);
	} catch {
		return null;
	}
}

function searchSheet(): HTMLElement | null {
	return document.querySelector(`[role="dialog"][aria-label="${SEARCH_SHEET_LABEL}"]`);
}

// The app's own pages the bar names, as the library holds them.
function seedLibrary(): void {
	albumList.set([
		buildAlbum({ id: 'a1', title: 'Broken Lanterns' }),
		buildAlbum({ id: 'a2', title: 'Cold Harbour' })
	]);
	songList.set([buildSong({ album_id: 'a2', slug: 'quiet-wind', title: 'Quiet Wind' })]);
	playlistList.set([buildPlaylist({ slug: 'night-drive', title: 'Night Drive' })]);
}

// The app loads on `address` in a fresh tab, the way the root layout starts
// it: the router starts over the tab's first entry and reports it, and history
// stands still once the start has run to its end.
async function enterAppOn(address: string): Promise<void> {
	history.replaceState(null, '', address);
	const length = vi.spyOn(history, 'length', 'get').mockReturnValue(1);
	resetHistoryControllerForTests();
	loadHistoryPageForTests();
	startFakeRouter();
	installHistoryController();
	stampNavigatedEntry('enter');
	length.mockRestore();
	await historyStandsStill();
}

// The root layout stamps every navigation the router reports, in order.
function stampNavigationsReportedSince(count: number): void {
	for (const { type } of reportedNavigations.slice(count)) stampNavigatedEntry(type);
}

async function followLinkTo(address: Pathname): Promise<void> {
	const reported = reportedNavigations.length;
	// `resolve` has one overload per route; TypeScript cannot relate a union
	// this wide to them, so the address is narrowed to one static route.
	await goto(resolve(address as '/'));
	stampNavigationsReportedSince(reported);
}

// History as a person left it: `from` the page they opened `opened` from, or
// with no `from` the page the tab was entered on, with nothing of its own below.
async function standOn(opened: Pathname, from?: Pathname): Promise<void> {
	if (from === undefined) {
		await enterAppOn(opened);
		return;
	}
	await enterAppOn(from);
	await followLinkTo(opened);
}

// What ‹ is named now, or null on a page without one.
function backName(target: HTMLElement): string | null {
	return target.querySelector('header button.back')?.getAttribute('aria-label') ?? null;
}

// ‹ pressed, resolving once history has left the page and the root layout
// has stamped what the router reported on the way.
async function pressBarBack(target: HTMLElement): Promise<void> {
	const from = location.pathname;
	const reported = reportedNavigations.length;
	target.querySelector<HTMLButtonElement>('header button.back')?.click();
	await vi.waitFor(() => expect(location.pathname).not.toBe(from));
	stampNavigationsReportedSince(reported);
	await tick();
}

beforeEach(async () => {
	injectHitboxStyles();
	setPointer('coarse');
	phoneAppBar.set(null);
	sessionStorage.clear();
	await enterAppOn(LIBRARY_ROUTE_PATH);
	seedLibrary();
	playlistsOnServer.fetchPlaylists.mockResolvedValue([]);
	for (const open of Object.values(navigation)) open.mockClear();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	phoneAppBar.set(null);
	libraryAddressOverlayActive.set(false);
	resetHistoryControllerForTests();
	resetLayersForTests();
	resetRailSearchForTests();
	railTreeQuery.set('');
	albumList.set([]);
	songList.set([]);
	resetPlaylistsForTests();
	clearHitboxStyles();
	clearPointer();
	vi.restoreAllMocks();
	document.body.replaceChildren();
});

function songBar(onrename = vi.fn(async () => undefined)) {
	return {
		kind: 'song' as const,
		title: 'Sommerlicht',
		onrename,
		share: {
			isShared: false,
			shareSlug: null,
			onshare: vi.fn(),
			onunshare: vi.fn()
		},
		menu: {
			saveDisabled: true,
			onsave: vi.fn(),
			onaddtoplaylist: vi.fn(),
			ondelete: vi.fn()
		}
	};
}

// Whether the workspace-style `inert` reaches the element: jsdom has no
// hit-testing, so the attribute on it or an ancestor is what a browser acts on.
function isInert(element: Element | null): boolean {
	return element?.closest('[inert]') != null;
}

describe('PhoneAppBar', () => {
	it('1354_rule_32: offers song Back beside named touch actions, search and inline rename', async () => {
		const onrename = vi.fn(async () => undefined);
		await standOn('/album/a2/quiet-wind', '/album/a2');
		phoneAppBar.set(songBar(onrename));
		const target = renderBar();
		await tick();
		expect(target.querySelector('h1')?.textContent?.trim()).toBe('Sommerlicht');
		expect(target.querySelector('.brand')).toBeNull();
		expect(queryButton(target, ACCOUNT_CIRCLE_NAME)).toBeNull();
		for (const name of [backLabel('Cold Harbour'), SEARCH_OPEN_LABEL, 'Share song', 'Song menu']) {
			expectFrequentHitbox(getByRoleButton(target, name), name);
		}
		await tick();
		getByRoleButton(target, 'Song menu').click();
		await tick();
		getByRoleButton(target, 'Rename').click();
		await tick();
		const input = target.querySelector<HTMLInputElement>('input[aria-label="Song title"]');
		if (!input) throw new Error('Expected inline title input');
		input.value = 'Abendlicht';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await tick();
		expect(onrename).toHaveBeenCalledWith('Abendlicht');
	});

	it('defect:#1531: waits with the workspace while an address overlay is up, and acts once it is gone', async () => {
		phoneAppBar.set(songBar());
		libraryAddressOverlayActive.set(true);
		const target = renderBar();
		await tick();
		const songControls = (): Element[] => [
			target.querySelector('h1') as Element,
			getByRoleButton(target, 'Share song'),
			getByRoleButton(target, 'Song menu')
		];
		const otherControls = [getByRoleButton(target, SEARCH_OPEN_LABEL)];

		expect(songControls().map(isInert)).toEqual([true, true, true]);
		expect(otherControls.map(isInert)).toEqual([false]);

		libraryAddressOverlayActive.set(false);
		await tick();
		expect(songControls().map(isInert)).toEqual([false, false, false]);
		getByRoleButton(target, 'Song menu').click();
		await tick();
		expect(getByRoleButton(target, 'Delete song')).toBeTruthy();

		libraryAddressOverlayActive.set(true);
		await tick();
		expect(songControls().map(isInert)).toEqual([true, true, true]);
	});

	it("carries search and the viewer's account circle at the right on the Library", async () => {
		const target = renderBar();
		await tick();

		const header = target.querySelector('header');
		expect(header?.textContent).toContain(APP_NAME);
		const circle = getByRoleButton(target, ACCOUNT_CIRCLE_NAME);
		expect(circle.textContent?.trim()).toBe('F');
		expect(header?.lastElementChild?.contains(circle)).toBe(true);
		expectFrequentHitbox(circle, ACCOUNT_CIRCLE_NAME);
		expectFrequentHitbox(getByRoleButton(target, SEARCH_OPEN_LABEL), SEARCH_OPEN_LABEL);
	});

	// #1402, #1506: Home and the Playlists page are places the app opens on, as
	// the Library is.
	it.each<{ place: string; address: Pathname; entered: string; from?: Pathname }>([
		{ place: 'Home', address: HOME_ROUTE_PATH, entered: 'fresh' },
		{ place: 'Home', address: HOME_ROUTE_PATH, entered: 'from an album', from: '/album/a1' },
		{ place: 'the Playlists page', address: '/playlists', entered: 'fresh' },
		{
			place: 'the Playlists page',
			address: '/playlists',
			entered: 'from an album',
			from: '/album/a1'
		}
	])(
		'1354_rule_25: carries the brand, search and the account circle without ‹ on $place entered $entered',
		async ({ address, from }) => {
			await standOn(address, from);
			const target = renderBar();
			await tick();

			expect(backName(target)).toBeNull();
			expect(target.querySelector('.brand')?.textContent).toBe(APP_NAME);
			expect(queryButton(target, SEARCH_OPEN_LABEL)).not.toBeNull();
			expect(queryButton(target, ACCOUNT_CIRCLE_NAME)).not.toBeNull();
		}
	);

	it('keeps Sign out off the bar and one tap away in the account menu', async () => {
		const onlogout = vi.fn();
		const target = renderBar(onlogout);
		await tick();
		const bar = target.querySelector('header');
		if (!bar) throw new Error('Expected the app bar');
		const logoutOnBar = () => getByRoleButton(bar, ACCOUNT_MENU_LOGOUT_LABEL);
		expect(logoutOnBar).toThrow();

		getByRoleButton(target, ACCOUNT_CIRCLE_NAME).click();
		await tick();
		getByRoleButton(document.body, ACCOUNT_MENU_LOGOUT_LABEL).click();

		expect(onlogout).toHaveBeenCalledOnce();
	});

	// #1354 rule 25: ‹ is named after where it goes, and a page opened from
	// another one carries no account circle (navigation.html, frame I3).
	it.each<{ page: string; opened: Pathname; from?: Pathname; name: string }>([
		{
			page: 'an album opened from the Library',
			opened: '/album/a1',
			from: LIBRARY_ROUTE_PATH,
			name: 'Library'
		},
		{
			page: 'an album opened from Home',
			opened: '/album/a1',
			from: HOME_ROUTE_PATH,
			name: HOME_PAGE_LABEL
		},
		{
			page: 'an album opened from another album',
			opened: '/album/a1',
			from: '/album/a2',
			name: 'Cold Harbour'
		},
		{
			page: 'a playlist opened from a song',
			opened: '/playlist/night-drive',
			from: '/album/a2/quiet-wind',
			name: 'Quiet Wind'
		},
		{
			page: 'Settings opened from a playlist',
			opened: '/settings',
			from: '/playlist/night-drive',
			name: 'Night Drive'
		},
		{
			page: 'a Settings section opened from the Settings list',
			opened: '/settings/voices',
			from: '/settings',
			name: 'Settings'
		},
		{
			page: 'a playlist opened from the Playlists page',
			opened: '/playlist/night-drive',
			from: '/playlists',
			name: 'Playlists'
		},
		{ page: 'an album with nothing before it', opened: '/album/a1', name: 'Library' },
		{
			page: 'a playlist with nothing before it',
			opened: '/playlist/night-drive',
			name: 'Playlists'
		},
		{
			page: 'a Settings section with nothing before it',
			opened: '/settings/voices',
			name: 'Settings'
		},
		{ page: 'Settings with nothing before it', opened: '/settings', name: 'Library' }
	])(
		'1354_rule_25: names ‹ on $page after $name, beside search and without the account circle',
		async ({ opened, from, name }) => {
			await standOn(opened, from);
			const target = renderBar();
			await tick();

			const back = getByRoleButton(target, backLabel(name));
			expect(back.textContent?.trim()).toBe(name);
			expectFrequentHitbox(back, backLabel(name));
			expect(queryButton(target, SEARCH_OPEN_LABEL)).not.toBeNull();
			expect(queryButton(target, ACCOUNT_CIRCLE_NAME)).toBeNull();
			expect(target.querySelector('.brand')).toBeNull();
		}
	);

	it.each([
		{ from: '/album/a2' as const, name: 'Cold Harbour' },
		{ from: '/' as const, name: HOME_PAGE_LABEL }
	])('1354_rule_32: song ‹ traverses to $name without adding an entry', async ({ from, name }) => {
		await standOn('/album/a2/quiet-wind', from);
		phoneAppBar.set(songBar());
		const target = renderBar();
		await tick();
		const length = history.length;
		getByRoleButton(target, backLabel(name)).click();
		await vi.waitFor(() => expect(location.pathname).toBe(from));
		expect(history).toHaveLength(length);
	});

	it('renames ‹ when history moves onto another page', async () => {
		const target = renderBar();
		await tick();
		expect(queryButton(target, backLabel('Library'))).toBeNull();

		pushEntry('/album/a2', {});
		await tick();
		pushEntry('/album/a1', {});
		await tick();

		expect(queryButton(target, backLabel('Cold Harbour'))).not.toBeNull();
	});

	it('steps back on ‹ onto the page below, whose ‹ names the page below it', async () => {
		await standOn('/album/a2', LIBRARY_ROUTE_PATH);
		await followLinkTo('/album/a1');
		const target = renderBar();
		await tick();
		const tabLength = history.length;

		await pressBarBack(target);

		expect(location.pathname).toBe('/album/a2');
		expect(history).toHaveLength(tabLength);
		expect(backName(target)).toBe(backLabel('Library'));
	});
});

// #1354 rule 26: 🔍 opens the one search in a sheet of its own.
describe('PhoneAppBar search sheet', () => {
	async function openSearch(): Promise<HTMLElement> {
		const target = renderBar();
		await tick();
		getByRoleButton(target, SEARCH_OPEN_LABEL).click();
		await tick();
		const sheet = searchSheet();
		if (!sheet) throw new Error('Expected the search sheet');
		return sheet;
	}

	it('opens over the page with the search field focused', async () => {
		await standOn('/album/a1', LIBRARY_ROUTE_PATH);

		const sheet = await openSearch();

		expect(sheet.getAttribute('aria-modal')).toBe('true');
		expect(document.activeElement?.getAttribute('aria-label')).toBe(RAIL_SEARCH_LABEL);
		expectFrequentHitbox(getByRoleButton(sheet, SEARCH_CLOSE_LABEL), SEARCH_CLOSE_LABEL);
	});

	it('closes on Back and leaves the page where it was', async () => {
		await standOn('/album/a1', LIBRARY_ROUTE_PATH);
		await openSearch();

		history.back();

		await vi.waitFor(() => expect(searchSheet()).toBeNull());
		expect(location.pathname).toBe('/album/a1');
	});

	it('closes on its own ‹', async () => {
		const sheet = await openSearch();

		getByRoleButton(sheet, SEARCH_CLOSE_LABEL).click();
		await tick();

		expect(searchSheet()).toBeNull();
	});

	it('finds playlists on a page loaded directly, which lists none itself', async () => {
		resetPlaylistsForTests();
		playlistsOnServer.fetchPlaylists.mockResolvedValue([
			buildPlaylist({ slug: 'night-drive', title: 'Night Drive' })
		]);
		await standOn('/settings/voices');
		const sheet = await openSearch();
		const field = sheet.querySelector<HTMLInputElement>('input[type="search"]');
		if (!field) throw new Error('Expected the search field');

		field.value = 'night';
		field.dispatchEvent(new Event('input', { bubbles: true }));

		await vi.waitFor(() =>
			expect(
				Array.from(sheet.querySelectorAll('[role="option"]'), (option) => option.textContent)
			).toEqual([expect.stringContaining('Night Drive')])
		);
	});

	it('closes and opens what was chosen', async () => {
		const sheet = await openSearch();
		const field = sheet.querySelector<HTMLInputElement>('input[type="search"]');
		if (!field) throw new Error('Expected the search field');

		field.value = 'night';
		field.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		sheet.querySelector<HTMLElement>('[role="option"]')?.click();
		await tick();

		expect(searchSheet()).toBeNull();
		expect(navigation.openRailSearchTarget).toHaveBeenCalledWith({ kind: 'playlist', id: 'p1' });
	});
});
