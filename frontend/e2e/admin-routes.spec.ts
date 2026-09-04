import { expect, test } from '@playwright/test';

import { ADMIN_TABS_LABEL } from '../src/lib/constants';

test('an admin can inspect route state and switch the selected route at desktop and 375px', async ({
	page,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });

	// global-setup.ts creates the admin session used by every browser fixture.
	await page.goto('/settings/users');
	await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible();

	const compactTabs = page.getByRole('combobox', { name: ADMIN_TABS_LABEL, exact: true });
	if (await compactTabs.count()) {
		await compactTabs.selectOption('models');
	} else {
		await page.getByRole('button', { name: 'Models', exact: true }).click();
	}

	const cowriter = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'Co-Writer' }) });
	await expect(cowriter).toBeVisible();
	const routeCards = cowriter.locator('.route-card');
	await expect(routeCards.first()).toBeVisible();

	const routeCard = routeCards.first();
	await expect(routeCard).toContainText(/CLI · (ready|not set up|broken)/);
	await expect(routeCard).toContainText(/API · (ready|not set up|broken)/);

	const routeButtons = routeCard.locator('.route-switch button');
	await expect(routeButtons).toHaveCount(2);
	const selectedRouteIndex = await routeButtons.evaluateAll((buttons) =>
		buttons.findIndex((button) => button.getAttribute('aria-pressed') === 'true')
	);
	const nextRouteIndex = selectedRouteIndex === 0 ? 1 : 0;
	await routeButtons.nth(nextRouteIndex).click();
	await expect(routeButtons.nth(nextRouteIndex)).toHaveAttribute('aria-pressed', 'true');

	await expect(cowriter.locator('#cowriter-model')).toBeVisible();
	if (isMobile) {
		await expect
			.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
			.toBe(true);
	}
});
