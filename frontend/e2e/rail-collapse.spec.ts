import { PHONE_TABS_NAV_LABEL } from '../src/lib/constants/phone-tabs';
import { expect, test } from '@playwright/test';
import { RAIL_NAV_LABEL } from '../src/lib/constants';
import { HOME_PATH, LIBRARY_PATH, ONLY_IN_SHELL } from './helpers';

for (const { shell, name, viewport } of [
	{
		shell: 'desktop',
		name: 'the desktop rail remembers its 52-px icon column (defect:#1409)',
		viewport: { width: 1440, height: 900 }
	},
	{
		shell: 'mobile',
		name: '1354_61_C30: phone tabs ignore the desktop collapse preference',
		viewport: { width: 390, height: 844 }
	}
] as const) {
	test(`1354_61_C18 1354_37a_A6: ${name}`, { tag: ONLY_IN_SHELL[shell] }, async ({ page }) => {
		const isMobile = shell === 'mobile';
		await page.setViewportSize(viewport);
		await page.addInitScript((mobile) => {
			if (sessionStorage.getItem('railCollapsePreferenceReset') === 'true') return;
			if (mobile) {
				localStorage.setItem('songmaker.rail-collapsed', 'true');
				localStorage.setItem('songmaker.rail-width', '360');
			} else {
				localStorage.removeItem('songmaker.rail-collapsed');
				localStorage.removeItem('songmaker.rail-width');
			}
			sessionStorage.setItem('railCollapsePreferenceReset', 'true');
		}, Boolean(isMobile));
		await page.goto(HOME_PATH);

		if (isMobile) {
			await expect(page.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL })).toBeVisible();
			await expect(page.getByRole('navigation', { name: RAIL_NAV_LABEL })).toHaveCount(0);
			return;
		}

		const rail = page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		const resizeHandle = rail.getByRole('slider', { name: 'Resize rail' });
		const railScroll = rail.locator('.rail-scroll');
		await expect(resizeHandle).toBeVisible();
		await resizeHandle.focus();
		await resizeHandle.press('ArrowRight');
		await expect(rail).toHaveCSS('width', '272px');
		const scrollTop = await railScroll.evaluate((element) => {
			element.scrollTop = Math.min(40, element.scrollHeight - element.clientHeight);
			return element.scrollTop;
		});
		const resizeBox = await resizeHandle.boundingBox();
		const railBox = await rail.boundingBox();
		if (!resizeBox || !railBox) throw new Error('Expected a visible rail resize handle');
		await page.mouse.move(resizeBox.x + resizeBox.width / 2, resizeBox.y + 40);
		await page.mouse.down();
		await page.mouse.move(railBox.x + 330, resizeBox.y + 40);
		await page.mouse.up();
		await expect(rail).toHaveCSS('width', '330px');
		await expect(resizeHandle).toBeFocused();
		expect(await railScroll.evaluate((element) => element.scrollTop)).toBe(scrollTop);

		const control = rail.getByRole('button', { name: 'Collapse rail' });
		await expect(control).toBeVisible();
		await control.click();
		await expect(rail).toHaveClass(/rail-collapsed/);
		await expect(rail).toHaveCSS('width', '52px');
		await expect(rail.getByRole('button', { name: 'Expand rail' })).toBeVisible();
		await expect(rail.getByRole('button', { name: 'Settings', exact: true })).toHaveAttribute(
			'title',
			'Settings'
		);
		// defect:#1409 (#1354 rule 40): the fold control hides, so the icon column fits the 52 px rail.
		expect(await railScroll.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
			true
		);
		for (const [label, pathname] of [
			['Playlists', '/playlists'],
			['Library', LIBRARY_PATH]
		]) {
			const groupIcon = rail.getByRole('link', { name: new RegExp(`^${label}\\b`) });
			await expect(groupIcon).toHaveAttribute('title', label);
			await groupIcon.click();
			await expect.poll(() => new URL(page.url()).pathname).toBe(pathname);
		}

		await page.reload();
		await expect(rail).toHaveClass(/rail-collapsed/);
		await rail.getByRole('button', { name: 'Expand rail' }).click();
		await expect(rail).not.toHaveClass(/rail-collapsed/);
		await expect(rail).toHaveCSS('width', '330px');
		await expect(rail.getByRole('slider', { name: 'Resize rail' })).toBeVisible();
	});
}
