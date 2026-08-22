import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA, HITBOX_FREQUENT_PX } from '$lib/constants';
import { checkAuth, currentUser, authLoading } from '$lib/stores/auth';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { openCollection } from '$lib/stores/collection';
import { closeSidebar } from '$lib/stores/ui';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';

const { pageState } = vi.hoisted(() => ({
	pageState: { url: new URL('https://songmaker.test/') }
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

const VIEWPORT_PX = 320;
const USER = { id: 'u1', username: 'felix', role: 'user' as const };

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
	currentUser.set(null);
	authLoading.set(false);
	closeSidebar();
	audioPlayer.destroy();
	vi.mocked(checkAuth).mockReset();
	vi.unstubAllGlobals();
});

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
		const brand = requireElement<HTMLAnchorElement>(strip, '.brand');

		expect(target.querySelector('.rail')).toBeNull();
		expect(brand.textContent).toBeTruthy();

		const stripStyle = getComputedStyle(strip);
		const pad = px(stripStyle.paddingLeft) + px(stripStyle.paddingRight);
		const gap = px(stripStyle.gap);
		expect(minUsedWidth(trigger)).toBe(HITBOX_FREQUENT_PX);
		const used = pad + minUsedWidth(trigger) + gap + px(getComputedStyle(brand).minWidth || '0');
		expect(used).toBeLessThanOrEqual(VIEWPORT_PX);
	});

	it('opens the rail drawer from the trigger on every private route', async () => {
		const target = await renderLayout('/loras');
		expect(document.body.querySelector('.rail')).toBeNull();
		requireElement<HTMLButtonElement>(target, '.drawer-trigger').click();
		await tick();
		const rail = requireElement<HTMLElement>(document.body, '.rail');
		expect(requireElement<HTMLAnchorElement>(rail, 'a[href="/"]').textContent).toBeTruthy();
	});

	it('renders the rail inline instead of a drawer on wide layouts', async () => {
		stubMatchMedia(false);
		delete document.documentElement.dataset.pointer;
		const target = await renderLayout('/');
		expect(target.querySelector('.mobile-strip')).toBeNull();
		expect(requireElement(target, '.rail')).toBeTruthy();
	});
});
