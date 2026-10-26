import { PHONE_TABS_NAV_LABEL } from '../src/lib/constants/phone-tabs';
import { readSeededLibrary } from './seed';
import { expect, test, type Page } from '@playwright/test';
import { TRANSPORT_PLAY_LABEL, songEditorOpenLabel } from '../src/lib/constants';
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
const PHONE_TABS_HEIGHT = 54;
const CASES = [
	{
		name: '1354_61_C21 Library at 390',
		offset: PHONE_TABS_HEIGHT,
		shell: 'mobile',
		viewport: MOBILE_VIEWPORT,
		height: 64,
		open: openLibrary,
		lastContent: lastAlbum,
		offline: true,
		refusals: []
	},
	{
		name: '1354_61_C18 app at 1440',
		offset: 0,
		shell: 'desktop',
		viewport: DESKTOP_VIEWPORT,
		height: 88,
		open: openLibrary,
		lastContent: lastAlbum,
		offline: true,
		refusals: []
	},
	{
		name: '1354_61_C21 Voices at 390',
		offset: PHONE_TABS_HEIGHT,
		shell: 'mobile',
		viewport: MOBILE_VIEWPORT,
		height: 64,
		open: async (page: Page) => {
			await page.goto('/settings/voices');
		},
		lastContent: (page: Page) => workspace(page).locator('.page > .empty, .lora-card:last-child'),
		offline: true,
		refusals: []
	},
	...([true, false] as const).flatMap((signedIn) =>
		(
			[
				{ shell: 'mobile', viewport: MOBILE_VIEWPORT, height: 64 },
				{ shell: 'desktop', viewport: DESKTOP_VIEWPORT, height: 88 }
			] as const
		).map(({ shell, viewport, height }) => ({
			name: `1354_61_C${signedIn ? '19' : '20'} public share ${signedIn ? 'signed in' : 'signed out'} at ${viewport.width}`,
			offset: 0,
			shell,
			viewport,
			height,
			open: async (page: Page) => {
				if (!signedIn) await page.context().clearCookies();
				await openMockSharedAlbum(page, mockSongs(40));
				await control(page, TRANSPORT_PLAY_LABEL).click();
			},
			lastContent: (page: Page) => page.getByRole('link', { name: 'Impressum', exact: true }),
			offline: false,
			refusals: [MOCK_STREAM_REFUSAL]
		}))
	)
] as const;

for (const cell of CASES) {
	test(
		`1354_37b_66: ${cell.name} keeps transport, offline strip and last content clear above the shell bottom`,
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
			await expect(strip).toHaveCount(0);
			const tabs = page.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL });
			if (cell.offset) {
				await expect(tabs).toBeVisible();
				const [box] = await boundingBoxes(tabs);
				expect(box.y).toBe(790);
				expect(box.height).toBe(PHONE_TABS_HEIGHT);
			} else {
				await expect(tabs).toHaveCount(0);
				await expect(page.locator('html')).not.toHaveAttribute('data-phone-tabs');
			}
			if (!cell.offline) {
				await expect(page.locator('html')).not.toHaveAttribute('data-transport-bar');
				expect(
					await page
						.locator('.shared-page')
						.evaluate((node) =>
							getComputedStyle(node).getPropertyValue('--shell-bottom-offset').trim()
						)
				).toBe('0px');
				if (cell.shell === 'desktop') {
					// The wide share keeps its inline player visible beside the scrolling songs.
					await expect(control(page, 'Pause')).toBeInViewport({ ratio: 1 });
					await expect(transport).toHaveCount(0);
					await expect(lastContent).toBeInViewport({ ratio: 1 });
					await page.screenshot({ path: testInfo.outputPath('bottom-geometry.png') });
					guard.assertClean();
					return;
				}
			}
			await expect(transport).toBeVisible();
			const [onlineBar] = await boundingBoxes(transport);
			expect(onlineBar).toEqual({
				x: 0,
				y: cell.viewport.height - cell.height - cell.offset,
				width: cell.viewport.width,
				height: cell.height
			});
			await expect(lastContent).toBeInViewport({ ratio: 1 });
			const [onlineContent] = await boundingBoxes(lastContent);
			expect(onlineContent.y + onlineContent.height).toBeLessThanOrEqual(onlineBar.y);
			await testInfo.attach('content-clearance.json', {
				body: JSON.stringify({
					gap: onlineBar.y - onlineContent.y - onlineContent.height,
					padding: await (cell.offline ? workspace(page) : page.locator('.shared-page')).evaluate(
						(node) => {
							const shell = node.closest('.app-shell');
							return {
								content: getComputedStyle(node).paddingBottom,
								shell: shell ? getComputedStyle(shell).paddingBottom : null
							};
						}
					)
				}),
				contentType: 'application/json'
			});

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

for (const safeArea of [0, 24]) {
	test(
		`1354_61_C${safeArea ? '29' : '22'}: editor returns bottom ownership to transport with ${safeArea}px safe area`,
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page, context }, testInfo) => {
			await page.setViewportSize(MOBILE_VIEWPORT);
			const cdp = await context.newCDPSession(page);
			if (safeArea) {
				try {
					await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { bottom: safeArea } });
				} catch (error) {
					testInfo.annotations.push({
						type: 'not driven',
						description: `Cell 29 requires gate disposition: ${String(error)}`
					});
					await testInfo.attach('safe-area-not-driven.txt', {
						body: String(error),
						contentType: 'text/plain'
					});
					await cdp.detach();
					return;
				}
			}
			try {
				const library = readSeededLibrary();
				await page.goto(`/album/${library.albumId}`);
				const tabs = page.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL });
				await expect(tabs).toBeVisible();
				const [tabBox, barBox] = await boundingBoxes(tabs, page.getByRole('contentinfo'));
				expect(tabBox.height).toBe(PHONE_TABS_HEIGHT + safeArea);
				expect(barBox.height).toBe(64);
				expect(barBox.y + barBox.height).toBe(tabBox.y);
				await workspace(page)
					.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle), exact: true })
					.click();
				await expect(page).toHaveURL(/\/album\/[^/]+\/[^/]+$/);
				await expect(tabs).toHaveCount(0);
				await expect(page.locator('html')).not.toHaveAttribute('data-phone-tabs');
				const [editorBar] = await boundingBoxes(page.getByRole('contentinfo'));
				expect(editorBar.height).toBe(64 + safeArea);
				expect(editorBar.y + editorBar.height).toBe(MOBILE_VIEWPORT.height);
				const generate = page
					.getByRole('tabpanel')
					.getByRole('button', { name: /^Generate/ })
					.first();
				await expect(generate).toBeVisible();
				const [generateBox] = await boundingBoxes(generate);
				expect(generateBox.y + generateBox.height).toBeLessThanOrEqual(editorBar.y);
				await page.screenshot({ path: testInfo.outputPath('editor-bottom.png') });
			} finally {
				if (safeArea)
					await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { bottom: 0 } });
				await cdp.detach();
			}
		}
	);
}
