// The Settings list on the phone (issue #1150, picture H4 in
// docs/design/navigation.html §(h)): the drawer no longer lists the settings
// pages, so on the phone `/settings` is itself the list, a row opens its
// page, and Back returns to the list. The desktop rail carries the sections,
// so there `/settings` keeps redirecting into the first one. The run's
// session is the stack's admin, so Admin and Cleanup are listed.

import { expect, test, type Locator, type Page } from '@playwright/test';
import { SETTINGS_NAV_LABEL } from '../src/lib/constants';
import { shellOf, workspace } from './helpers';

const ADMIN_SECTIONS = ['Generation', 'Voices', 'Account', 'Admin', 'Cleanup', 'Legal'] as const;
const ROW_MIN_HEIGHT_PX = 52;

function settingsList(page: Page): Locator {
	return workspace(page).getByRole('navigation', { name: SETTINGS_NAV_LABEL });
}

test('the phone opens a Settings list, a row opens its page and Back returns to the list', async ({
	page
}, testInfo) => {
	test.skip(shellOf(testInfo) !== 'mobile', 'The Settings list is the phone’s; see the header.');

	await page.goto('/settings');
	await expect(page).toHaveURL(/\/settings$/);
	await expect(
		workspace(page).getByRole('heading', { name: 'Settings', exact: true })
	).toBeVisible();

	const rows = settingsList(page).getByRole('link');
	await expect(rows).toHaveCount(ADMIN_SECTIONS.length);
	for (const [index, label] of ADMIN_SECTIONS.entries()) {
		await expect(rows.nth(index)).toContainText(label);
		const box = await rows.nth(index).boundingBox();
		expect(box?.height ?? 0).toBeGreaterThanOrEqual(ROW_MIN_HEIGHT_PX);
	}

	await rows.filter({ hasText: 'Voices' }).click();
	await expect(page).toHaveURL(/\/settings\/voices$/);
	await expect(workspace(page).getByRole('heading', { name: 'My Voices' })).toBeVisible();

	await page.goBack();
	await expect(page).toHaveURL(/\/settings$/);
	await expect(settingsList(page).getByRole('link')).toHaveCount(ADMIN_SECTIONS.length);
});

test('the desktop keeps redirecting /settings into its first section', async ({
	page
}, testInfo) => {
	test.skip(shellOf(testInfo) !== 'desktop', 'The desktop rail carries the sections.');

	await page.goto('/settings');
	await expect(page).toHaveURL(/\/settings\/generation$/);
	await expect(settingsList(page)).toHaveCount(0);
});
