import { backLabel } from '$lib/routes/pageBack';
import {
	historyEntry,
	pressBack,
	replaceHistoryEntry,
	standingHistoryEntry,
	watchBack
} from '$lib/test-utils/library-history';
import { fakePage, reportFakeRouterEnter, startFakeRouter } from '$lib/test-utils/app-navigation';
import {
	documentLoads as documentLoadStandIn,
	documentLoadsStandIn
} from '$lib/test-utils/document-loads';
import {
	historyStandsStill,
	pushEntry,
	resetHistoryControllerForTests,
	standInForDocumentLoadsForTests
} from '$lib/history/historyController';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { createRawSnippet, flushSync, mount, tick, unmount, type Snippet } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	COMPACT_LAYOUT_MEDIA,
	HITBOX_FREQUENT_PX,
	OFFLINE_STRIP_MESSAGE,
	RATE_LIMITED_TOAST_MESSAGE,
	RAIL_SETTINGS_LABEL,
	SEARCH_OPEN_LABEL
} from '$lib/constants';
import { SEARCH_SHEET_LABEL } from '$lib/components/PhoneAppBar.svelte';
import { apiFetch } from '$lib/api/fetch';
import { AUTH_CHECK_NETWORK_ERROR, AUTH_CHECK_RETURN_PROBE_INTERVAL_MS } from '$lib/constants/auth';
import {
	checkAuth,
	currentUser,
	authLoading,
	authCheckError,
	handleSessionLost,
	resetAuthForTests
} from '$lib/stores/auth';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { openCollection } from '$lib/stores/collection';
import {
	currentLibraryHistoryState,
	isLibraryHistoryState,
	libraryRootState,
	librarySurface,
	loadLibraryHistoryPageForTests,
	resetLibraryContextForTests,
	openHomeAddress,
	openLibraryAddress
} from '$lib/stores/libraryContext';
import { HOME_ROUTE_PATH, LIBRARY_ROUTE_PATH } from '$lib/routes/addresses';
import { resetNavigationForTests } from '$lib/stores/navigation';
import { songList } from '$lib/stores/libraryData';
import { toasts } from '$lib/stores/toast';
import {
	closeNowPlaying,
	nowPlayingDockable,
	nowPlayingSurface,
	openNowPlaying,
	selectedSongId
} from '$lib/stores/player';
import {
	NOW_PLAYING_DOCKED_WIDTH_PX,
	NOW_PLAYING_EXPAND_LABEL,
	NOW_PLAYING_STACKED_MAX_PX
} from '$lib/constants/now-playing';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { openOnScreenKeyboard } from '$lib/test-utils/on-screen-keyboard';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { phoneAppBar, railCollapsed, railWidth } from '$lib/stores/ui';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';

const { liveStream } = vi.hoisted(() => ({
	liveStream: {
		start: vi.fn(),
		stop: vi.fn(),
		waitForReady: vi.fn(async () => true)
	}
}));

vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/environment', () => ({
	browser: true,
	dev: true
}));
vi.mock('$lib/stores/auth', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/auth')>();
	return {
		...actual,
		checkAuth: vi.fn(async () => {
			const user = { id: 'u1', username: 'felix', role: 'user' as const };
			actual.currentUser.set(user);
			actual.authLoading.set(false);
			return user;
		})
	};
});
vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchCapabilities: vi.fn().mockResolvedValue({})
	};
});
vi.mock('$lib/stores/resourceSync', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/resourceSync')>();
	return {
		...actual,
		startLibraryResourceSync: liveStream.start,
		stopLibraryResourceSync: liveStream.stop,
		waitForResourceReady: liveStream.waitForReady
	};
});
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

import Layout from './+layout.svelte';
import layoutSource from './+layout.svelte?raw';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';

// `?raw` yields an empty string for a stylesheet under this vitest config
// (CSS processing is off), so app.css is read from disk instead.
const appCss = readFileSync(join(process.cwd(), 'src/app.css'), 'utf8');

const VIEWPORT_PX = 320;
const USER = { id: 'u1', username: 'felix', role: 'user' as const };

function extractRule(source: string, selector: string): string {
	const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = new RegExp(`${escaped}\\s*{([^}]*)}`).exec(source);
	if (!match) throw new Error(`Expected rule ${selector} in stylesheet`);
	return match[1];
}

let mounted: ReturnType<typeof mount> | undefined;
const children = createRawSnippet(() => ({
	render: () => `<main><button data-testid="workspace-focus">Workspace action</button></main>`
}));

function stubMatchMedia(matches: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches,
			media: COMPACT_LAYOUT_MEDIA,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function px(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	const parsed = Number.parseFloat(resolved);
	return Number.isFinite(parsed) ? parsed : 0;
}

function minUsedWidth(el: Element): number {
	const style = getComputedStyle(el);
	return px(style.minWidth) || px(style.width);
}

async function renderLayout(path: string, pageContent: Snippet = children): Promise<HTMLElement> {
	currentUser.set(USER);
	authLoading.set(false);
	const target = mountLayout(path, pageContent);
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

// Mounts the layout the way the router starts a page: on `path`, reporting
// the `enter` navigation once it is mounted.
function mountLayout(path: string, pageContent: Snippet = children): HTMLElement {
	fakePage.url = new URL(`https://songmaker.test${path}`);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Layout, { target, props: { children: pageContent } });
	flushSync();
	reportFakeRouterEnter();
	return target;
}

async function unmountCurrentLayout(): Promise<void> {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
}

beforeEach(() => {
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	stubMatchMedia(true);
	document.documentElement.dataset.pointer = 'coarse';
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: VIEWPORT_PX });
	vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	vi.mocked(checkAuth).mockImplementation(async () => {
		currentUser.set(USER);
		authLoading.set(false);
		return USER;
	});
	openCollection.set({ kind: 'album', id: 'a1' });
	liveStream.start.mockClear();
	liveStream.stop.mockClear();
	vi.mocked(goto).mockClear();
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
});

