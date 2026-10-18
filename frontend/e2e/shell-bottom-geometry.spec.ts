import { expect, test } from '@playwright/test';
import { OFFLINE_STRIP_MESSAGE, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import {
	boundingBoxes,
	DESKTOP_VIEWPORT,
	expectLibraryWallLoaded,
	FlowGuard,
	LIBRARY_PATH,
	loseNetwork,
	MOBILE_VIEWPORT,
	ONLY_IN_SHELL,
	workspace
} from './helpers';
import { MOCK_ALBUM_TITLE, MOCK_URL, mockSharedAlbum, mockSongs } from './share-album-fixtures';

const CASES = [
	{ name: 'app at 390', shell: 'mobile', viewport: MOBILE_VIEWPORT, share: false, height: 64 },
	{ name: 'app at 1440', shell: 'desktop', viewport: DESKTOP_VIEWPORT, share: false, height: 88 },
	{
		name: 'public share at 390',
		shell: 'mobile',
		viewport: MOBILE_VIEWPORT,
		share: true,
		height: 64
	}
] as const;

for (const cell of CASES) {
	test(
		`1354_37b_66: ${cell.name} keeps transport, offline strip and last content clear at zero offset`,
		{ tag: ONLY_IN_SHELL[cell.shell] },
		async ({ page, context }, testInfo) => {
			const guard = new FlowGuard(page, {
				losesNetworkOnPurpose: !cell.share,
				refusalsExpectedOn: cell.share
					? [{ path: '/shared/mock-album/stream', statuses: [404] }]
					: []
			});
			await page.setViewportSize(cell.viewport);
			if (cell.share) {
				await context.clearCookies();
				await mockSharedAlbum(page, mockSongs(40));
				await page.goto(MOCK_URL);
				await expect(page.getByRole('heading', { level: 1 })).toHaveText(MOCK_ALBUM_TITLE);
				await page
					.locator('.now-playing.page')
					.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
					.click();
			} else {
				await page.goto(LIBRARY_PATH);
				await expectLibraryWallLoaded(page);
			}

			const lastContent = cell.share
				? page.getByRole('button', { name: 'Impressum', exact: true })
				: workspace(page)
						.getByRole('button', { name: /^Open album / })
						.last();
			await lastContent.scrollIntoViewIfNeeded();
			const transport = page.locator('footer.player-bar');
			const strip = page.getByRole('status').filter({ hasText: OFFLINE_STRIP_MESSAGE });
			await expect(transport).toBeVisible();
			await expect(strip).toHaveCount(0);
			const [onlineBar] = await boundingBoxes(transport);
			expect(onlineBar).toEqual({
				x: 0,
				y: cell.viewport.height - cell.height,
				width: cell.viewport.width,
				height: cell.height
			});
			await expect(lastContent).toBeInViewport({ ratio: 1 });
			const [onlineContent] = await boundingBoxes(lastContent);
			expect(onlineContent.y + onlineContent.height).toBeLessThanOrEqual(onlineBar.y);

			if (!cell.share) {
				await loseNetwork(page, context);
				await expect(strip).toBeVisible();
				await lastContent.scrollIntoViewIfNeeded();
				const [offlineBar, offlineStrip, content] = await boundingBoxes(
					transport,
					strip,
					lastContent
				);
				expect(offlineBar).toEqual(onlineBar);
				expect(offlineStrip).toEqual({
					x: 0,
					y: onlineBar.y - 36,
					width: cell.viewport.width,
					height: 36
				});
				await expect(lastContent).toBeInViewport({ ratio: 1 });
				expect(content.y + content.height).toBeLessThanOrEqual(offlineStrip.y);
			}
			await page.screenshot({ path: testInfo.outputPath('bottom-geometry.png') });
			guard.assertClean();
		}
	);
}
