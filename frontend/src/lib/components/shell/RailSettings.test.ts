import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RAIL_SETTINGS_OPEN_STORAGE_KEY } from '$lib/constants';
import { currentUser } from '$lib/stores/auth';

// A genuine `$state` proxy, not a plain object: Rail.svelte (and the real
// root layout) never remounts across a route change, so the fix this file
// pins — the disclosure staying closed while the viewer browses Settings —
// only shows up if `page.url` actually notifies Svelte's reactivity when it
// changes under an already-mounted instance, the same way SvelteKit's real
// `$app/state` does. `stateProxy` lives in reactive-fixtures.svelte.ts
// because runes only compile in a `.svelte.ts` module (see that file).
vi.mock('$app/state', async () => {
	const { stateProxy } = await import('../../../tests/reactive-fixtures.svelte');
	return { page: stateProxy({ url: new URL('https://songmaker.test/') }) };
});

import { page } from '$app/state';
import RailSettings from './RailSettings.svelte';

// SvelteKit's real `page.url` type brands `pathname` to a union of known
// routes; the mock only needs a plain, freely-assignable URL.
const pageState = page as unknown as { url: URL };

const ADMIN = { id: 'u1', username: 'felix', role: 'admin' as const };
const USER = { id: 'u2', username: 'jane', role: 'user' as const };

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RailSettings, { target, props: {} });
	await tick();
	return target;
}

/** Flushes a `page.url` mutation through to the component, the same way
 * layout.test.ts flushes a state change that a mocked effect reacts to. */
async function flush(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
}

function itemLabels(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll<HTMLAnchorElement>('.row-sub')).map(
		(link) => link.textContent?.trim() ?? ''
	);
}

beforeEach(() => {
	localStorage.clear();
	pageState.url = new URL('https://songmaker.test/');
	currentUser.set(ADMIN);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	currentUser.set(null);
});

describe('RailSettings', () => {
	it('starts collapsed off a settings route and expands on click', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');

		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(itemLabels(target)).toEqual([
			'Generation',
			'Playback',
			'Voices',
			'Account',
			'Admin',
			'Cleanup',
			'Legal'
		]);
	});

	it('opens automatically and marks the active section when landing on a settings route', async () => {
		pageState.url = new URL('https://songmaker.test/settings/voices');
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('true');

		const active = requireElement<HTMLAnchorElement>(target, '.row-active');
		expect(active.textContent?.trim()).toBe('Voices');
		expect(active.getAttribute('href')).toBe('/settings/voices');
	});

	it('omits admin-only sections for a non-admin', async () => {
		currentUser.set(USER);
		pageState.url = new URL('https://songmaker.test/settings/generation');
		const target = await render();
		expect(itemLabels(target)).toEqual(['Generation', 'Playback', 'Voices', 'Account', 'Legal']);
	});

	it('remembers an open disclosure across a fresh mount via localStorage', async () => {
		const first = await render();
		requireElement<HTMLButtonElement>(first, 'button.disclose').click();
		await tick();
		const firstInstance = mounted;
		if (firstInstance) await unmount(firstInstance);
		mounted = undefined;
		document.body.replaceChildren();

		expect(localStorage.getItem(RAIL_SETTINGS_OPEN_STORAGE_KEY)).toBe('true');

		const second = await render();
		expect(
			requireElement<HTMLButtonElement>(second, 'button.disclose').getAttribute('aria-expanded')
		).toBe('true');
	});

	it('still renders and toggles when localStorage throws', async () => {
		const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked in private mode');
		});
		const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked in private mode');
		});

		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');

		getItem.mockRestore();
		setItem.mockRestore();
	});

	// Regression coverage for the reviewer's throwaway probe: the force-open
	// effect used to read `open` as well as write it, so it re-ran on every
	// close and immediately reopened itself — a viewer could never collapse
	// the disclosure while browsing Settings.
	it('stays closed after the viewer collapses it while already on a settings route', async () => {
		pageState.url = new URL('https://songmaker.test/settings/generation');
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('true');

		toggle.click();
		await flush();

		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		const panel = requireElement<HTMLDivElement>(target, '#rail-settings-group');
		expect(panel.inert).toBe(true);
	});

	it('reopens on a genuine entry into Settings, not on every re-render while already inside it', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');

		pageState.url = new URL('https://songmaker.test/settings/voices');
		await flush();

		expect(toggle.getAttribute('aria-expanded')).toBe('true');
	});
});
