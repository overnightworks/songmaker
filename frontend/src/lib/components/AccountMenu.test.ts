import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

import { goto } from '$app/navigation';
import {
	ACCOUNT_MENU_CLOSE_LABEL,
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	ACCOUNT_MENU_SIGNED_IN_PREFIX,
	RAIL_SETTINGS_LABEL,
	THEME_SWITCH_TO_DARK_LABEL,
	THEME_SWITCH_TO_LIGHT_LABEL
} from '$lib/constants';
import { theme } from '$lib/stores/ui';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { describeBackClosesOverlay, plannedHistoryIndex } from '$lib/test-utils/library-history';
import AccountMenu from './AccountMenu.svelte';

const USERNAME = 'felix';
const TRIGGER_NAME = `${ACCOUNT_MENU_LABEL} · ${USERNAME}`;

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	theme.set('dark');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	vi.mocked(goto).mockReset();
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

	it('names who is signed in, then Settings, the theme switch, and Log out last', async () => {
		const panel = await openMenu(await renderAccountMenu());

		expect(rowTexts(panel)).toEqual([
			`${ACCOUNT_MENU_SIGNED_IN_PREFIX} ${USERNAME}`,
			RAIL_SETTINGS_LABEL,
			THEME_SWITCH_TO_LIGHT_LABEL,
			ACCOUNT_MENU_LOGOUT_LABEL
		]);
	});

	it('switches the theme and then offers the way back', async () => {
		const panel = await openMenu(await renderAccountMenu());

		getByRoleButton(panel, THEME_SWITCH_TO_LIGHT_LABEL).click();
		await tick();

		expect(get(theme)).toBe('light');
		expect(getByRoleButton(panel, THEME_SWITCH_TO_DARK_LABEL)).toBeDefined();
	});

	it('opens the Settings list and closes', async () => {
		const target = await renderAccountMenu();
		const panel = await openMenu(target);

		getByRoleButton(panel, RAIL_SETTINGS_LABEL).click();
		await tick();

		await vi.waitFor(() => expect(goto).toHaveBeenCalledWith('/settings'));
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('logs out through the shell', async () => {
		const onlogout = vi.fn();
		const panel = await openMenu(await renderAccountMenu(onlogout));

		getByRoleButton(panel, ACCOUNT_MENU_LOGOUT_LABEL).click();

		expect(onlogout).toHaveBeenCalledOnce();
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

	it('moves focus to Settings, its first item, when it opens', async () => {
		const panel = await openMenu(await renderAccountMenu());

		expect(document.activeElement).toBe(getByRoleButton(panel, RAIL_SETTINGS_LABEL));
	});

	it.each([
		{
			from: ACCOUNT_MENU_LOGOUT_LABEL,
			shiftKey: false,
			to: RAIL_SETTINGS_LABEL,
			way: 'Tab past Log out'
		},
		{
			from: RAIL_SETTINGS_LABEL,
			shiftKey: true,
			to: ACCOUNT_MENU_LOGOUT_LABEL,
			way: 'Shift+Tab before Settings'
		}
	])('keeps focus inside: $way wraps to $to', async ({ from, shiftKey, to }) => {
		const panel = await openMenu(await renderAccountMenu());
		getByRoleButton(panel, from).focus();

		press('Tab', shiftKey);

		expect(document.activeElement).toBe(getByRoleButton(panel, to));
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
