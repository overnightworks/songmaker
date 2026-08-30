import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { COMPACT_LAYOUT_MEDIA, HITBOX_FREQUENT_PX } from '$lib/constants';
import { checkAuth, currentUser, authLoading, authCheckError } from '$lib/stores/auth';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { openCollection } from '$lib/stores/collection';
import { librarySurface } from '$lib/stores/libraryContext';
import { songList } from '$lib/stores/libraryData';
import {
	closeNowPlaying,
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
import type { GenerationItem, SongItem } from '$lib/api/types';
import { closeSidebar, sidebarOpen } from '$lib/stores/ui';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';

const { pageState, liveStream } = vi.hoisted(() => ({
	pageState: { url: new URL('https://songmaker.test/') },
	liveStream: {
		start: vi.fn(),
		stop: vi.fn(),
		waitForReady: vi.fn(async () => true)
	}
}));

vi.mock('$app/state', () => ({
	page: pageState
}));
vi.mock('$app/navigation', () => ({
	goto: vi.fn(),
	afterNavigate: vi.fn()
}));
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
		fetchCapabilities: vi.fn().mockResolvedValue({}),
		checkSetupRequired: vi.fn(),
		logout: vi.fn()
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

async function renderLayout(path: string): Promise<HTMLElement> {
	pageState.url = new URL(`https://songmaker.test${path}`);
	currentUser.set(USER);
	authLoading.set(false);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Layout, { target, props: { children } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

function mountLayout(path: string): HTMLElement {
	pageState.url = new URL(`https://songmaker.test${path}`);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(Layout, { target, props: { children } });
	return target;
}

async function unmountCurrentLayout(): Promise<void> {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
}

beforeEach(() => {
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
	closeSidebar();
	audioPlayer.destroy();
	vi.mocked(checkAuth).mockReset();
	vi.unstubAllGlobals();
});

const TAKE: GenerationItem = {
	id: 'g1',
	song_id: 's1',
	version_id: 'v1',
	version_number: 1,
	generation_number: 2,
	mp3_path: 'a.mp3',
	wav_path: null,
	seed: 1,
	status: 'completed',
	is_archived: false,
	is_picked: false,
	is_kept: false,
	is_shared: false,
	model_mode: 'sft',
	whisper_text: null,
	whisper_cues: null,
	version_lyrics: 'old verse',
	scores: null,
	generation_params: null,
	audio_duration_sec: null,
	created_at: ''
};

const PLAYING_SONG: SongItem = {
	id: 's1',
	title: 'Tide',
	album_id: 'a1',
	album_title: 'Nachtstrom',
	artist: 'Artist',
	track_number: 1,
	vocal_language: 'en',
	lyrics: 'old verse',
	prompt: 'dreamy',
	version_count: 1,
	generation_count: 1,
	is_shared: false,
	created_at: '',
	generations: [TAKE]
};

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
	return renderLayout('/');
}

function pressEscape(target: EventTarget): void {
	target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

describe('app shell', () => {
	it('keeps the private PlayerBar and body reservation visible while idle', async () => {
		const target = await renderLayout('/');
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

	it.each(['/login', '/setup', '/legal', '/share/public-token'])(
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
		const target = mountLayout('/');
		await tick();

		expect(target.querySelector('.loading')).not.toBeNull();
		expect(target.querySelector('.player-bar')).toBeNull();
		expect(target.querySelector('.app-shell')).toBeNull();
	});

	it('removes the PlayerBar and reservation after auth loss', async () => {
		const privateTarget = await renderLayout('/');
		expect(privateTarget.querySelector('.player-bar')).not.toBeNull();
		currentUser.set(null);
		await tick();
		expect(privateTarget.querySelector('.player-bar')).toBeNull();
		expect(privateTarget.querySelector('.app-shell')).toBeNull();
	});

	it('keeps the mobile strip trigger and brand inside 320px', async () => {
		const target = await renderLayout('/');
		const strip = requireElement<HTMLElement>(target, '.mobile-strip');
		const trigger = requireElement<HTMLButtonElement>(strip, '.drawer-trigger');
		const brand = requireElement<HTMLButtonElement>(strip, '.brand');

		expect(target.querySelector('.rail')).toBeNull();
		expect(brand.textContent).toBeTruthy();

		const stripStyle = getComputedStyle(strip);
		const pad = px(stripStyle.paddingLeft) + px(stripStyle.paddingRight);
		const gap = px(stripStyle.gap);
		expect(minUsedWidth(trigger)).toBe(HITBOX_FREQUENT_PX);
		const used = pad + minUsedWidth(trigger) + gap + px(getComputedStyle(brand).minWidth || '0');
		expect(used).toBeLessThanOrEqual(VIEWPORT_PX);
	});

	it('acts as the Library link when the mobile-strip brand is clicked', async () => {
		librarySurface.set('detail');
		const target = await renderLayout('/');
		const brand = requireElement<HTMLButtonElement>(target, '.mobile-strip .brand');
		expect(brand.getAttribute('aria-label')).toBe('Library');
		brand.click();
		await tick();
		await Promise.resolve();
		expect(get(librarySurface)).toBe('browse');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens the rail drawer from the trigger on every private route', async () => {
		const target = await renderLayout('/loras');
		expect(document.body.querySelector('.rail')).toBeNull();
		requireElement<HTMLButtonElement>(target, '.drawer-trigger').click();
		await tick();
		const rail = requireElement<HTMLElement>(document.body, '.rail');
		expect(requireElement<HTMLButtonElement>(rail, '.brand').textContent).toBeTruthy();
	});

	it('renders the rail inline instead of a drawer on wide layouts', async () => {
		stubMatchMedia(false);
		delete document.documentElement.dataset.pointer;
		const target = await renderLayout('/');
		expect(target.querySelector('.mobile-strip')).toBeNull();
		expect(requireElement(target, '.rail')).toBeTruthy();
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
		await renderLayout('/');
		pressEscape(window);
		await tick();
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('goes from the collection to the Library wall', async () => {
		selectedSongId.set(null);
		librarySurface.set('detail');
		await renderLayout('/');
		pressEscape(window);
		await tick();
		expect(get(librarySurface)).toBe('browse');
	});

	it('does nothing while typing in a textarea', async () => {
		selectedSongId.set('s1');
		const target = await renderLayout('/');
		const textarea = document.createElement('textarea');
		target.append(textarea);
		pressEscape(textarea);
		await tick();
		expect(get(selectedSongId)).toBe('s1');
	});

	it('does nothing while the rail drawer is open', async () => {
		selectedSongId.set('s1');
		await renderLayout('/');
		sidebarOpen.set(true);
		await tick();
		pressEscape(window);
		await tick();
		expect(get(selectedSongId)).toBe('s1');
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
		expect(document.documentElement.dataset.nowPlaying).toBeUndefined();

		nowPlayingSurface.set('full');
		await tick();
		expect(document.documentElement.dataset.nowPlaying).toBe('full');
		expect(extractRule(appCss, "html[data-now-playing='full']")).toContain('--player-height: 0px');
		// Same specificity as the coarse-pointer override of the same variable,
		// so only source order makes the collapse win.
		expect(appCss.indexOf("html[data-now-playing='full']")).toBeGreaterThan(
			appCss.indexOf("html[data-pointer='coarse']")
		);

		closeNowPlaying();
		await tick();
		expect(document.documentElement.dataset.nowPlaying).toBeUndefined();
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
		const target = await renderLayout('/');

		openNowPlaying('queue');
		await tick();

		expect(target.querySelector('.now-playing.docked')).toBeNull();
		expect(requireElement(target, '.now-playing').getAttribute('aria-modal')).toBe('true');
		expect(target.querySelector('.player-bar')).toBeNull();
	});
});

describe('auth check failure', () => {
	it('shows a retry-able error instead of navigating to /login on a transient failure', async () => {
		currentUser.set(null);
		authLoading.set(true);
		authCheckError.set(null);
		vi.mocked(checkAuth).mockImplementationOnce(async () => {
			currentUser.set(null);
			authLoading.set(false);
			authCheckError.set('Too many requests. Retry in a moment to check your session.');
			return null;
		});
		const target = mountLayout('/');
		await tick();
		await Promise.resolve();
		await tick();

		expect(goto).not.toHaveBeenCalled();
		expect(target.querySelector('.app-shell')).toBeNull();
		const retry = requireElement<HTMLButtonElement>(target, '.auth-retry button');
		expect(retry.textContent).toBe('Retry');
		expect(target.querySelector('.auth-retry')?.textContent).toContain('Too many requests');
	});

	it('navigates to /login on a 401 (no known user, no check error)', async () => {
		currentUser.set(null);
		authLoading.set(true);
		authCheckError.set(null);
		vi.mocked(checkAuth).mockImplementationOnce(async () => {
			currentUser.set(null);
			authLoading.set(false);
			authCheckError.set(null);
			return null;
		});
		mountLayout('/');
		await tick();
		await Promise.resolve();
		await tick();
		await Promise.resolve();
		await tick();

		expect(goto).toHaveBeenCalledWith('/login', { replaceState: true });
	});
});

// The live library stream and the history listener used to belong to the
// workspace page. Two routes mount that workspace now (`/` and
// `/album/<slug>`, issue #269) and the layout survives a swap between them,
// so it owns their lifetime -- while keeping the reach the page had: signed
// in, and only where the library is actually shown.
describe('the live library stream', () => {
	it.each([
		['the library route', '/'],
		['an album address', '/album/anfield']
	])('runs on %s', async (_name, path) => {
		await renderLayout(path);
		expect(liveStream.start).toHaveBeenCalled();
	});

	it.each([
		['Settings', '/settings/voices'],
		['the login page', '/login'],
		['a public share page', '/share/some-slug']
	])('stays off %s, as it did before the layout owned it', async (_name, path) => {
		await renderLayout(path);
		expect(liveStream.start).not.toHaveBeenCalled();
	});

	it('stays off while nobody is signed in', async () => {
		currentUser.set(null);
		authLoading.set(false);
		vi.mocked(checkAuth).mockImplementation(async () => null);
		mountLayout('/');
		await tick();
		await Promise.resolve();
		await tick();
		expect(liveStream.start).not.toHaveBeenCalled();
	});

	it('shuts down when the browser leaves the library', async () => {
		await renderLayout('/');
		expect(liveStream.stop).not.toHaveBeenCalled();

		await unmountCurrentLayout();

		expect(liveStream.stop).toHaveBeenCalled();
	});
});