afterEach(async () => {
	await unmountCurrentLayout();
	document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	openCollection.set(null);
	selectedSongId.set(null);
	closeNowPlaying();
	audioPlayer.current = null;
	songList.set([]);
	currentUser.set(null);
	authLoading.set(false);
	authCheckError.set(null);
	phoneAppBar.set(null);
	railCollapsed.set(false);
	localStorage.removeItem('songmaker.rail-collapsed');
	railWidth.set(264);
	localStorage.removeItem('songmaker.rail-width');
	audioPlayer.destroy();
	vi.mocked(checkAuth).mockReset();
	vi.unstubAllGlobals();
	resetAuthForTests();
	resetConnectivityForTests();
});

const TAKE = makeGeneration({
	generation_number: 2,
	mp3_path: 'a.mp3',
	seed: 1,
	model_mode: 'sft',
	version_lyrics: 'old verse',
	created_at: ''
});

const PLAYING_SONG = makeSong({
	slug: 'tide',
	title: 'Tide',
	album_title: 'Nachtstrom',
	lyrics: 'old verse',
	prompt: 'dreamy',
	created_at: '',
	generations: [TAKE]
});

function playing(songTitle = 'Tide'): PlaybackInfo {
	return {
		generation: TAKE,
		songId: 's1',
		songTitle,
		artist: 'Artist',
		albumTitle: 'Nachtstrom',
		lyrics: 'old verse'
	};
}

// Evaluates the one media feature these layout subscriptions use, so a test
// can name a viewport width instead of a blanket true/false. A fine-pointer
// device never matches `(any-pointer: coarse)`; the `data-pointer` override
// that stands in for touch is applied by subscribeCompactLayout itself.
function stubMatchMediaAtWidth(width: number): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => {
			const maxWidth = /max-width:\s*(\d+)px/.exec(query);
			return {
				matches: maxWidth !== null && width <= Number(maxWidth[1]),
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			};
		})
	);
}

/**
 * A fine-pointer viewport, wide enough for the docked panel unless told
 * otherwise — by default the narrowest one that is, a pixel past the width at
 * which Now Playing stops standing its three columns side by side (#185).
 */
async function renderDesktopLayout(width = NOW_PLAYING_STACKED_MAX_PX + 1): Promise<HTMLElement> {
	stubMatchMediaAtWidth(width);
	delete document.documentElement.dataset.pointer;
	return renderLayout(LIBRARY_ROUTE_PATH);
}

