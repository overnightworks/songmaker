// Settings after Keycloak (#1784, picture navigation.html (j) and
// admin-models.html #cleanup): the account circle and its menu on both
// shells, Settings without Account, Legal's old home and Cleanup, Cleanup as
// the Admin page's last tab with its confirmation and empty state, and the two
// old addresses behaving like any unknown one. Both shells drive every cell.
// The retention endpoints are answered with test data: the run deletes takes
// for good and the stack's library must stay as seeded.

import { expect, test, type Locator, type Page } from '@playwright/test';

import {
	ACCOUNT_MENU_LOGOUT_LABEL,
	ADMIN_TABS_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SETTINGS_LABEL,
	SETTINGS_NAV_LABEL,
	THEME_SWITCH_TO_DARK_LABEL
} from '../src/lib/constants';
import {
	accountCircle,
	accountMenu,
	FlowGuard,
	LIBRARY_PATH,
	nameStartingWith,
	shellOf,
	type Shell
} from './helpers';
import { runMarker, seedAccount } from './seed';

const PREVIEW_PATH = '**/api/admin/generation-retention/preview';
const RUN_PATH = '**/api/admin/generation-retention/run';
const ACCOUNT_CONSOLE_PATH = /\/realms\/e2e\/account$/;

function retentionReport(archived: number, deleted: number, dryRun = true) {
	return {
		archived_ids: [],
		deleted_ids: [],
		archived_count: archived,
		deleted_count: deleted,
		retention_days: 30,
		hard_delete_days: 90,
		scheduled_hour_utc: 3,
		dry_run: dryRun
	};
}

async function openAccountMenu(page: Page, shell: Shell): Promise<Locator> {
	// The phone carries the circle on the Library bar; the desktop on every page.
	await page.goto(shell === 'mobile' ? LIBRARY_PATH : '/settings/generation');
	await accountCircle(page).click();
	const menu = accountMenu(page);
	await expect(menu).toBeVisible();
	return menu;
}

test('the account circle opens a menu with the name, Settings, the theme, Sign out and the legal links, on both shells', async ({
	page
}, info) => {
	const shell = shellOf(info);
	const guard = new FlowGuard(page);
	const menu = await openAccountMenu(page, shell);

	const name = menu.getByRole('link', { name: /^\S/ }).first();
	await expect(name).toHaveAttribute('href', ACCOUNT_CONSOLE_PATH);
	await expect(name).toHaveAttribute('target', '_blank');
	await expect(menu.getByRole('button', { name: RAIL_SETTINGS_LABEL, exact: true })).toBeVisible();
	await expect(
		menu.getByRole('button', { name: THEME_SWITCH_TO_DARK_LABEL, exact: true })
	).toBeVisible();
	await expect(
		menu.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL, exact: true })
	).toBeVisible();
	for (const legal of ['Impressum', 'Datenschutz', 'Nutzungsbedingungen']) {
		const link = menu.getByRole('link', { name: legal, exact: true });
		await expect(link).toBeVisible();
		await expect(link).toHaveAttribute('target', '_blank');
		await expect(link).toHaveAttribute('rel', /noopener/);
	}
	// The separator trails its item, so no line of the legal row starts on one:
	// each link stands at the left edge of its own item.
	const items = menu.locator('.legal-item');
	for (let index = 0; index < (await items.count()); index += 1) {
		const item = items.nth(index);
		const itemBox = await item.boundingBox();
		const linkBox = await item.getByRole('link').boundingBox();
		expect(linkBox?.x).toBe(itemBox?.x);
	}
	await expect(menu.getByText('Signed in as')).toHaveCount(0);

	if (shell === 'desktop') {
		const rail = page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		await expect(rail.getByRole('button', { name: /^(Log ?out|Sign out)$/i })).toHaveCount(0);
		await expect(rail.getByRole('link', { name: 'Account', exact: true })).toHaveCount(0);
	}
	guard.assertClean();
});

