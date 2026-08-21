import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HITBOX_FREQUENT_PX } from '$lib/constants';
import { currentUser, authLoading } from '$lib/stores/auth';
import { selectedAlbumId } from '$lib/stores/player';
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

import Layout from './+layout.svelte';

const VIEWPORT_PX = 320;
const USER = { id: 'u1', username: 'felix', role: 'user' as const };

let mounted: ReturnType<typeof mount> | undefined;
const children = createRawSnippet(() => ({
	render: () => `<div></div>`
}));

function stubMatchMedia(matches: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches,
			media: '(max-width: 768px), (any-pointer: coarse)',
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

beforeEach(() => {
	stubMatchMedia(true);
	document.documentElement.dataset.pointer = 'coarse';
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: VIEWPORT_PX });
	selectedAlbumId.set('a1');
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	selectedAlbumId.set(null);
	currentUser.set(null);
	vi.unstubAllGlobals();
});

describe('app shell header', () => {
	it('keeps Brand, Back, and the account menu trigger inside 320px', async () => {
		const target = await renderLayout('/');
		const header = requireElement<HTMLElement>(target, '.top-bar');
		const back = requireElement<HTMLButtonElement>(header, '.back-btn');
		const brand = requireElement<HTMLAnchorElement>(header, '.brand');
		const trigger = requireElement<HTMLButtonElement>(
			header,
			'[data-hitbox="frequent"][aria-haspopup="dialog"]'
		);

		expect(header.querySelector('.header-nav')).toBeNull();
		expect(header.querySelectorAll('.back-btn')).toHaveLength(1);
		expect(header.querySelector('a[href="/loras"]')).toBeNull();
		expect(header.querySelector('a[href="/settings"]')).toBeNull();
		expect(header.querySelector('.logout')).toBeNull();
		expect(back.tagName).toBe('BUTTON');
		expect(brand.textContent).toBeTruthy();

		const headerStyle = getComputedStyle(header);
		const pad = px(headerStyle.paddingLeft) + px(headerStyle.paddingRight);
		const gap = px(headerStyle.gap);
		const leftGap = px(getComputedStyle(requireElement(header, '.top-left')).gap);
		expect(px(getComputedStyle(brand).minWidth)).toBe(0);
		expect(minUsedWidth(trigger)).toBe(HITBOX_FREQUENT_PX);
		const used =
			pad +
			minUsedWidth(back) +
			leftGap +
			px(getComputedStyle(brand).minWidth) +
			gap +
			minUsedWidth(trigger);
		expect(used).toBeLessThanOrEqual(VIEWPORT_PX);
	});

	it('keeps library back on home and uses the settings home link elsewhere', async () => {
		const home = await renderLayout('/');
		const homeBack = requireElement<HTMLButtonElement>(home, '.back-btn');
		expect(homeBack.tagName).toBe('BUTTON');
		expect(homeBack.getAttribute('aria-label')).toBe('Back');
		if (mounted) await unmount(mounted);
		mounted = undefined;
		document.body.replaceChildren();

		const voices = await renderLayout('/loras');
		expect(voices.querySelector('.back-btn')).toBeNull();
		expect(voices.querySelector('.brand')).not.toBeNull();
		if (mounted) await unmount(mounted);
		mounted = undefined;
		document.body.replaceChildren();

		const settings = await renderLayout('/settings');
		const settingsBack = requireElement<HTMLAnchorElement>(settings, '.back-btn');
		expect(settingsBack.tagName).toBe('A');
		expect(settingsBack.getAttribute('href')).toBe('/');
		expect(settingsBack.getAttribute('aria-label')).toBe('Back to home');
		expect(settings.querySelectorAll('.back-btn')).toHaveLength(1);
	});
});