function pressEscape(target: EventTarget): void {
	target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

describe('app shell', () => {
	it('keeps the private PlayerBar and body reservation visible while idle', async () => {
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		const body = requireElement<HTMLElement>(target, '.app-shell');

		expect(audioPlayer.current).toBeNull();
		expect(target.querySelector('.player-bar')).not.toBeNull();
		expect(body.classList.contains('has-player')).toBe(true);
		const workspaceAction = requireElement<HTMLButtonElement>(
			target,
			'[data-testid="workspace-focus"]'
		);
		workspaceAction.focus();
		expect(document.activeElement).toBe(workspaceAction);
		expect(body.compareDocumentPosition(requireElement(target, '.player-bar'))).toBe(
			Node.DOCUMENT_POSITION_FOLLOWING
		);
	});

	it.each(['/login', '/no-access', '/auth/callback', '/share/public-token'])(
		'keeps the PlayerBar and reservation out of public route %s',
		async (path) => {
			const target = await renderLayout(path);
			expect(target.querySelector('.player-bar')).toBeNull();
			expect(target.querySelector('.app-shell')).toBeNull();
		}
	);

	it('keeps the PlayerBar and reservation out while auth is loading', async () => {
		currentUser.set(null);
		authLoading.set(true);
		vi.mocked(checkAuth).mockImplementationOnce(() => new Promise(() => {}));
		const target = mountLayout(LIBRARY_ROUTE_PATH);
		await tick();

		expect(target.querySelector('.loading')).not.toBeNull();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(target.querySelector('.app-shell')).toBeNull();
	});

	it('removes the PlayerBar and reservation after auth loss', async () => {
		const privateTarget = await renderLayout(LIBRARY_ROUTE_PATH);
		expect(privateTarget.querySelector('.player-bar')).not.toBeNull();
		currentUser.set(null);
		await tick();
		expect(privateTarget.querySelector('.player-bar')).toBeNull();
		expect(privateTarget.querySelector('.app-shell')).toBeNull();
		expect(privateTarget.querySelector('.phone-tabs')).toBeNull();
		expect(document.documentElement.dataset.phoneTabs).toBeUndefined();
	});

	it('keeps the mobile strip brand and account circle inside 320px', async () => {
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		const strip = requireElement<HTMLElement>(target, '.mobile-strip');
		const brand = requireElement<HTMLButtonElement>(strip, '.brand');
		const accountCircle = requireElement<HTMLButtonElement>(strip, '.account-menu .menu-trigger');

		expect(target.querySelector('.rail')).toBeNull();
		expect(brand.textContent).toBeTruthy();

		const stripStyle = getComputedStyle(strip);
		const pad = px(stripStyle.paddingLeft) + px(stripStyle.paddingRight);
		const gap = px(stripStyle.gap);
		expect(minUsedWidth(accountCircle)).toBe(HITBOX_FREQUENT_PX);
		const used =
			pad + px(getComputedStyle(brand).minWidth || '0') + gap + minUsedWidth(accountCircle);
		expect(used).toBeLessThanOrEqual(VIEWPORT_PX);
	});

	it.each([
		['/', true],
		['/library', true],
		['/playlists', true],
		['/album/summer', true],
		['/playlist/favourites', true],
		['/album/summer/song', false],
		['/album/summer/song/take/3', false],
		['/settings', true],
		['/settings/voices', true],
		['/loras', true],
		['/share/public', false],
		['/login', false],
		['/no-access', false],
		['/auth/callback', false]
	])('1354_rule_28 1354_rule_33 1354_49: mount-time tabs at %s are %s', async (path, shown) => {
		replaceHistoryEntry(path);
		selectedSongId.set('retained-song');
		const target = await renderLayout(path);
		expect(target.querySelector('.phone-tabs') !== null).toBe(shown);
		expect(document.documentElement.hasAttribute('data-phone-tabs')).toBe(shown);
		expect(target.querySelector('[aria-label="Open menu"]')).toBeNull();
		if (path.startsWith('/settings') || path === '/loras')
			expect(target.querySelector('.phone-tabs [aria-current]')).toBeNull();
		await unmountCurrentLayout();
		expect(document.documentElement.hasAttribute('data-phone-tabs')).toBe(false);
	});

	it('1354_61_C29: tabs own the safe area once, through the shared room tokens', () => {
		expect(extractRule(appCss, ':root')).toContain(
			'--phone-tabs-room: calc(var(--phone-tabs-height) + env(safe-area-inset-bottom, 0px))'
		);
		const rule = extractRule(appCss, 'html[data-phone-tabs]');
		expect(rule).toContain('--shell-bottom-offset: var(--phone-tabs-room)');
		expect(rule).toContain('--transport-safe-area-bottom: 0px');
	});

	it('leaves public transport room intact with retained user and full-player state', async () => {
		nowPlayingSurface.set('full');
		await renderLayout('/share/public');
		expect(document.documentElement.dataset.transportBar).toBeUndefined();
		expect(document.documentElement.dataset.phoneTabs).toBeUndefined();
	});

	it('hides tabs with full Now Playing and restores them on close', async () => {
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		nowPlayingSurface.set('full');
		await tick();
		expect(target.querySelector('.phone-tabs')).toBeNull();
		nowPlayingSurface.set('closed');
		await tick();
		expect(target.querySelector('.phone-tabs')).not.toBeNull();
	});

	it('1354_rule_40: acts as the Home link when the mobile-strip brand is clicked', async () => {
		librarySurface.set('detail');
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		const brand = requireElement<HTMLButtonElement>(target, '.mobile-strip .brand');
		// The wordmark is named after the app.
		expect(brand.hasAttribute('aria-label')).toBe(false);
		expect(brand.textContent).toBe('Hallucinai');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('home');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('1354_rule_32: keeps song Back and actions in the same strip without a menu', async () => {
		phoneAppBar.set({
			kind: 'song',
			title: 'Sommerlicht',
			onrename: vi.fn(),
			share: { isShared: false, shareSlug: null, onshare: vi.fn(), onunshare: vi.fn() },
			menu: { saveDisabled: true, onsave: vi.fn(), onaddtoplaylist: vi.fn(), ondelete: vi.fn() }
		});
		replaceHistoryEntry('/album/summer/sommerlicht');
		const target = await renderLayout('/album/summer/sommerlicht');
		expect(target.querySelectorAll('.mobile-strip')).toHaveLength(1);
		const strip = requireElement<HTMLElement>(target, '.mobile-strip');
		expect(strip.querySelector('button[aria-label="Back to Album"]')).not.toBeNull();
		expect(strip.querySelector('h1')?.textContent?.trim()).toBe('Sommerlicht');
		expect(strip.querySelector('.brand')).toBeNull();
		expect(strip.querySelector('[aria-label="Open menu"]')).toBeNull();
		phoneAppBar.set(null);
		await tick();
		expect(strip.querySelector('.brand')).toBeNull();
		expect(strip.querySelector('.back')?.textContent?.trim()).toBe('Album');
	});

	it('renders the rail inline on wide layouts, keeping its Settings group and no account row', async () => {
		stubMatchMedia(false);
		delete document.documentElement.dataset.pointer;
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		expect(target.querySelector('.mobile-strip')).toBeNull();
		expect(target.querySelector('.phone-tabs')).toBeNull();
		const rail = requireElement<HTMLElement>(target, '.rail');
		expect(rail.textContent).toContain(RAIL_SETTINGS_LABEL);
		expect(rail.querySelector('.rail-bottom')).toBeNull();
	});

	it('makes the desktop workspace follow the rail edge control', async () => {
		const target = await renderDesktopLayout();
		const shell = requireElement<HTMLElement>(target, '.shell-row');
		const rail = requireElement<HTMLElement>(shell, '.rail');
		const control = requireElement<HTMLButtonElement>(rail, '.rail-collapse');

		expect(shell.classList.contains('rail-collapsed')).toBe(false);
		expect(control.getAttribute('aria-label')).toBe('Collapse rail');
		control.click();
		await tick();

		expect(get(railCollapsed)).toBe(true);
		expect(shell.classList.contains('rail-collapsed')).toBe(true);
		expect(rail.classList.contains('rail-collapsed')).toBe(true);
		expect(localStorage.getItem('songmaker.rail-collapsed')).toBe('true');
	});

	it('makes the desktop shell inherit the remembered expanded rail width', async () => {
		localStorage.setItem('songmaker.rail-width', '320');
		const target = await renderDesktopLayout();
		const shell = requireElement<HTMLElement>(target, '.shell-row');
		const rail = requireElement<HTMLElement>(shell, '.rail');

		expect(shell.style.getPropertyValue('--rail-expanded-width')).toBe('320px');
		expect(rail.style.width).toBe('');
	});

	// T1/T2/T6 (#999, #1017): the shell alone decides that a field has focus
	// on the phone with its keyboard open; the bar and its reserved room step aside for the keyboard.
	// The room collapses through the one transport-bar fact, so the shell,
	// the song page's panel, the toast stack and the queue-stream chip all
	// give it back together.
	it('hands the bottom to the keyboard while a field has focus on the phone, and takes it back on leaving it', async () => {
		const closeKeyboard = openOnScreenKeyboard();
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		const lyrics = document.createElement('textarea');
		requireElement<HTMLElement>(target, 'main').append(lyrics);

		lyrics.focus();
		await tick();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(target.querySelector('.phone-tabs')).toBeNull();
		expect(document.documentElement.dataset.transportBar).toBe('hidden');
		expect(requireElement(target, '.mobile-strip')).toBeTruthy();

		lyrics.blur();
		await tick();
		expect(target.querySelector('.player-bar')).not.toBeNull();
		expect(document.documentElement.dataset.transportBar).toBeUndefined();
		closeKeyboard();
	});

	it('keeps the transport bar and its room on the desktop while a field has focus', async () => {
		const closeKeyboard = openOnScreenKeyboard();
		const target = await renderDesktopLayout();
		const lyrics = document.createElement('textarea');
		requireElement<HTMLElement>(target, 'main').append(lyrics);

		lyrics.focus();
		await tick();
		expect(target.querySelector('.player-bar')).not.toBeNull();
		expect(document.documentElement.dataset.transportBar).toBeUndefined();
		closeKeyboard();
	});

	// O1 (#1080): the offline strip rests on the transport bar, and the room
	// every surface reserves for the bar grows by the strip while it shows, so
	// the phone's Generate bar stays above the strip instead of under it.
	it('1354_37b_66: adds the offline strip to the room the transport bar takes, and gives it back online', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);
		expect(document.documentElement.dataset.offline).toBeUndefined();

		reportResourceStreamReachable(false);
		await tick();
		expect(document.documentElement.dataset.offline).toBe('');
		expect(extractRule(appCss, ':root').replace(/\s+/g, '')).toContain(
			'--player-height:calc(var(--shell-bottom-offset)+var(--transport-bar-height)+var(--offline-strip-room))'
		);
		expect(extractRule(appCss, 'html[data-offline]')).toContain(
			'--offline-strip-room: var(--offline-strip-height)'
		);

		reportResourceStreamReachable(true);
		await tick();
		expect(document.documentElement.dataset.offline).toBeUndefined();
	});

	it('leaves the offline room out of public routes, which have no transport bar to rest on', async () => {
		reportResourceStreamReachable(false);
		await renderLayout('/login');
		expect(document.documentElement.dataset.offline).toBeUndefined();
	});

	it('lays out the mobile app-shell as a flex column, mirroring desktop, so content below the fold stays reachable', () => {
		const rule = extractRule(layoutSource, '.app-shell.mobile');
		expect(rule).toContain('display: flex');
		expect(rule).toContain('flex-direction: column');
	});
});

describe('global Escape', () => {
	it('goes from a song to its collection', async () => {
		selectedSongId.set('s1');
		await renderLayout(LIBRARY_ROUTE_PATH);
		pressEscape(window);
		await tick();
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('goes from the collection to the Library wall', async () => {
		selectedSongId.set(null);
		librarySurface.set('detail');
		await renderLayout(LIBRARY_ROUTE_PATH);
		pressEscape(window);
		await tick();
		expect(get(librarySurface)).toBe('browse');
	});

	it('does nothing while typing in a textarea', async () => {
		selectedSongId.set('s1');
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		const textarea = document.createElement('textarea');
		target.append(textarea);
		pressEscape(textarea);
		await tick();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('1354_37b_71_escape: closes the open Search sheet first and leaves the song only on the next Escape', async () => {
		selectedSongId.set('s1');
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		getByRoleButton(target, SEARCH_OPEN_LABEL).click();
		await tick();

		pressEscape(window);
		await tick();
		expect(target.querySelector(`[role="dialog"][aria-label="${SEARCH_SHEET_LABEL}"]`)).toBeNull();
		expect(get(selectedSongId)).toBe('s1');

		pressEscape(window);
		await tick();
		expect(get(selectedSongId)).toBeNull();
	});
});

describe('docked Now Playing', () => {
	beforeEach(() => {
		// The surface resolves the playing take against the song list; seeding it
		// keeps the test off the API.
		songList.set([PLAYING_SONG]);
	});

	it('opens as a column of the shell row, leaving the workspace and the transport bar in place', async () => {
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();

		openNowPlaying('queue');
		await tick();

		const panel = requireElement<HTMLElement>(target, '.now-playing.docked');
		expect(panel.parentElement?.classList.contains('shell-row')).toBe(true);
		expect(panel.style.width).toBe(`${NOW_PLAYING_DOCKED_WIDTH_PX}px`);
		expect(target.querySelector('main')).not.toBeNull();
		expect(target.querySelector('.player-bar')).not.toBeNull();
	});

	it('is no overlay: no dialog role, no aria-modal, and no transport of its own', async () => {
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();

		openNowPlaying('queue');
		await tick();

		const panel = requireElement<HTMLElement>(target, '.now-playing.docked');
		expect(panel.getAttribute('role')).toBe('complementary');
		expect(panel.getAttribute('aria-modal')).toBeNull();
		expect(panel.querySelector('.transport')).toBeNull();
		expect(panel.querySelector('.progress')).toBeNull();
	});

	it('does not trap Tab inside the panel, so the workspace stays reachable', async () => {
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();

		const workspaceButton = requireElement<HTMLButtonElement>(
			target,
			'[data-testid="workspace-focus"]'
		);
		workspaceButton.focus();
		workspaceButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));

		expect(document.activeElement).toBe(workspaceButton);
	});

	it('expands to the full surface, which hides the transport bar', async () => {
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();

		const expand = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent?.trim() === NOW_PLAYING_EXPAND_LABEL
		);
		expand?.click();
		await tick();

		const surface = requireElement<HTMLElement>(target, '.now-playing');
		expect(surface.classList.contains('docked')).toBe(false);
		expect(surface.getAttribute('aria-modal')).toBe('true');
		expect(target.querySelector('.player-bar')).toBeNull();
	});

	it('Escape steps out of the full surface into the panel, then out of Now Playing', async () => {
		selectedSongId.set('s1');
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();
		nowPlayingSurface.set('full');
		await tick();

		pressEscape(target.querySelector('.now-playing') ?? window);
		await tick();
		expect(target.querySelector('.now-playing.docked')).not.toBeNull();

		pressEscape(window);
		await tick();
		expect(target.querySelector('.now-playing')).toBeNull();
		// Leaving Now Playing is the whole level-up: the open song stays open.
		expect(get(selectedSongId)).toBe('s1');
	});

	it('Escape closes a full surface the window narrowed the docked panel into, and the song stays', async () => {
		selectedSongId.set('s1');
		audioPlayer.current = playing();
		const target = await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();
		nowPlayingDockable.set(false);
		await tick();
		expect(target.querySelector('.now-playing.docked')).toBeNull();

		pressEscape(target.querySelector('.now-playing') ?? window);
		await tick();

		expect(target.querySelector('.now-playing')).toBeNull();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('follows the playing take while it stays open', async () => {
		audioPlayer.current = playing('Tide');
		const target = await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();
		expect(requireElement(target, '.cover-title').textContent).toBe('Tide');

		audioPlayer.current = playing('Second');
		await tick();

		expect(requireElement(target, '.cover-title').textContent).toBe('Second');
	});

	// One owner for "the room the transport bar takes right now": the shell
	// rows, the toast stack, the queue-stream chip and Now Playing's own sheet
	// all read --player-height, so hiding the bar has to collapse that one
	// value rather than leave each surface its own exception.
	it('collapses the reserved transport-bar height while the full surface hides the bar', async () => {
		audioPlayer.current = playing();
		await renderDesktopLayout();
		openNowPlaying('queue');
		await tick();
		expect(document.documentElement.dataset.transportBar).toBeUndefined();

		nowPlayingSurface.set('full');
		await tick();
		expect(document.documentElement.dataset.transportBar).toBe('hidden');
		expect(extractRule(appCss, "html[data-transport-bar='hidden']")).toContain(
			'--player-height: 0px'
		);

		closeNowPlaying();
		await tick();
		expect(document.documentElement.dataset.transportBar).toBeUndefined();
	});

	// Too narrow for Now Playing's own three columns is too narrow to stand
	// them beside the workspace: one threshold, not two (#185).
	it('takes the whole screen on a viewport too narrow to spare the panel its width', async () => {
		audioPlayer.current = playing();
		const target = await renderDesktopLayout(NOW_PLAYING_STACKED_MAX_PX);

		openNowPlaying('queue');
		await tick();

		expect(target.querySelector('.now-playing.docked')).toBeNull();
		expect(requireElement(target, '.now-playing').getAttribute('aria-modal')).toBe('true');
	});

	it('opens full screen on a compact viewport, which has no room to dock', async () => {
		audioPlayer.current = playing();
		const target = await renderLayout(LIBRARY_ROUTE_PATH);

		openNowPlaying('queue');
		await tick();

		expect(target.querySelector('.now-playing.docked')).toBeNull();
		expect(requireElement(target, '.now-playing').getAttribute('aria-modal')).toBe('true');
		expect(target.querySelector('.player-bar')).toBeNull();
	});
});

describe('auth check failure', () => {
	function signInRedirects(): unknown[] {
		return [
			...documentLoadStandIn.assign.mock.calls,
			...documentLoadStandIn.replace.mock.calls
		].map(([to]) => to);
	}

	beforeEach(() => {
		resetHistoryControllerForTests();
		standInForDocumentLoadsForTests(documentLoadStandIn);
		for (const load of Object.values(documentLoadStandIn)) load.mockReset();
	});

	it('shows a retry-able error instead of navigating to sign-in on a transient failure', async () => {
		currentUser.set(null);
		authLoading.set(true);
		authCheckError.set(null);
		vi.mocked(checkAuth).mockImplementationOnce(async () => {
			currentUser.set(null);
			authLoading.set(false);
			authCheckError.set('Too many requests. Retry in a moment to check your session.');
			return null;
		});
		const target = mountLayout(LIBRARY_ROUTE_PATH);
		await tick();
		await Promise.resolve();
		await tick();

		expect(signInRedirects()).toEqual([]);
		expect(target.querySelector('.app-shell')).toBeNull();
		const retry = requireElement<HTMLButtonElement>(target, '.auth-retry button');
		expect(retry.textContent).toBe('Retry');
		expect(target.querySelector('.auth-retry')?.textContent).toContain('Too many requests');
	});

	it('with the server out of reach and the browser online shows the offline strip, not the session error, and loads the app once the server answers', async () => {
		const actual = await vi.importActual<typeof import('$lib/stores/auth')>('$lib/stores/auth');
		vi.mocked(checkAuth).mockImplementation(actual.checkAuth);
		currentUser.set(null);
		authLoading.set(true);
		vi.stubGlobal(
			'fetch',
			vi
				.fn()
				.mockRejectedValueOnce(new TypeError('Failed to fetch'))
				.mockImplementation(async () => Response.json(USER))
		);

		const target = mountLayout(LIBRARY_ROUTE_PATH);

		await vi.waitFor(() => expect(target.textContent).toContain(OFFLINE_STRIP_MESSAGE));
		expect(target.textContent).not.toContain(AUTH_CHECK_NETWORK_ERROR);
		expect(target.querySelector('.auth-retry')).toBeNull();
		expect(signInRedirects()).toEqual([]);

		await vi.waitFor(() => expect(target.querySelector('.app-shell')).not.toBeNull(), {
			timeout: AUTH_CHECK_RETURN_PROBE_INTERVAL_MS * 3
		});
		expect(target.textContent).not.toContain(OFFLINE_STRIP_MESSAGE);
		expect(signInRedirects()).toEqual([]);
	});

	it.each([
		['the library', HOME_ROUTE_PATH, '/login/oidc?next=%2F'],
		[
			'a logged-out deep link',
			'/album/northern-lights/glass-river',
			'/login/oidc?next=%2Falbum%2Fnorthern-lights%2Fglass-river'
		]
	])(
		'sends %s to the sign-in start with a full navigation on a 401 (no known user, no check error)',
		async (_label, path, signIn) => {
			currentUser.set(null);
			authLoading.set(true);
			authCheckError.set(null);
			vi.mocked(checkAuth).mockImplementationOnce(async () => {
				currentUser.set(null);
				authLoading.set(false);
				authCheckError.set(null);
				return null;
			});
			mountLayout(path);

			await vi.waitFor(() =>
				expect(signInRedirects()).toEqual([`${window.location.origin}${signIn}`])
			);
			expect(goto).not.toHaveBeenCalled();
		}
	);

	it.each(['/login', '/no-access', '/auth/callback', '/share/public-token'])(
		'never sends the public address %s to sign-in',
		async (path) => {
			currentUser.set(null);
			authLoading.set(true);
			vi.mocked(checkAuth).mockImplementation(async () => null);
			mountLayout(path);
			await tick();
			await Promise.resolve();
			await tick();

			expect(checkAuth).not.toHaveBeenCalled();
			expect(signInRedirects()).toEqual([]);
		}
	);
});

// SvelteKit's start drops the library a reloaded entry carried, and shallow
// routing waits for that start (issue #1165).
describe('a reload on a library page', () => {
	it('puts the library its entry carried back once the router reports the start', async () => {
		resetLibraryContextForTests();
		resetNavigationForTests();
		const playlist = {
			...libraryRootState(),
			surface: 'detail' as const,
			collection: { kind: 'playlist' as const, id: 'p1' },
			scrollAnchor: 480
		};
		replaceHistoryEntry('/playlist/friday-night', playlist);
		loadLibraryHistoryPageForTests();
		startFakeRouter();

		await renderLayout('/playlist/friday-night');

		await vi.waitFor(() => expect(historyEntry()).toEqual(playlist));
		expect(location.pathname).toBe('/playlist/friday-night');
	});
});

// A phone tab reloaded over the full Now Playing comes back onto a layer entry
// no open layer owns; with no session the sign-in start loads afresh from
// there, with no step back, and the return lands on the page (issue #1002).
describe('a reload over the phone Now Playing', () => {
	it.each([
		{ page: 'Home', address: HOME_ROUTE_PATH, openAddress: openHomeAddress, surface: 'home' },
		{
			page: 'the Library wall',
			address: LIBRARY_ROUTE_PATH,
			openAddress: openLibraryAddress,
			surface: 'browse'
		}
	] as const)(
		'1354_rule_31: the sign-in start loads afresh from the entry the reload left, and the return stays on $page',
		async ({ address, openAddress, surface }) => {
			resetHistoryControllerForTests();
			resetLibraryContextForTests();
			const playlist = {
				...libraryRootState(),
				index: 1,
				surface: 'detail' as const,
				collection: { kind: 'playlist' as const, id: 'p1' }
			};
			pushEntry('/playlist/friday-night', { library: playlist });
			pushEntry('/playlist/friday-night', { library: playlist }, 'now-playing');
			// The reload forgets the open layer, so its entry is left unowned on top.
			resetNavigationForTests();
			loadLibraryHistoryPageForTests();
			startFakeRouter();
			const signInLoads = documentLoadsStandIn();
			standInForDocumentLoadsForTests(signInLoads);
			currentUser.set(null);
			vi.mocked(checkAuth).mockImplementation(async () => null);
			mountLayout(address);
			await vi.waitFor(() =>
				expect(signInLoads.assign).toHaveBeenCalledWith(
					`${window.location.origin}/login/oidc?next=${encodeURIComponent(address)}`
				)
			);
			expect(signInLoads.replace).not.toHaveBeenCalled();
			await historyStandsStill();

			// The server sends the person back to the address in a new document.
			await unmountCurrentLayout();
			vi.mocked(checkAuth).mockImplementation(async () => {
				currentUser.set(USER);
				return USER;
			});
			mountLayout(address);
			await goto(resolve(address));
			await openAddress();

			await vi.waitFor(() =>
				expect(isLibraryHistoryState(currentLibraryHistoryState())).toBe(true)
			);
			expect(currentLibraryHistoryState()).toMatchObject({ collection: null, surface });
			expect(location.pathname).toBe(address);
		}
	);
});

// A sign-out the server can answer posts the logout form over the account
// menu's entry, and nothing steps back on the way (#1340, ruling A; cells 17
// and 25). The account circle lives on the Library (#1354 rule 25).
describe('signing out on the phone', () => {
	it("from the open account menu posts the logout form over the menu's entry, and steps back nowhere", async () => {
		resetLibraryContextForTests();
		resetNavigationForTests();
		replaceHistoryEntry(LIBRARY_ROUTE_PATH);
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		await openLibraryAddress();
		await vi.waitFor(() => expect(isLibraryHistoryState(currentLibraryHistoryState())).toBe(true));
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => Response.json(USER))
		);
		const documentLoads = documentLoadsStandIn();
		standInForDocumentLoadsForTests(documentLoads);
		getByRoleButton(target, `${ACCOUNT_MENU_LABEL} · ${USER.username}`).click();
		await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('account-menu'));
		const backs = vi.spyOn(history, 'back');
		onTestFinished(() => backs.mockRestore());

		getByRoleButton(target, ACCOUNT_MENU_LOGOUT_LABEL).click();

		await vi.waitFor(() => expect(documentLoads.submitPost).toHaveBeenCalledWith('/auth/logout'));
		expect(standingHistoryEntry()?.layer).toBe('account-menu');
		expect(documentLoads.replace).not.toHaveBeenCalled();
		expect(documentLoads.assign).not.toHaveBeenCalled();
		expect(backs).not.toHaveBeenCalled();
	});
});

describe('a session lost behind the open Search sheet', () => {
	it('1354_37b_71_session: steps back nowhere, and loads the page afresh over the Search sheet entry (#1230)', async () => {
		resetLibraryContextForTests();
		resetNavigationForTests();
		replaceHistoryEntry(LIBRARY_ROUTE_PATH);
		const target = await renderLayout(LIBRARY_ROUTE_PATH);
		await openLibraryAddress();
		const documentLoads = documentLoadsStandIn();
		standInForDocumentLoadsForTests(documentLoads);
		await vi.waitFor(() => expect(isLibraryHistoryState(currentLibraryHistoryState())).toBe(true));
		getByRoleButton(target, SEARCH_OPEN_LABEL).click();
		await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('search-sheet'));

		const back = watchBack();
		let backPresses: number;
		try {
			await handleSessionLost();
			backPresses = back.presses();
		} finally {
			back.stop();
		}

		expect(documentLoads.replace).toHaveBeenCalledWith(
			`${window.location.origin}${LIBRARY_ROUTE_PATH}`
		);
		expect(documentLoads.reload).not.toHaveBeenCalled();
		expect(backPresses).toBe(0);
	});
});

