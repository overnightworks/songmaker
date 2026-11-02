import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);

vi.mock('#lib/api/settings.ts', () => ({
	fetchTheme: vi.fn(),
	updateTheme: vi.fn().mockResolvedValue({ theme: 'light' })
}));

import { goto } from '$app/navigation';
import { updateTheme } from '#lib/api/settings.ts';
import {
	ACCOUNT_MENU_CLOSE_LABEL,
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	RAIL_SETTINGS_LABEL,
	THEME_SWITCH_TO_DARK_LABEL,
	THEME_SWITCH_TO_LIGHT_LABEL
} from '#lib/constants.ts';
import { currentUser, signOutFailed } from '#lib/stores/auth.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';
import { theme } from '#lib/stores/ui.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import {
	describeBackClosesOverlay,
	plannedHistoryIndex,
	replaceHistoryEntry
} from '#lib/test-utils/library-history.ts';
import AccountMenu from './AccountMenu.svelte';

const USERNAME = 'felix';
const ACCOUNT_CONSOLE_URL = 'https://login.test/realms/songmaker/account';
const TRIGGER_NAME = `${ACCOUNT_MENU_LABEL} · ${USERNAME}`;

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	theme.set('dark');
	currentUser.set(makeAuthUser({ username: USERNAME, account_console_url: ACCOUNT_CONSOLE_URL }));
	replaceHistoryEntry('/');
	startFakeRouter();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	vi.mocked(goto).mockReset();
	signOutFailed.set(false);
	currentUser.set(null);
	document.body.replaceChildren();
});

async function renderAccountMenu(onlogout = vi.fn()): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(AccountMenu, { target, props: { username: USERNAME, onlogout } }));
	await tick();
	return target;
}

async function openMenu(target: HTMLElement): Promise<HTMLElement> {
	getByRoleButton(target, TRIGGER_NAME).click();
	await tick();
	await tick();
	const panel = target.querySelector<HTMLElement>('[role="dialog"]');
	if (!panel) throw new Error('Expected the account menu to open');
	return panel;
}

function requireElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
	const found = root.querySelector<T>(selector);
	if (!found) throw new Error(`Expected ${selector}`);
	return found;
}

function rowTexts(panel: HTMLElement): string[] {
	return Array.from(panel.children).map(
		(row) => row.textContent?.replace(/\s+/g, ' ').trim() ?? ''
	);
}

