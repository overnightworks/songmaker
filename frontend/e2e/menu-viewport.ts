// What every popover menu promises about where it stands: fully on screen,
// with its rows inside it. Jsdom cannot measure it, so the specs that open a
// menu (album-menu.spec.ts, song-menu.spec.ts) ask a real browser through this.

import { expect, type Locator, type Page } from '@playwright/test';
import { boundingBoxes, type RenderedBox } from './helpers';

export const VIEWPORT_MARGIN_PX = 8;

export function rightOf(box: RenderedBox): number {
	return box.x + box.width;
}

export function bottomOf(box: RenderedBox): number {
	return box.y + box.height;
}

export function expectInside(inner: RenderedBox, outer: RenderedBox): void {
	expect(inner.x).toBeGreaterThanOrEqual(outer.x);
	expect(inner.y).toBeGreaterThanOrEqual(outer.y);
	expect(rightOf(inner)).toBeLessThanOrEqual(rightOf(outer));
	expect(bottomOf(inner)).toBeLessThanOrEqual(bottomOf(outer));
}

export async function expectMenuInsideViewport(page: Page, menu: Locator): Promise<void> {
	const viewport = page.viewportSize();
	if (!viewport) throw new Error('Expected a fixed viewport to measure against');
	const [menuBox] = await boundingBoxes(menu);
	expectInside(menuBox, {
		x: VIEWPORT_MARGIN_PX,
		y: VIEWPORT_MARGIN_PX,
		width: viewport.width - 2 * VIEWPORT_MARGIN_PX,
		height: viewport.height - 2 * VIEWPORT_MARGIN_PX
	});
	const rows = await menu.getByRole('button').all();
	expect(rows.length).toBeGreaterThan(0);
	for (const rowBox of await boundingBoxes(...rows)) expectInside(rowBox, menuBox);
}
