// The Settings list on the phone (account_rule_3 and
// 1354_rule_28 in docs/navigation.md): the bottom tabs carry no settings
// pages, so on the phone `/settings` is itself the list, a row opens its
// page, and Back returns to the list. The desktop rail carries the sections,
// so there `/settings` keeps redirecting into the first one. The run's
// session is the stack's admin, so Admin is listed.

import { expect, test, type Locator, type Page } from './coverage-test';
import { words } from '../src/lib/words/en';
import { ONLY_IN_SHELL, workspace } from './helpers';

const ADMIN_SECTIONS = [
	words['settingsSections.generation'],
	words['settingsSections.voices'],
	words['settingsSections.references'],
	words['settingsSections.admin'],
	words['settingsSections.about']
] as const;
const ROW_MIN_HEIGHT_PX = 52;

function settingsList(page: Page): Locator {
	return workspace(page).getByRole('navigation', { name: words['settingsPage.nav'] });
}

test(
	'the phone opens a Settings list, a row opens its page and Back returns to the list',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		await page.goto('/settings');
		await expect(page).toHaveURL(/\/settings$/);
		await expect(
			workspace(page).getByRole('heading', { name: words['places.settings'], exact: true })
		).toBeVisible();

		const rows = settingsList(page).getByRole('link');
		await expect(rows).toHaveCount(ADMIN_SECTIONS.length);
		for (const [index, label] of ADMIN_SECTIONS.entries()) {
			await expect(rows.nth(index)).toContainText(label);
			const box = await rows.nth(index).boundingBox();
			expect(box?.height ?? 0).toBeGreaterThanOrEqual(ROW_MIN_HEIGHT_PX);
		}

		await rows.filter({ hasText: words['settingsSections.voices'] }).click();
		await expect(page).toHaveURL(/\/settings\/voices$/);
		await expect(workspace(page).getByRole('heading', { name: 'My Voices' })).toBeVisible();

		await page.goBack();
		await expect(page).toHaveURL(/\/settings$/);
		await expect(settingsList(page).getByRole('link')).toHaveCount(ADMIN_SECTIONS.length);
	}
);

test(
	'the desktop keeps redirecting /settings into its first section',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await page.goto('/settings');
		await expect(page).toHaveURL(/\/settings\/generation$/);
		await expect(settingsList(page)).toHaveCount(0);
	}
);