test('a member sees Generation and Voices in Settings, an admin also Admin, and nobody sees Account, Legal or Cleanup', async ({
	page
}) => {
	// Switching accounts leaves the old page's last request without a session.
	const guard = new FlowGuard(page, { refusalsExpectedOn: [{ path: '/api/', statuses: [401] }] });
	const member = await seedAccount(`e2e-member-${runMarker()}`);
	const adminCookies = await page.context().cookies();

	for (const [cookies, shown, hidden] of [
		[member.cookies, ['Generation', 'Voices'], ['Admin']],
		[adminCookies, ['Generation', 'Voices', 'Admin'], []]
	] as const) {
		await page.context().clearCookies();
		await page.context().addCookies([...cookies]);
		await page.goto('/settings');
		const sections = page.getByRole('navigation', { name: SETTINGS_NAV_LABEL });
		await expect(sections).toBeVisible();
		for (const label of shown) {
			await expect(sections.getByRole('link', { name: nameStartingWith(label) })).toBeVisible();
		}
		for (const label of [...hidden, 'Account', 'Cleanup']) {
			await expect(sections.getByRole('link', { name: nameStartingWith(label) })).toHaveCount(0);
		}
	}
	guard.assertClean();
});

test('Cleanup is the last Admin tab; Run now asks before anything is deleted, and Cancel runs nothing', async ({
	page
}, info) => {
	const shell = shellOf(info);
	const guard = new FlowGuard(page);
	let runs = 0;
	await page.route(PREVIEW_PATH, (route) => route.fulfill({ json: retentionReport(12, 3) }));
	await page.route(RUN_PATH, (route) => {
		runs += 1;
		return route.fulfill({ json: retentionReport(0, 0, false) });
	});

	await page.goto('/settings/users');
	if (shell === 'mobile') {
		const select = page.getByRole('combobox', { name: ADMIN_TABS_LABEL });
		await expect(select.locator('option').last()).toHaveText('Cleanup');
		await select.selectOption({ label: 'Cleanup' });
	} else {
		const tabs = page.locator('.tabs button');
		await expect(tabs.last()).toHaveText('Cleanup');
		await tabs.last().click();
	}

	await expect(page.getByRole('heading', { name: 'Take Retention' })).toBeVisible();
	await expect(page.getByText('Auto · daily 03:00 UTC')).toBeVisible();
	await page.getByRole('button', { name: 'Run now', exact: true }).click();
	await expect(
		page.getByText('Archive 12 takes and permanently delete 3. Deleting cannot be undone.')
	).toBeVisible();
	expect(runs).toBe(0);

	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Run now', exact: true })).toBeVisible();
	expect(runs).toBe(0);

	await page.getByRole('button', { name: 'Run now', exact: true }).click();
	await page.getByRole('button', { name: 'Delete 3', exact: true }).click();
	await expect.poll(() => runs).toBe(1);
	guard.assertClean();
});

test('Cleanup with nothing due says so and offers no buttons', async ({ page }) => {
	const guard = new FlowGuard(page);
	await page.route(PREVIEW_PATH, (route) => route.fulfill({ json: retentionReport(0, 0) }));

	await page.goto('/settings/users?tab=cleanup');

	await expect(page.getByText('Nothing to clean up right now')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Run now', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toHaveCount(0);
	guard.assertClean();
});

test('the old Account and Cleanup addresses behave like any unknown address', async ({ page }) => {
	await page.goto('/settings/never-existed');
	const unknownAnswer = page.getByText('Not Found');
	await expect(unknownAnswer).toBeVisible();

	for (const oldAddress of ['/settings/account', '/settings/cleanup']) {
		await page.goto(oldAddress);
		await expect(page).toHaveURL(new RegExp(`${oldAddress}$`));
		await expect(unknownAnswer).toBeVisible();
		await expect(page.getByRole('heading', { name: /Account|Take Retention/ })).toHaveCount(0);
	}
});