describe('AccountMenu', () => {
	it("shows the viewer's initial on a circle named after the account", async () => {
		const target = await renderAccountMenu();

		expect(getByRoleButton(target, TRIGGER_NAME).textContent?.trim()).toBe('F');
	});

	it('lists the name, Settings, the theme switch, Sign out, then one quiet row of legal links', async () => {
		const panel = await openMenu(await renderAccountMenu());

		expect(rowTexts(panel)).toEqual([
			USERNAME,
			RAIL_SETTINGS_LABEL,
			THEME_SWITCH_TO_LIGHT_LABEL,
			ACCOUNT_MENU_LOGOUT_LABEL,
			'ImpressumDatenschutzNutzungsbedingungen'
		]);
		expect(ACCOUNT_MENU_LOGOUT_LABEL).toBe('Sign out');
	});

	it('opens every legal link in a new tab so the playing song is not left', async () => {
		const panel = await openMenu(await renderAccountMenu());

		const links = Array.from(panel.querySelectorAll('a.legal-link'));
		expect(links).toHaveLength(3);
		for (const link of links) {
			expect(link.getAttribute('target')).toBe('_blank');
			expect(link.getAttribute('rel')).toContain('noopener');
		}
	});

	it("opens the identity provider's account console in a new tab from the name", async () => {
		const panel = await openMenu(await renderAccountMenu());

		const name = requireElement<HTMLAnchorElement>(panel, 'a.account-name');

		expect(name.getAttribute('href')).toBe(ACCOUNT_CONSOLE_URL);
		expect(name.getAttribute('target')).toBe('_blank');
		expect(name.getAttribute('rel')).toContain('noopener');
		expect(name.querySelector('svg')).not.toBeNull();
	});

	it('shows the name as plain text when the server names no account console', async () => {
		currentUser.set(makeAuthUser({ username: USERNAME, account_console_url: null }));
		const panel = await openMenu(await renderAccountMenu());

		expect(panel.querySelector('a.account-name')).toBeNull();
		expect(rowTexts(panel)[0]).toBe(USERNAME);
	});

	it('switches the theme and then offers the way back', async () => {
		const panel = await openMenu(await renderAccountMenu());

		getByRoleButton(panel, THEME_SWITCH_TO_LIGHT_LABEL).click();
		await tick();

		expect(get(theme)).toBe('light');
		expect(getByRoleButton(panel, THEME_SWITCH_TO_DARK_LABEL)).toBeDefined();
		expect(updateTheme).toHaveBeenCalledWith('light');
	});

	it('opens the Settings list and closes', async () => {
		const target = await renderAccountMenu();
		const panel = await openMenu(target);

		getByRoleButton(panel, RAIL_SETTINGS_LABEL).click();
		await tick();

		await vi.waitFor(() => expect(goto).toHaveBeenCalledWith('/settings'));
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('only closes when Settings is already the page on screen, adding no history entry', async () => {
		replaceHistoryEntry('/settings');
		startFakeRouter();
		const target = await renderAccountMenu();
		const panel = await openMenu(target);

		getByRoleButton(panel, RAIL_SETTINGS_LABEL).click();
		await tick();
		await Promise.resolve();

		expect(target.querySelector('[role="dialog"]')).toBeNull();
		expect(goto).not.toHaveBeenCalled();
		expect(location.pathname).toBe('/settings');
	});

	it('logs out through the shell', async () => {
		const onlogout = vi.fn();
		const panel = await openMenu(await renderAccountMenu(onlogout));

		getByRoleButton(panel, ACCOUNT_MENU_LOGOUT_LABEL).click();

		await vi.waitFor(() => expect(onlogout).toHaveBeenCalledOnce());
	});

	it('stays open and says so when the server did not confirm the sign-out', async () => {
		const target = await renderAccountMenu(vi.fn(() => signOutFailed.set(true)));
		const panel = await openMenu(target);

		getByRoleButton(panel, ACCOUNT_MENU_LOGOUT_LABEL).click();
		await tick();

		expect(target.querySelector('[role="dialog"]')).toBe(panel);
		expect(panel.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			"Couldn't sign out. Check your connection and try again."
		);
	});

	it('no longer tells a failed sign-out once the menu has closed', async () => {
		const target = await renderAccountMenu(vi.fn(() => signOutFailed.set(true)));
		getByRoleButton(await openMenu(target), ACCOUNT_MENU_LOGOUT_LABEL).click();
		await tick();

		getByRoleButton(target, TRIGGER_NAME).click();
		await tick();
		const reopened = await openMenu(target);

		expect(reopened.querySelector('[role="alert"]')).toBeNull();
	});
});

describe('AccountMenu focus', () => {
	function press(key: string, shiftKey = false): void {
		window.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
	}

	async function focusSettles(): Promise<void> {
		await Promise.resolve();
		await tick();
	}

	it('moves focus to the name, its first item, when it opens', async () => {
		const panel = await openMenu(await renderAccountMenu());

		expect(document.activeElement).toBe(requireElement(panel, 'a.account-name'));
	});

	it.each([
		{ way: 'Tab past the last legal link', shiftKey: false },
		{ way: 'Shift+Tab before the name', shiftKey: true }
	])('keeps focus inside: $way wraps around', async ({ shiftKey }) => {
		const panel = await openMenu(await renderAccountMenu());
		const name = requireElement<HTMLElement>(panel, 'a.account-name');
		const lastLegal = Array.from(panel.querySelectorAll<HTMLElement>('a.legal-link')).at(-1);
		(shiftKey ? name : lastLegal)?.focus();

		press('Tab', shiftKey);

		expect(document.activeElement).toBe(shiftKey ? lastLegal : name);
	});

	it.each([
		{ way: 'Escape', close: () => press('Escape') },
		{
			way: 'a tap outside',
			close: (target: HTMLElement) => getByRoleButton(target, ACCOUNT_MENU_CLOSE_LABEL).click()
		},
		{
			way: 'the circle again',
			close: (target: HTMLElement) => getByRoleButton(target, TRIGGER_NAME).click()
		}
	])('closing it by $way hands focus back to the circle', async ({ close }) => {
		const target = await renderAccountMenu();
		await openMenu(target);

		close(target);
		await focusSettles();

		expect(target.querySelector('[role="dialog"]')).toBeNull();
		expect(document.activeElement).toBe(getByRoleButton(target, TRIGGER_NAME));
	});
});

let settingsSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the account menu',
	render: async () => {
		settingsSawHistoryAt = undefined;
		vi.mocked(goto).mockImplementation(async () => {
			settingsSawHistoryAt = plannedHistoryIndex();
		});
		return renderAccountMenu();
	},
	open: (target) => getByRoleButton(target, TRIGGER_NAME).click(),
	isShown: (target) => target.querySelector('[role="dialog"]') !== null,
	closeWays: [
		{
			way: 'a tap outside',
			close: (target) => getByRoleButton(target, ACCOUNT_MENU_CLOSE_LABEL).click()
		},
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		},
		{
			way: 'choosing Settings',
			close: (target) => getByRoleButton(target, RAIL_SETTINGS_LABEL).click(),
			actionSawHistoryAt: () => settingsSawHistoryAt
		}
	]
});
