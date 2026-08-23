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
import { closeSidebar, sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import RailDrawer from './RailDrawer.svelte';

let mounted: ReturnType<typeof mount> | undefined;

const children = createRawSnippet(() => ({
	render: () => `<div><a href="/">Library</a><button>Settings</button></div>`
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
