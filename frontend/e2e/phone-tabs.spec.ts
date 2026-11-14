import { expect, test, type Page } from './coverage-test';
import { PHONE_TABS } from '../src/lib/constants/phone-tabs';
import { words } from '../src/lib/words/en';
import {
	appBar,
	FlowGuard,
	DESKTOP_VIEWPORT,
	HOME_PATH,
	MOBILE_VIEWPORT,
	nameStartingWith,
	ONLY_IN_SHELL,
	openSettingsSection,
	workspace
} from './helpers';
import { openSearchSheet } from './phone-search';
import { readSeededLibrary } from './seed';

const TAB_LABEL_BY_PLACE = {
	home: words['places.home'],
	library: words['places.library'],
	playlists: words['places.playlists']
};
const TAB_LABELS = Object.values(TAB_LABEL_BY_PLACE);

const tabs = (page: Page) => page.getByRole('navigation', { name: words['phoneTabs.nav'] });

async function expectCurrent(page: Page, label: string | null): Promise<void> {
	await expect(tabs(page)).toBeVisible();
	await expect(tabs(page).getByRole('button')).toHaveText(TAB_LABELS);
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
		const rail = page.getByRole('navigation', { name: words['rail.nav'] });
		await expect(rail).toBeVisible();
		const links = rail.locator('.rail-page-link');
		await expect(links).toHaveText(TAB_LABELS.map((label) => new RegExp(label)));
		const icons = await links
			.locator('svg')
			.evaluateAll((nodes) => nodes.map((node) => node.innerHTML));
		await page.setViewportSize(MOBILE_VIEWPORT);
		await expectCurrent(page, words['places.home']);
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
		await expectCurrent(page, words['places.home']);
		for (const { place } of PHONE_TABS) {
			const label = TAB_LABEL_BY_PLACE[place];
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
				await tabs(page).getByRole('button', { name: words['places.home'], exact: true }).click();
				await expectCurrent(page, words['places.home']);
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
		await expectCurrent(page, words['places.library']);
		await workspace(page)
			.getByRole('button', {
				name: words['collectionHeader.playAlbum'],
				exact: true
			})
			.click();
		await expectCurrent(page, words['places.library']);
		await page
			.getByRole('contentinfo')
			.getByRole('button', {
				name: words['player.openNowPlaying']({ title: library.pickedSongTitle }),
				exact: true
			})
			.click();
		await expect(tabs(page)).toHaveCount(0);
		await page.getByRole('button', { name: words['nowPlaying.close'], exact: true }).click();
		await expectCurrent(page, words['places.library']);
		guard.assertClean();
	});

	test('1354_61_C05: playlist detail selects Playlists', async ({ page }) => {
		await page.goto('/playlists');
		await expectCurrent(page, words['places.playlists']);
		await workspace(page)
			.getByRole('button', {
				name: nameStartingWith(words['libraryWall.openPlaylist']({ title: '' }))
			})
			.first()
			.click();
		await expect(page).toHaveURL(/\/playlist\/[^/]+$/);
		await expectCurrent(page, words['places.playlists']);
	});

	for (const destination of ['Settings section', 'Voices'] as const) {
		test(`1354_61_C${destination === 'Voices' ? '11' : '10'} 1354_rule_33 1354_49: ${destination} keeps player and unselected tabs with Home reachable`, async ({
			page
		}) => {
			await page.goto(HOME_PATH);
			if (destination === 'Settings section') {
				await openSettingsSection(page, 'mobile', words['settingsSections.voices']);
				await expect(page).toHaveURL(/\/settings\/voices$/);
			} else await page.goto('/loras');
			await expectCurrent(page, null);
			await expect(page.getByRole('contentinfo')).toBeVisible();
			await tabs(page).getByRole('button', { name: words['places.home'], exact: true }).click();
			await expect.poll(() => new URL(page.url()).pathname).toBe('/');
			await expectCurrent(page, words['places.home']);
		});
	}

	test('1354_61_C26: editor Search to Voices retains the song without hiding tabs', async ({
		page
	}) => {
		const library = readSeededLibrary();
		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', {
				name: words['songRow.openInEditor']({ title: library.pickedSongTitle }),
				exact: true
			})
			.click();
		await expect(
			appBar(page).getByRole('heading', { name: library.pickedSongTitle })
		).toBeVisible();
		await expect(tabs(page)).toHaveCount(0);
		const search = await openSearchSheet(page);
		await search
			.getByRole('combobox', { name: words['railSearch.field'] })
			.fill(words['settingsSections.voices']);
		await search
			.getByRole('group', { name: words['railSearch.groupPages'] })
			.getByRole('option', { name: nameStartingWith(words['settingsSections.voices']) })
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
