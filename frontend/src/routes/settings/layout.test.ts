import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA, SETTINGS_NAV_LABEL } from '$lib/constants';
import { COMPACT_SELECT_CLASS } from '$lib/styles/compact-ui';
import { currentUser } from '$lib/stores/auth';

const { pageState, goto } = vi.hoisted(() => ({
	pageState: { url: new URL('https://songmaker.test/settings/generation') },
	goto: vi.fn()
}));

vi.mock('$app/state', () => ({
	page: pageState
}));
vi.mock('$app/navigation', () => ({
	goto
}));

import SettingsLayout from './+layout.svelte';

const VIEWPORT_PX = 320;
const ADMIN = { id: 'u1', username: 'felix', role: 'admin' as const };
const USER = { id: 'u2', username: 'jane', role: 'user' as const };
const ADMIN_SECTIONS = ['Generation', 'Playback', 'Voices', 'Account', 'Admin', 'Cleanup', 'Legal'];
const USER_SECTIONS = ['Generation', 'Playback', 'Voices', 'Account', 'Legal'];

let mounted: ReturnType<typeof mount> | undefined;
const children = createRawSnippet(() => ({
	render: () => `<div data-settings-child="true"></div>`
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

function optionLabels(select: HTMLSelectElement): string[] {
	return Array.from(select.options).map((option) => option.textContent ?? '');
}

function px(value: string): number {
	const parsed = Number.parseFloat(value);
	return Number.isFinite(parsed) ? parsed : 0;
}

async function renderLayout(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	target.style.width = `${VIEWPORT_PX}px`;
	document.body.append(target);
	mounted = mount(SettingsLayout, { target, props: { children } });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

beforeEach(() => {
	goto.mockReset();
	pageState.url = new URL('https://songmaker.test/settings/generation');
	currentUser.set(ADMIN);
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: VIEWPORT_PX });
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	currentUser.set(null);
	vi.unstubAllGlobals();
});

describe('settings layout', () => {
	it('keeps the section selector inside 320px with every visible section', async () => {
		const target = await renderLayout(true);
		const select = requireElement<HTMLSelectElement>(
			target,
			`select[aria-label="${SETTINGS_NAV_LABEL}"]`
		);
		const sidebar = requireElement<HTMLElement>(target, '.settings-sidebar');
		const style = getComputedStyle(select);

		expect(target.querySelector('.nav-items')).toBeNull();
		expect(target.querySelector('.nav-link')).toBeNull();
		expect(optionLabels(select)).toEqual(ADMIN_SECTIONS);
		expect(select.value).toBe('/settings/generation');
		expect(select.classList.contains(COMPACT_SELECT_CLASS)).toBe(true);
		expect(style.width).toBe('100%');
		expect(style.maxWidth).toBe('100%');
		expect(style.minWidth === '0px' || style.minWidth === '0').toBe(true);

		const used =
			px(getComputedStyle(sidebar).paddingLeft) + px(getComputedStyle(sidebar).paddingRight);
		expect(used).toBeLessThanOrEqual(VIEWPORT_PX);
	});

	it('omits admin-only sections for a non-admin', async () => {
		currentUser.set(USER);
		const target = await renderLayout(true);
		const select = requireElement<HTMLSelectElement>(
			target,
			`select[aria-label="${SETTINGS_NAV_LABEL}"]`
		);
		expect(optionLabels(select)).toEqual(USER_SECTIONS);
	});

	it('navigates when the compact selector changes', async () => {
		const target = await renderLayout(true);
		const select = requireElement<HTMLSelectElement>(
			target,
			`select[aria-label="${SETTINGS_NAV_LABEL}"]`
		);
		select.value = '/settings/account';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(goto).toHaveBeenCalledWith('/settings/account');
	});

	it('shows the desktop link list instead of a selector', async () => {
		const target = await renderLayout(false);
		expect(target.querySelector(`select[aria-label="${SETTINGS_NAV_LABEL}"]`)).toBeNull();
		const links = Array.from(target.querySelectorAll<HTMLAnchorElement>('.nav-link'));
		expect(links.map((link) => link.textContent?.trim())).toEqual(ADMIN_SECTIONS);
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/settings/generation',
			'/settings/playback',
			'/loras',
			'/settings/account',
			'/settings/users',
			'/settings/cleanup',
			'/settings/legal'
		]);
		expect(target.querySelector('.nav-link.active')?.getAttribute('href')).toBe(
			'/settings/generation'
		);
	});
});