// The history controller runs on every page, not only in the library, so
// Back closes an overlay on Settings before it leaves the page (#1331).
describe('overlays on Settings', () => {
	it('Back closes the search sheet and the address stays', async () => {
		replaceHistoryEntry('/settings/voices');
		const target = await renderLayout('/settings/voices');
		const sheet = () =>
			document.querySelector(`[role="dialog"][aria-label="${SEARCH_SHEET_LABEL}"]`);
		getByRoleButton(target, SEARCH_OPEN_LABEL).click();
		await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('search-sheet'));
		expect(sheet()).not.toBeNull();

		await pressBack();

		await vi.waitFor(() => expect(sheet()).toBeNull());
		expect(standingHistoryEntry()?.layer).toBeUndefined();
		expect(location.pathname).toBe('/settings/voices');
	});
});

// On a page the tab was entered on, nothing of the tab's own lies below, so ‹
// writes the page's list over the page (#1354 rule 25): the list shows, the
// tab holds no more entries than before, and the list's own ‹ goes on rather
// than back to the page it replaced (#1389).
describe('‹ on the page a phone tab was entered on', () => {
	function barBack(target: HTMLElement): HTMLButtonElement | null {
		return target.querySelector<HTMLButtonElement>('.mobile-strip button.back');
	}

	async function pressBarBack(target: HTMLElement, lands: string): Promise<void> {
		barBack(target)?.click();
		await vi.waitFor(() => expect(location.pathname).toBe(lands));
		await historyStandsStill();
		await tick();
	}

	function enterTabOn(address: string, entry: unknown = null): void {
		resetLibraryContextForTests();
		resetNavigationForTests();
		replaceHistoryEntry(address, entry);
		loadLibraryHistoryPageForTests();
		startFakeRouter();
	}

	it.each([
		{
			page: 'an album',
			address: '/album/a1',
			collection: { kind: 'album' as const, id: 'a1' },
			list: { name: 'Library', address: LIBRARY_ROUTE_PATH, surface: 'browse' }
		},
		{
			page: 'a playlist',
			address: '/playlist/friday-night',
			collection: { kind: 'playlist' as const, id: 'p1' },
			list: { name: 'Playlists', address: '/playlists', surface: 'playlists' }
		}
	])(
		'1354_rule_25: on $page shows the $list.name list in its place',
		async ({ address, collection, list }) => {
			const opened = { ...libraryRootState(), surface: 'detail' as const, collection };
			enterTabOn(address, opened);
			openCollection.set(collection);
			librarySurface.set('detail');
			const target = await renderLayout(address);
			await vi.waitFor(() => expect(historyEntry()).toEqual(opened));
			await historyStandsStill();
			const tabLength = history.length;
			expect(barBack(target)?.getAttribute('aria-label')).toBe(backLabel(list.name));

			await pressBarBack(target, list.address);

			expect(get(librarySurface)).toBe(list.surface);
			expect(historyEntry()).toMatchObject({ surface: list.surface, collection });
			expect(history).toHaveLength(tabLength);
			expect(barBack(target)).toBeNull();
		}
	);

	it('1354_rule_25: on a Settings section opens Settings, whose ‹ opens the Library wall', async () => {
		enterTabOn('/settings/voices');
		const target = await renderLayout('/settings/voices');
		await historyStandsStill();
		const tabLength = history.length;

		await pressBarBack(target, '/settings');

		expect(history).toHaveLength(tabLength);
		expect(barBack(target)?.getAttribute('aria-label')).toBe(backLabel('Library'));

		await pressBarBack(target, LIBRARY_ROUTE_PATH);

		expect(get(librarySurface)).toBe('browse');
		expect(historyEntry()).toMatchObject({ surface: 'browse' });
		expect(history).toHaveLength(tabLength);
		expect(barBack(target)).toBeNull();
	});
});

