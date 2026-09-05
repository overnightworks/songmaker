import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RAIL_SETTINGS_OPEN_STORAGE_KEY } from '$lib/constants';
import { currentUser } from '$lib/stores/auth';
import { createComponentMount, requireElement } from './rail-test-fixtures';

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

const { render, cleanup } = createComponentMount(RailSettings);

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
	await cleanup();
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

	it('persists its open state under RAIL_SETTINGS_OPEN_STORAGE_KEY', async () => {
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		expect(localStorage.getItem(RAIL_SETTINGS_OPEN_STORAGE_KEY)).toBe('true');
	});

	it('toggles from its text and caret without navigating away from the current settings page', async () => {
		pageState.url = new URL('https://songmaker.test/settings/users');
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		const title = requireElement<HTMLSpanElement>(toggle, '.group-title');
		const caret = requireElement<SVGElement>(toggle, '.caret');

		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		title.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(pageState.url.pathname).toBe('/settings/users');

		caret.dispatchEvent(new MouseEvent('click', { bubbles: true }));
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(pageState.url.pathname).toBe('/settings/users');
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
