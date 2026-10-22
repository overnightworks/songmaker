import { expect, test, type Page } from '@playwright/test';
import { PHONE_TABS, PHONE_TABS_NAV_LABEL } from '../src/lib/constants/phone-tabs';
import {
	NOW_PLAYING_CLOSE,
	openNowPlayingLabel,
	collectionActionLabel,
	TRANSPORT_PLAY_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SEARCH_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import {
	appBar,
	FlowGuard,
	DESKTOP_VIEWPORT,
	HOME_PATH,
	MOBILE_VIEWPORT,
	ONLY_IN_SHELL,
	openSettingsSection,
	workspace
} from './helpers';
import { openSearchSheet } from './phone-search';
import { readSeededLibrary } from './seed';

const tabs = (page: Page) => page.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL });

async function expectCurrent(page: Page, label: string | null): Promise<void> {
	await expect(tabs(page)).toBeVisible();
	await expect(tabs(page).getByRole('button')).toHaveText(PHONE_TABS.map((tab) => tab.label));
	await expect(tabs(page).locator('[aria-current="page"]')).toHaveCount(label ? 1 : 0);
	if (label)
		await expect(tabs(page).getByRole('button', { name: label, exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
	await expect(page.getByRole('button', { name: 'Open menu', exact: true })).toHaveCount(0);
}

test(
	'1354_61_C01 1354_61_C02 1354_61_C03 1354_rule_28: phone icons match the desktop rail in order',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const guard = new FlowGuard(page);
		await page.setViewportSize(DESKTOP_VIEWPORT);
		await page.goto(HOME_PATH);
		const rail = page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		await expect(rail).toBeVisible();
		const links = rail.locator('.rail-page-link');
		await expect(links).toHaveText(PHONE_TABS.map(({ label }) => new RegExp(label)));
		const icons = await links
			.locator('svg')
			.evaluateAll((nodes) => nodes.map((node) => node.innerHTML));
		await page.setViewportSize(MOBILE_VIEWPORT);
		await expectCurrent(page, 'Home');
		await expect(tabs(page).locator('svg')).toHaveCount(icons.length);
		expect(
			await tabs(page)
				.locator('svg')
				.evaluateAll((nodes) => nodes.map((node) => node.innerHTML))
		).toEqual(icons);
		guard.assertClean();
	}
);

test.describe('phone bottom places', { tag: ONLY_IN_SHELL.mobile }, () => {
	test('1354_61_C01 1354_61_C02 1354_61_C03 1354_61_C27 1354_rule_28: named tabs in order lead to their places without duplicate history', async ({
		page
	}, testInfo) => {
		const guard = new FlowGuard(page);
		await page.setViewportSize(MOBILE_VIEWPORT);
		await page.goto(HOME_PATH);
		await expectCurrent(page, 'Home');
		for (const { label, place } of PHONE_TABS) {
			const tab = tabs(page).getByRole('button', { name: label, exact: true });
			await expect(tab.locator('svg')).toBeVisible();
			await tab.click();
			await expect
				.poll(() => new URL(page.url()).pathname)
				.toBe(place === 'home' ? '/' : `/${place}`);
			await expectCurrent(page, label);
			if (place !== 'home') {
				const before = await page.evaluate(() => ({
					address: location.href,
					length: history.length
				}));
				await tab.click();
				expect(
					await page.evaluate(() => ({ address: location.href, length: history.length }))
				).toEqual(before);
				await tabs(page).getByRole('button', { name: 'Home', exact: true }).click();
				await expectCurrent(page, 'Home');
				expect(await page.evaluate(() => history.length)).toBe(before.length + 1);
			}
		}
		await page.screenshot({ path: testInfo.outputPath('phone-tabs.png') });
		guard.assertClean();
	});

	test('1354_61_C04 1354_61_C23: album stays Library from idle to playing; full player steps over tabs', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		await page.goto(`/album/${library.albumId}`);
		await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toBeVisible();
		await expectCurrent(page, 'Library');
		await workspace(page)
			.getByRole('button', {
				name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
				exact: true
			})
			.click();
		await expectCurrent(page, 'Library');
		await page
			.getByRole('contentinfo')
			.getByRole('button', { name: openNowPlayingLabel(library.pickedSongTitle), exact: true })
			.click();
		await expect(tabs(page)).toHaveCount(0);
		await page.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true }).click();
		await expectCurrent(page, 'Library');
		guard.assertClean();
	});

	test('1354_61_C05: playlist detail selects Playlists', async ({ page }) => {
		await page.goto('/playlists');
		await expectCurrent(page, 'Playlists');
		await workspace(page)
			.getByRole('button', { name: /^Open playlist / })
			.first()
			.click();
		await expect(page).toHaveURL(/\/playlist\/[^/]+$/);
		await expectCurrent(page, 'Playlists');
	});

	for (const destination of ['Settings section', 'Voices'] as const) {
		test(`1354_61_C${destination === 'Voices' ? '11' : '10'} 1354_rule_33 1354_49: ${destination} keeps player and unselected tabs with Home reachable`, async ({
			page
		}) => {
			await page.goto(HOME_PATH);
			if (destination === 'Settings section') {
				await openSettingsSection(page, 'mobile', 'Voices');
				await expect(page).toHaveURL(/\/settings\/voices$/);
			} else await page.goto('/loras');
			await expectCurrent(page, null);
			await expect(page.getByRole('contentinfo')).toBeVisible();
			await tabs(page).getByRole('button', { name: 'Home', exact: true }).click();
			await expect.poll(() => new URL(page.url()).pathname).toBe('/');
			await expectCurrent(page, 'Home');
		});
	}

	test('1354_61_C26: editor Search to Voices retains the song without hiding tabs', async ({
		page
	}) => {
		const library = readSeededLibrary();
		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle), exact: true })
			.click();
		await expect(
			appBar(page).getByRole('heading', { name: library.pickedSongTitle })
		).toBeVisible();
		await expect(tabs(page)).toHaveCount(0);
		const search = await openSearchSheet(page);
		await search.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).fill('Voices');
		await search
			.getByRole('group', { name: 'Pages' })
			.getByRole('option', { name: /^Voices\b/ })
			.click();
		await expect(page).toHaveURL(/\/settings\/voices$/);
		await expectCurrent(page, null);
		await expect(page.getByRole('contentinfo')).toBeVisible();
		await page.goBack();
		await expect(
			appBar(page).getByRole('heading', { name: library.pickedSongTitle })
		).toBeVisible();
		await expect(tabs(page)).toHaveCount(0);
	});
});