// The live library stream and the history listener used to belong to the
// workspace page. Three addresses share that workspace now (`/`,
// `/album/<slug>` and `/album/<slug>/<song-slug>`, issues #269, #275, #276)
// and this layout survives a swap between any of them, so it owns their
// lifetime -- while keeping the reach the page had: signed in, and only where
// the library is actually shown.
describe('the live library stream', () => {
	it.each([
		['Home', HOME_ROUTE_PATH],
		['the Library route', LIBRARY_ROUTE_PATH],
		['an album address', '/album/anfield'],
		['a song address', '/album/anfield/stadion-lauf-a'],
		['a playlist address', '/playlist/friday-night'],
		['the Playlists page', '/playlists']
	])('1354_rule_31: runs on %s', async (_name, path) => {
		await renderLayout(path);
		expect(liveStream.start).toHaveBeenCalled();
	});

	it.each([
		['Settings', '/settings/voices'],
		['the signed-out page', '/login'],
		['a public share page', '/share/some-slug']
	])('stays off %s, as it did before the layout owned it', async (_name, path) => {
		await renderLayout(path);
		expect(liveStream.start).not.toHaveBeenCalled();
	});

	it('stays off while nobody is signed in', async () => {
		currentUser.set(null);
		authLoading.set(false);
		vi.mocked(checkAuth).mockImplementation(async () => null);
		mountLayout(LIBRARY_ROUTE_PATH);
		await tick();
		await Promise.resolve();
		await tick();
		expect(liveStream.start).not.toHaveBeenCalled();
	});

	it('shuts down when the browser leaves the library', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);
		expect(liveStream.stop).not.toHaveBeenCalled();

		await unmountCurrentLayout();

		expect(liveStream.stop).toHaveBeenCalled();
	});
});

