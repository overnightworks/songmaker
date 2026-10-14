import { expect, test } from '@playwright/test';
import { RAIL_DRAWER_LABEL, RAIL_DRAWER_OPEN_LABEL, RAIL_NAV_LABEL } from '../src/lib/constants';

test('the desktop rail remembers its 52-px icon column while the 375 px drawer stays expanded', async ({
	page,
	isMobile
}) => {
	await page.setViewportSize(isMobile ? { width: 375, height: 812 } : { width: 1440, height: 900 });
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
	await page.goto('/');

	if (isMobile) {
		await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		const drawer = page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
		const rail = drawer.getByRole('navigation', { name: RAIL_NAV_LABEL });

		await expect(rail).not.toHaveClass(/rail-collapsed/);
		await expect(rail.getByRole('button', { name: 'Collapse rail' })).toHaveCount(0);
		await expect(rail.getByRole('button', { name: 'Expand rail' })).toHaveCount(0);
		await expect(rail.getByRole('slider', { name: 'Resize rail' })).toHaveCount(0);
		await expect(drawer).toHaveCSS('width', '315px');
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
	for (const label of ['Library', 'Playlists', 'Settings']) {
		await expect(rail.getByRole('button', { name: label, exact: true })).toHaveAttribute(
			'title',
			label
		);
	}

	await page.reload();
	await expect(rail).toHaveClass(/rail-collapsed/);
	await rail.getByRole('button', { name: 'Expand rail' }).click();
	await expect(rail).not.toHaveClass(/rail-collapsed/);
	await expect(rail).toHaveCSS('width', '330px');
	await expect(rail.getByRole('slider', { name: 'Resize rail' })).toBeVisible();
});
