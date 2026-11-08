import { mount, tick, unmount } from 'svelte';
import { ACCOUNT_MENU_CLOSE_LABEL, ACCOUNT_MENU_LABEL } from '#lib/constants/auth.ts';
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
import { RAIL_SETTINGS_LABEL } from '#lib/constants.ts';
import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
import { currentUser, signOutFailed } from '#lib/stores/auth.ts';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import { pendingDirtyNavigation } from '#lib/stores/navigation.ts';
import { makeAuthUser, makeSong } from '#lib/test-utils/factories.ts';
import { initTheme, theme, themeChoice } from '#lib/stores/ui.ts';
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
// The kit's panel owns these words.
const LOG_OUT_NAME = 'Log out';
const TRIGGER_NAME = `${ACCOUNT_MENU_LABEL} · ${USERNAME}`;

function storeChoice(choice: 'dark' | 'light' | 'system'): void {
	localStorage.setItem('songmaker.theme', choice);
	initTheme();
}

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	storeChoice('dark');
	currentUser.set(makeAuthUser({ username: USERNAME, account_console_url: ACCOUNT_CONSOLE_URL }));
	replaceHistoryEntry('/');
	startFakeRouter();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	vi.mocked(goto).mockReset();
	signOutFailed.set(false);
	currentUser.set(null);
	localStorage.clear();
	discardDraft();
	pendingDirtyNavigation.set(null);
	document.body.replaceChildren();
});

async function renderAccountMenu(onlogout = vi.fn()): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(AccountMenu, {
			target,
			props: { username: USERNAME, accountHref: ACCOUNT_CONSOLE_URL, onlogout }
		})
	);
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

describe('AccountMenu', () => {
	it("shows the viewer's initial on a circle named after the account", async () => {
		const target = await renderAccountMenu();

		expect(getByRoleButton(target, TRIGGER_NAME).textContent?.trim()).toBe('F');
	});

	it('shows the kit panel: the name, Settings, the theme choice, Log out and the legal links', async () => {
		const panel = await openMenu(await renderAccountMenu());

		expect(requireElement(panel, 'a[href="' + ACCOUNT_CONSOLE_URL + '"]').textContent).toContain(
			USERNAME
		);
		getByRoleButton(panel, RAIL_SETTINGS_LABEL);
		getByRoleButton(panel, LOG_OUT_NAME);
		expect(panel.querySelectorAll('input[type="radio"]')).toHaveLength(3);
		expect(
			Array.from(panel.querySelectorAll('nav[aria-label="Legal"] a')).map(
				(link) => link.textContent
			)
		).toEqual(LEGAL_SECTIONS.map((section) => section.label));
	});

	it('opens every legal link in a new tab so the playing song is not left', async () => {
		const panel = await openMenu(await renderAccountMenu());

		const links = Array.from(panel.querySelectorAll('nav[aria-label="Legal"] a'));
		expect(links).toHaveLength(LEGAL_SECTIONS.length);
		for (const link of links) {
			expect(link.getAttribute('target')).toBe('_blank');
			expect(link.getAttribute('rel')).toContain('noopener');
		}
	});

	it("opens the identity provider's account console in a new tab from the name and closes", async () => {
		const target = await renderAccountMenu();
		const panel = await openMenu(target);

		const name = requireElement<HTMLAnchorElement>(panel, `a[href="${ACCOUNT_CONSOLE_URL}"]`);
		name.addEventListener('click', (event) => event.preventDefault());
		name.click();
		await tick();

		expect(name.getAttribute('target')).toBe('_blank');
		expect(name.getAttribute('rel')).toContain('noopener');
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it.each([
		{ pick: 'Light', saved: 'light', shown: 'light' },
		{ pick: 'Follow system', saved: 'system', shown: 'light' },
		{ pick: 'Dark', saved: 'dark', shown: 'dark' }
	])(
		'takes effect at once and saves $saved when $pick is picked',
		async ({ pick, saved, shown }) => {
			storeChoice(saved === 'dark' ? 'light' : 'dark');
			const panel = await openMenu(await renderAccountMenu());

			requireElement<HTMLInputElement>(
				panel,
				`input[type="radio"][value="${pick === 'Follow system' ? 'follow-system' : saved}"]`
			).click();
			await tick();

			expect(get(themeChoice)).toBe(saved);
			expect(get(theme)).toBe(shown);
			expect(updateTheme).toHaveBeenCalledWith(saved);
		}
	);

	it('shows the stored choice as the checked radio', async () => {
		storeChoice('system');
		const panel = await openMenu(await renderAccountMenu());

		expect(requireElement<HTMLInputElement>(panel, 'input[type="radio"]:checked').value).toBe(
			'follow-system'
		);
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

		getByRoleButton(panel, LOG_OUT_NAME).click();

		await vi.waitFor(() => expect(onlogout).toHaveBeenCalledOnce());
	});

	it('asks about an unsaved draft before logging out, and logs out only once that is confirmed', async () => {
		loadSongData(makeSong());
		setDraftLyrics('unsaved edit');
		const onlogout = vi.fn();
		const panel = await openMenu(await renderAccountMenu(onlogout));

		getByRoleButton(panel, LOG_OUT_NAME).click();
		await tick();

		expect(onlogout).not.toHaveBeenCalled();
		const confirmed = get(pendingDirtyNavigation);
		expect(confirmed).not.toBeNull();
		await confirmed?.();
		expect(onlogout).toHaveBeenCalledOnce();
	});

	it('stays open and says so when the server did not confirm the log-out', async () => {
		const target = await renderAccountMenu(vi.fn(() => signOutFailed.set(true)));
		const panel = await openMenu(target);

		getByRoleButton(panel, LOG_OUT_NAME).click();
		await tick();

		expect(target.querySelector('[role="dialog"]')).toBe(panel);
		expect(panel.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			"Couldn't log out. Check your connection and try again."
		);
	});

	it('no longer tells a failed log-out once the menu has closed', async () => {
		const target = await renderAccountMenu(vi.fn(() => signOutFailed.set(true)));
		getByRoleButton(await openMenu(target), LOG_OUT_NAME).click();
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

		expect(document.activeElement).toBe(requireElement(panel, `a[href="${ACCOUNT_CONSOLE_URL}"]`));
	});

	it.each([
		{ way: 'Tab past the last legal link', shiftKey: false },
		{ way: 'Shift+Tab before the name', shiftKey: true }
	])('keeps focus inside: $way wraps around', async ({ shiftKey }) => {
		const panel = await openMenu(await renderAccountMenu());
		const name = requireElement<HTMLElement>(panel, `a[href="${ACCOUNT_CONSOLE_URL}"]`);
		const lastLegal = Array.from(
			panel.querySelectorAll<HTMLElement>('nav[aria-label="Legal"] a')
		).at(-1);
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
