import { expect, test } from '@playwright/test';
import { LIBRARY_WALL_ORDER_GROUP_LABEL, LIBRARY_WALL_ORDER_LABELS } from '../src/lib/constants';
import {
	FlowGuard,
	LIBRARY_PATH,
	LIBRARY_URL,
	HOME_URL,
	ONLY_IN_SHELL,
	openLibraryWall,
	shellOf,
	workspace
} from './helpers';
import { readSeededLibrary } from './seed';

test('1354_rule_31 C1/C2: a cold Library, album Back and wall reload preserve the wall and its scroll', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const surface = workspace(page);
	const wall = surface.locator('.library-wall');
	const body = wall.locator('.wall-body');
	const album = wall.getByRole('button', {
		name: `Open album ${readSeededLibrary().albumTitle}`,
		exact: true
	});
	await page.goto(LIBRARY_PATH);
	await expect(album).toBeVisible();
	// Retain a real collection behind the wall before exercising its restore.
	await album.click();
	await expect(page).toHaveURL(/\/album\//);
	await openLibraryWall(page, shellOf(testInfo));
	await wall
		.getByRole('group', { name: LIBRARY_WALL_ORDER_GROUP_LABEL })
		.getByRole('button', { name: LIBRARY_WALL_ORDER_LABELS.played, exact: true })
		.click();
	await expect(wall.getByRole('heading')).toContainText(/\d+/);
	const tiles = wall.locator('.tile-grid .wall-tile-body');
	await tiles.last().scrollIntoViewIfNeeded();
	await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
	const scrolled = await body.evaluate((element) => Math.round(element.scrollTop));
	await tiles.last().click();
	await expect(page).toHaveURL(/\/album\//);

	await page.goBack();

	await expect(page).toHaveURL(LIBRARY_URL);
	await expect(wall).toBeVisible();
	await expect.poll(() => body.evaluate((element) => Math.round(element.scrollTop))).toBe(scrolled);
	const length = await page.evaluate(() => history.length);
	await page.reload();
	await expect(wall).toBeVisible();
	await expect.poll(() => body.evaluate((element) => Math.round(element.scrollTop))).toBe(scrolled);
	expect(await page.evaluate(() => history.length)).toBe(length);
	await expect(
		wall.getByRole('button', { name: LIBRARY_WALL_ORDER_LABELS.played, exact: true })
	).toHaveAttribute('aria-pressed', 'true');
	guard.assertClean();
});

test(
	'1354_rule_31 C3: sign-in mounts the wall without adding a history entry',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		await context.clearCookies();
		await page.goto('/login');
		const username = process.env.ADMIN_USERNAME;
		const password = process.env.ADMIN_PASSWORD;
		if (!username || !password) throw new Error('The e2e stack requires admin credentials');
		await page.getByLabel('Username').fill(username);
		await page.getByLabel('Password').fill(password);
		const length = await page.evaluate(() => history.length);
		await page.getByRole('button', { name: 'Enter', exact: true }).click();
		await expect(page).toHaveURL(HOME_URL);
		await expect(workspace(page).locator('.library-wall')).toBeVisible();
		expect(await page.evaluate(() => history.length)).toBe(length);
	}
);
