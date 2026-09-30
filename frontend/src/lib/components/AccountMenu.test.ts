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

async function renderMenu(onlogout = vi.fn()): Promise<HTMLElement> {
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
		const target = await renderMenu();

		expect(getByRoleButton(target, TRIGGER_NAME).textContent?.trim()).toBe('F');
	});

	it('names who is signed in, then Settings, the theme switch, and Log out last', async () => {
		const panel = await openMenu(await renderMenu());

		expect(rowTexts(panel)).toEqual([
			`${ACCOUNT_MENU_SIGNED_IN_PREFIX} ${USERNAME}`,
			RAIL_SETTINGS_LABEL,
			THEME_SWITCH_TO_LIGHT_LABEL,
			ACCOUNT_MENU_LOGOUT_LABEL
		]);
	});

	it('switches the theme and then offers the way back', async () => {
		const panel = await openMenu(await renderMenu());

		getByRoleButton(panel, THEME_SWITCH_TO_LIGHT_LABEL).click();
		await tick();

		expect(get(theme)).toBe('light');
		expect(getByRoleButton(panel, THEME_SWITCH_TO_DARK_LABEL)).toBeDefined();
	});

	it('opens the Settings list and closes', async () => {
		const target = await renderMenu();
		const panel = await openMenu(target);

		getByRoleButton(panel, RAIL_SETTINGS_LABEL).click();
		await tick();

		expect(goto).toHaveBeenCalledWith('/settings');
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('logs out through the shell', async () => {
		const onlogout = vi.fn();
		const panel = await openMenu(await renderMenu(onlogout));

		getByRoleButton(panel, ACCOUNT_MENU_LOGOUT_LABEL).click();

		expect(onlogout).toHaveBeenCalledOnce();
	});
});

let settingsSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the account menu',
	render: async () => {
		vi.mocked(goto).mockImplementation(async () => {
			settingsSawHistoryAt = plannedHistoryIndex();
		});
		return renderMenu();
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