// The transport only reports a 429; this layout installs the reaction that
// tells the person (`stores/rateLimitNotice.ts`), and takes it away again.
describe('a 429 under the mounted layout', () => {
	function throttleToasts() {
		return get(toasts).filter((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
	}

	function aThrottledRead() {
		return apiFetch('/api/songs').catch(() => undefined);
	}

	beforeEach(() => {
		toasts.set([]);
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () => new Response(JSON.stringify({ detail: 'Too many requests' }), { status: 429 })
			)
		);
	});

	it('925_M3_L1: a request sent while the layout mounts is already reported to the throttle reaction', async () => {
		let sentWhileMounting: Promise<unknown> = Promise.resolve();
		const sendsARequestWhenMounted = createRawSnippet(() => ({
			render: () => '<main></main>',
			setup: () => {
				sentWhileMounting = aThrottledRead();
			}
		}));

		await renderLayout(LIBRARY_ROUTE_PATH, sendsARequestWhenMounted);
		await sentWhileMounting;

		expect(throttleToasts()).toHaveLength(1);
	});

	it('925_M3_L2: a burst of 429s on ordinary requests raises the throttle toast once', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);

		await Promise.all([aThrottledRead(), aThrottledRead(), aThrottledRead()]);

		expect(throttleToasts()).toHaveLength(1);
	});

	it('925_M3_L4: after the layout unmounts, a 429 raises no toast', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);
		await aThrottledRead();
		expect(throttleToasts()).toHaveLength(1);
		toasts.set([]);

		await unmountCurrentLayout();
		await aThrottledRead();

		expect(throttleToasts()).toHaveLength(0);
	});
});

