import { readFileSync } from 'node:fs';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA, HITBOX_FREQUENT_PX, librarySharesStatusLabel } from '$lib/constants';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';
import { resetSharesForTests } from '$lib/stores/shares';
import HeaderMenu from './HeaderMenu.svelte';

const headerMenuSource = readFileSync('src/lib/components/HeaderMenu.svelte', 'utf8');

const fetchShares = vi.fn();
const persistLibraryHistory = vi.fn();

vi.mock('$lib/api/library', () => ({
	fetchShares: (...args: unknown[]) => fetchShares(...args)
}));
vi.mock('$lib/stores/navigation', () => ({
	persistLibraryHistory: (...args: unknown[]) => persistLibraryHistory(...args),
	isLibraryWorkspacePath: () => true
}));

let afterNavigateCb: (() => void) | undefined;

vi.mock('$app/navigation', () => ({
	goto: vi.fn(),
	afterNavigate: (cb: () => void) => {
		afterNavigateCb = cb;
	}
}));

let mounted: ReturnType<typeof mount> | undefined;
const onlogout = vi.fn();

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

function resolvePx(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	const parsed = Number.parseFloat(resolved);
	return Number.isFinite(parsed) ? parsed : 0;
}

function cssBlock(selector: string): string {
	const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = headerMenuSource.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
	if (!match?.[1]) throw new Error(`Expected ${selector} CSS`);
	return match[1];
}

async function renderMenu(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(HeaderMenu, {
		target,
		props: { username: 'felix', onlogout }
	});
	await tick();
	return target;
}

async function openMenu(target: HTMLElement): Promise<HTMLDivElement> {
	requireElement<HTMLButtonElement>(target, '[aria-haspopup="dialog"]').click();
	await tick();
	await Promise.resolve();
	return requireElement<HTMLDivElement>(document, '[role="dialog"]');
}

beforeEach(() => {
	afterNavigateCb = undefined;
	onlogout.mockReset();
	persistLibraryHistory.mockReset();
	fetchShares.mockReset();
	fetchShares.mockResolvedValue({
		items: [],
		total: 4,
		offset: 0,
		limit: 1,
		has_more: false
	});
	resetSharesForTests();
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
	resetSharesForTests();
	vi.unstubAllGlobals();
});

describe('HeaderMenu', () => {
	it('shows Shared · N outside the overflow on compact and wide layouts', async () => {
		const compact = await renderMenu(true);
		await Promise.resolve();
		await tick();
		const compactStatus = requireElement<HTMLButtonElement>(compact, '.shares-status');
		expect(compactStatus.textContent).toBe(librarySharesStatusLabel(4));
		expect(compact.querySelector('[aria-haspopup="dialog"]')).not.toBeNull();
		expect(compact.querySelector('[role="dialog"]')).toBeNull();

		await unmount(mounted);
		mounted = undefined;
		document.body.replaceChildren();
		const wide = await renderMenu(false);
		await Promise.resolve();
		await tick();
		expect(requireElement<HTMLButtonElement>(wide, '.shares-status').textContent).toBe(
			librarySharesStatusLabel(4)
		);
		expect(wide.querySelector('.header-nav')).not.toBeNull();
	});

	it('lets the Shared chip shrink with ellipsis outside the overflow menu', async () => {
		const target = await renderMenu(true);
		await Promise.resolve();
		await tick();
		const tools = requireElement<HTMLDivElement>(target, '.header-tools');
		const chip = requireElement<HTMLButtonElement>(tools, '.shares-status');
		const trigger = requireElement<HTMLButtonElement>(tools, '[aria-haspopup="dialog"]');
		const toolsCss = cssBlock('.header-tools');
		const chipCss = cssBlock('.shares-status');
		expect(toolsCss).toContain('min-width: 0');
		expect(toolsCss).not.toContain('flex-shrink: 0');
		expect(chipCss).toContain('min-width: 0');
		expect(chipCss).toContain('overflow: hidden');
		expect(chipCss).toContain('text-overflow: ellipsis');
		expect(tools.contains(trigger)).toBe(true);
		expect(chip.contains(trigger)).toBe(false);
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('shows one overflow trigger on compact viewports instead of inline nav', async () => {
		const target = await renderMenu(true);
		const trigger = requireElement<HTMLButtonElement>(
			target,
			'[data-hitbox="frequent"][aria-haspopup="dialog"]'
		);
		expect(trigger.getAttribute('aria-label')).toBe('Account menu');
		expect(target.querySelector('.header-nav')).toBeNull();
		expect(target.querySelector('a[href="/loras"]')).toBeNull();
		expect(resolvePx(getComputedStyle(trigger).minWidth)).toBe(HITBOX_FREQUENT_PX);
	});

	it('keeps the same account actions inline on a wide fine pointer', async () => {
		const target = await renderMenu(false);
		expect(target.querySelector('[aria-haspopup="dialog"]')).toBeNull();
		const nav = requireElement<HTMLElement>(target, '.header-nav');
		expect(nav.textContent).toContain('felix');
		expect(nav.querySelector('a[href="/loras"]')?.textContent).toBe('Voices');
		expect(nav.querySelector('a[href="/settings"]')?.textContent).toBe('Settings');
		expect(nav.querySelector('.logout')?.textContent).toBe('Logout');
		expect(nav.querySelector('[aria-label="Toggle theme"]')).not.toBeNull();
	});

	it('moves focus into the menu and traps Tab in both directions', async () => {
		const target = await renderMenu(true);
		const dialog = await openMenu(target);
		const focusable = Array.from(
			dialog.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')
		);
		const first = focusable[0];
		const last = focusable.at(-1);
		if (!first || !last) throw new Error('Expected account menu actions');

		expect(document.activeElement).toBe(first);

		last.focus();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
		expect(document.activeElement).toBe(first);

		first.focus();
		window.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })
		);
		expect(document.activeElement).toBe(last);
	});

	it('closes on Escape and restores focus to the trigger', async () => {
		const target = await renderMenu(true);
		const trigger = requireElement<HTMLButtonElement>(target, '[aria-haspopup="dialog"]');
		await openMenu(target);

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		await Promise.resolve();

		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(document.activeElement).toBe(trigger);
	});

	it('closes on an outside tap and on a route change', async () => {
		const target = await renderMenu(true);
		const trigger = requireElement<HTMLButtonElement>(target, '[aria-haspopup="dialog"]');
		const dialog = await openMenu(target);

		expect(dialog.textContent).toContain('felix');
		expect(dialog.querySelector('a[href="/loras"]')?.textContent).toBe('Voices');
		expect(dialog.querySelector('a[href="/settings"]')?.textContent).toBe('Settings');
		expect(dialog.querySelector('.logout')?.textContent).toBe('Logout');
		expect(dialog.querySelector('[aria-label="Toggle theme"]')).not.toBeNull();

		requireElement<HTMLButtonElement>(document, '.menu-backdrop').click();
		await tick();
		await Promise.resolve();
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(document.activeElement).toBe(trigger);

		await openMenu(target);
		afterNavigateCb?.();
		await tick();
		await Promise.resolve();
		expect(document.querySelector('[role="dialog"]')).toBeNull();
		expect(document.activeElement).not.toBe(trigger);
	});
});
