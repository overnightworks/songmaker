import { expect, test, type Page } from '@playwright/test';
import { TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import {
	boundingBoxes,
	DESKTOP_VIEWPORT,
	expectLibraryWallLoaded,
	FlowGuard,
	LIBRARY_PATH,
	loseNetwork,
	MOBILE_VIEWPORT,
	ONLY_IN_SHELL,
	offlineStrip,
	workspace
} from './helpers';
import {
	control,
	MOCK_STREAM_REFUSAL,
	openMockSharedAlbum,
	mockSongs
} from './share-album-fixtures';

async function openLibrary(page: Page): Promise<void> {
	await page.goto(LIBRARY_PATH);
	await expectLibraryWallLoaded(page);
}

function lastAlbum(page: Page) {
	return workspace(page)
		.getByRole('button', { name: /^Open album / })
		.last();
}

const OFFLINE_STRIP_HEIGHT = 36;
const CASES = [
	{
		name: 'app at 390',
		shell: 'mobile',
		viewport: MOBILE_VIEWPORT,
		height: 64,
		open: openLibrary,
		lastContent: lastAlbum,
		offline: true,
		refusals: []
	},
	{
		name: 'app at 1440',
		shell: 'desktop',
		viewport: DESKTOP_VIEWPORT,
		height: 88,
		open: openLibrary,
		lastContent: lastAlbum,
		offline: true,
		refusals: []
	},
	{
		name: 'public share at 390',
		shell: 'mobile',
		viewport: MOBILE_VIEWPORT,
		height: 64,
		open: async (page: Page) => {
			await page.context().clearCookies();
			await openMockSharedAlbum(page, mockSongs(40));
			await control(page, TRANSPORT_PLAY_LABEL).click();
		},
		lastContent: (page: Page) => page.getByRole('button', { name: 'Impressum', exact: true }),
		offline: false,
		refusals: [MOCK_STREAM_REFUSAL]
	}
] as const;

for (const cell of CASES) {
	test(
		`1354_37b_66: ${cell.name} keeps transport, offline strip and last content clear at zero offset`,
		{ tag: ONLY_IN_SHELL[cell.shell] },
		async ({ page, context }, testInfo) => {
			const guard = new FlowGuard(page, {
				losesNetworkOnPurpose: cell.offline,
				refusalsExpectedOn: [...cell.refusals]
			});
			await page.setViewportSize(cell.viewport);
			await cell.open(page);
			const lastContent = cell.lastContent(page);
			await lastContent.scrollIntoViewIfNeeded();
			const transport = page.locator('footer.player-bar');
			const strip = offlineStrip(page); // 1354_65_A3
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

			if (cell.offline) {
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
					y: onlineBar.y - OFFLINE_STRIP_HEIGHT,
					width: cell.viewport.width,
					height: OFFLINE_STRIP_HEIGHT
				});
				await expect(lastContent).toBeInViewport({ ratio: 1 });
				expect(content.y + content.height).toBeLessThanOrEqual(offlineStrip.y);
			}
			await page.screenshot({ path: testInfo.outputPath('bottom-geometry.png') });
			guard.assertClean();
		}
	);
}