// The transport only reports a 401; this layout installs the reaction that
// ends the session (`handleSessionLost`, in stores/auth.ts), and takes it away
// again.
describe('a 401 under the mounted layout', () => {
	const documentLoads = documentLoadsStandIn();

	function aRefusedRead() {
		return apiFetch('/api/songs').catch(() => undefined);
	}

	beforeEach(() => {
		resetHistoryControllerForTests();
		onTestFinished(resetHistoryControllerForTests);
		standInForDocumentLoadsForTests(documentLoads);
		for (const load of Object.values(documentLoads)) load.mockReset();
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () => new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 })
			)
		);
	});

	it('925_M3_L1: a request sent while the layout mounts already reaches the session-lost reaction', async () => {
		let sentWhileMounting: Promise<unknown> = Promise.resolve();
		const sendsARequestWhenMounted = createRawSnippet(() => ({
			render: () => '<main></main>',
			setup: () => {
				sentWhileMounting = aRefusedRead();
			}
		}));

		await renderLayout(LIBRARY_ROUTE_PATH, sendsARequestWhenMounted);
		await sentWhileMounting;

		expect(documentLoads.reload).toHaveBeenCalledOnce();
	});

	it('925_M3_L3: a 401 on an ordinary request with a user signed in loads the page afresh once', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);

		await Promise.all([aRefusedRead(), aRefusedRead()]);

		expect(documentLoads.reload).toHaveBeenCalledOnce();
	});

	it('925_M3_L4: after the layout unmounts, a 401 loads nothing', async () => {
		await renderLayout(LIBRARY_ROUTE_PATH);
		await unmountCurrentLayout();
		currentUser.set(USER);

		await aRefusedRead();

		expect(documentLoads.reload).not.toHaveBeenCalled();
	});
});

