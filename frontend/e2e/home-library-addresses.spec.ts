import { expect, test } from '@playwright/test';
import {
	FlowGuard,
	expectLibraryWallLoaded,
	scrollWallHalfway,
	LIBRARY_PATH,
	LIBRARY_URL,
	HOME_URL,
	ONLY_IN_SHELL,
	openLibraryWall,
	shellOf,
	workspace
} from './helpers';
import { readSeededLibrary } from './seed';

for (const retainCollection of [false, true]) {
	test(
		retainCollection
			? '1354_rule_31: retained collection and scroll survive Back and reload'
			: '1354_rule_31 C1/C2: Back directly to the cold Library restores scroll and reload adds no entry',
		async ({ page }, testInfo) => {
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
			if (retainCollection) {
				await album.click();
				await expect(page).toHaveURL(/\/album\//);
				await openLibraryWall(page, shellOf(testInfo));
				await expect(album.locator('..')).toHaveClass(/selected/);
			}
			await expectLibraryWallLoaded(page);
			const scrolled = await scrollWallHalfway(page);
			const tiles = wall.locator('.tile-grid .wall-tile-body');
			const bounds = await body.evaluate((element) => {
				const { top, bottom } = element.getBoundingClientRect();
				return { top, bottom };
			});
			const visibleTile = await tiles.evaluateAll((elements, bounds) => {
				return elements.findIndex((element) => {
					const tile = element.getBoundingClientRect();
					return tile.top >= bounds.top && tile.bottom <= bounds.bottom;
				});
			}, bounds);
			expect(visibleTile, 'a wall tile is fully in view').toBeGreaterThanOrEqual(0);
			await tiles.nth(visibleTile).click();
			await expect(page).toHaveURL(/\/album\//);

			await page.goBack();

			await expect(page).toHaveURL(LIBRARY_URL);
			await expectLibraryWallLoaded(page);
			await expect
				.poll(() => body.evaluate((element) => Math.round(element.scrollTop)))
				.toBe(scrolled);
			if (retainCollection) await expect(album.locator('..')).toHaveClass(/selected/);
			const length = await page.evaluate(() => history.length);
			await page.reload();
			await expectLibraryWallLoaded(page);
			await expect
				.poll(() => body.evaluate((element) => Math.round(element.scrollTop)))
				.toBe(scrolled);
			expect(await page.evaluate(() => history.length)).toBe(length);
			if (retainCollection) await expect(album.locator('..')).toHaveClass(/selected/);
			guard.assertClean();
		}
	);
}

test(
	'1354_rule_31 C3: sign-in mounts the wall without adding a history entry',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/api/auth/me', statuses: [401] }]
		});
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
		guard.assertClean();
	}
);
