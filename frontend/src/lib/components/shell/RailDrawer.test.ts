import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

let afterNavigateCb: (() => void) | undefined;

vi.mock('$app/navigation', () => ({
	afterNavigate: (cb: () => void) => {
		afterNavigateCb = cb;
	}
}));

import { RAIL_DRAWER_LABEL } from '$lib/constants';
import {
	closeSidebar,
	railWidth,
	RAIL_WIDTH_STORAGE_KEY,
	sidebarOpen,
	toggleSidebar
} from '$lib/stores/ui';
import RailDrawer from './RailDrawer.svelte';
import railDrawerSource from './RailDrawer.svelte?raw';

let mounted: ReturnType<typeof mount> | undefined;

const children = createRawSnippet(() => ({
	render: () =>
		`<div><input type="search" aria-label="Search or go to…"><a href="/">Library</a><button>Settings</button></div>`
}));

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	closeSidebar();
	railWidth.set(264);
	localStorage.removeItem(RAIL_WIDTH_STORAGE_KEY);
	afterNavigateCb = undefined;
});

describe('RailDrawer', () => {
	it('renders nothing while closed and the panel once opened', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		await tick();
		expect(document.body.querySelector('.drawer-panel')).toBeNull();

		toggleSidebar();
		await tick();
		expect(get(sidebarOpen)).toBe(true);
		const panel = requireElement(document.body, '.drawer-panel');
		expect(panel.textContent).toContain('Library');
		// The drawer is one of several overlays the shell can open, so a flow
		// scopes to it by name rather than by "the open dialog".
		expect(panel.getAttribute('aria-label')).toBe(RAIL_DRAWER_LABEL);
	});

	it('uses the remembered rail width but never exceeds 84vw', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		railWidth.set(360);
		toggleSidebar();
		await tick();

		const panel = requireElement<HTMLElement>(document.body, '.drawer-panel');
		expect(panel.style.getPropertyValue('--rail-width')).toBe('360px');
		expect(railDrawerSource).toContain('width: min(var(--rail-width), 84vw)');
	});

	it('closes on backdrop click and traps focus inside', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		toggleSidebar();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.drawer-backdrop').click();
		await tick();
		expect(document.body.querySelector('.drawer-panel')).toBeNull();
	});

	it('closes on Escape', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		toggleSidebar();
		await tick();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
		await tick();
		expect(document.body.querySelector('.drawer-panel')).toBeNull();
	});

	it('keeps the drawer open when its search field consumes Escape', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		toggleSidebar();
		await tick();
		const search = requireElement<HTMLInputElement>(document.body, 'input[type="search"]');
		search.addEventListener('keydown', (event) => event.preventDefault());

		search.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await tick();

		expect(document.body.querySelector('.drawer-panel')).not.toBeNull();
	});

	it('wraps Tab from the last control back to the rail search field', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		toggleSidebar();
		await tick();
		const search = requireElement<HTMLInputElement>(document.body, 'input[type="search"]');
		const last = requireElement<HTMLButtonElement>(document.body, '.drawer-panel button');
		last.focus();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }));

		expect(document.activeElement).toBe(search);
	});

	it('closes after navigation', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(RailDrawer, { target, props: { children } });
		toggleSidebar();
		await tick();
		afterNavigateCb?.();
		await tick();
		expect(document.body.querySelector('.drawer-panel')).toBeNull();
	});
});