// The single-mount fix (issue #276) lives in a route group, not in this
// layout: `(library)/+layout.svelte` owns the one LibraryWorkspace mount, and
// every library address sits inside it -- Home, the Library (#1506), an album
// (and its song and take, one and two segments deeper), since issue #286 a
// playlist, and since #1402 the Playlists page.
// SvelteKit resolves a route group at build time, invisible to a mounted-
// component test, so this reads the routes tree directly instead -- the same
// way this file already reads app.css from disk.
describe('the library route group', () => {
	const routesDir = join(process.cwd(), 'src/routes');
	const libraryGroupDir = join(routesDir, '(library)');

	it('1354_rule_31: owns the workspace mount for every library address', () => {
		expect(readdirSync(libraryGroupDir).sort()).toEqual([
			'+layout.svelte',
			'+page.svelte',
			'album',
			// Home's own test harness and spec (issue #284's legacy `?song=`
			// redirect) -- listed here rather than left to break this assertion
			// silently, the same way `album/[slug]` already carries its own
			// harness.svelte/page.test.ts one level down.
			'harness.svelte',
			'library',
			'page.test.ts',
			'playlist',
			'playlists'
		]);
		expect(readFileSync(join(libraryGroupDir, '+layout.svelte'), 'utf8')).toContain(
			'LibraryWorkspace'
		);
		expect(readdirSync(join(libraryGroupDir, 'album/[slug]'))).toContain('+page.svelte');
		expect(readdirSync(join(libraryGroupDir, 'album/[slug]/[song]'))).toContain('+page.svelte');
		expect(readdirSync(join(libraryGroupDir, 'playlist/[slug]'))).toContain('+page.svelte');
		expect(readdirSync(join(libraryGroupDir, 'playlists'))).toContain('+page.svelte');
		expect(readdirSync(join(libraryGroupDir, 'library'))).toContain('+page.svelte');
	});

	it('leaves settings, auth, and share pages outside the group', () => {
		const topLevelDirs = readdirSync(routesDir, { withFileTypes: true })
			.filter((entry) => entry.isDirectory())
			.map((entry) => entry.name);

		expect(topLevelDirs).toEqual(
			expect.arrayContaining([
				'(library)',
				'settings',
				'login',
				'no-access',
				'auth',
				'share',
				'loras'
			])
		);
		expect(topLevelDirs).not.toContain('album');
		expect(topLevelDirs).not.toContain('playlist');
		expect(topLevelDirs).not.toContain('playlists');
	});
});
