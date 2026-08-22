import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

let afterNavigateCb: (() => void) | undefined;

vi.mock('$app/navigation', () => ({
	afterNavigate: (cb: () => void) => {
		afterNavigateCb = cb;
	}
}));

import UserMenu from './UserMenu.svelte';

let mounted: ReturnType<typeof mount> | undefined;
const onlogout = vi.fn();

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function renderMenu(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(UserMenu, { target, props: { username: 'felix', onlogout } });
	await tick();
	return target;
}

async function openMenu(target: HTMLElement): Promise<HTMLDivElement> {
	requireElement<HTMLButtonElement>(target, '[aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLDivElement>(document.body, '.account-menu');
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	afterNavigateCb = undefined;
	onlogout.mockReset();
});

describe('UserMenu', () => {
	it('shows the username and no menu until opened', async () => {
		const target = await renderMenu();
		expect(target.textContent).toContain('felix');
		expect(document.body.querySelector('.account-menu')).toBeNull();
	});

	it('opens a menu with theme, voices, and logout', async () => {
		const target = await renderMenu();
		const menu = await openMenu(target);
		expect(menu.querySelector('a[href="/loras"]')).not.toBeNull();
		expect(menu.querySelector('.logout')).not.toBeNull();
	});

	it('calls onlogout when Logout is clicked', async () => {
		const target = await renderMenu();
		const menu = await openMenu(target);
		requireElement<HTMLButtonElement>(menu, '.logout').click();
		expect(onlogout).toHaveBeenCalledTimes(1);
	});

	it('closes on Escape and restores focus to the trigger', async () => {
		const target = await renderMenu();
		await openMenu(target);
		const trigger = requireElement<HTMLButtonElement>(target, '[aria-haspopup="dialog"]');
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
		await tick();
		expect(document.body.querySelector('.account-menu')).toBeNull();
		await Promise.resolve();
		expect(document.activeElement).toBe(trigger);
	});

	it('closes on navigation', async () => {
		const target = await renderMenu();
		await openMenu(target);
		afterNavigateCb?.();
		await tick();
		expect(document.body.querySelector('.account-menu')).toBeNull();
	});
});
