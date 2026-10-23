// Now Playing opens on the tab its queue calls for, and the album walk carries
// its ruled name (#1831, N1 and N3 of #1816): a queue of one take opens on
// This take, several on Queue, and the album ⋯ row, the walk's card and its
// way out say "Pick album takes" and "Done". Both shells walk the flow.

import { expect, test, type Page, type TestInfo } from '@playwright/test';
import {
	COLLECTION_MENU_CURATE_LABEL,
	COLLECTION_MENU_LABEL,
	collectionActionLabel,
	NOW_PLAYING_LABEL,
	openNowPlayingLabel,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import {
	NOW_PLAYING_CURATE_DONE_LABEL,
	NOW_PLAYING_CURATE_GROUP_LABEL,
	NOW_PLAYING_QUEUE_TAB,
	NOW_PLAYING_TAKE_TAB
} from '../src/lib/constants/now-playing';
import { FlowGuard, shellOf, workspace } from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

async function playCollection(page: Page, kind: 'album' | 'playlist'): Promise<void> {
	const play = workspace(page).getByRole('button', {
		name: collectionActionLabel(TRANSPORT_PLAY_LABEL, kind),
		exact: true
	});
	await play.click();
	await expect(
		page.getByRole('contentinfo').getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
}

/** The bar's own Now Playing button: the phone's title target, the desktop's labelled button. */
async function openNowPlayingFromBar(
	page: Page,
	testInfo: TestInfo,
	songTitle: string
): Promise<void> {
	await page
		.getByRole('contentinfo')
		.getByRole('button', {
			name: shellOf(testInfo) === 'mobile' ? openNowPlayingLabel(songTitle) : NOW_PLAYING_LABEL,
			exact: true
		})
		.click();
}

/**
 * The phone opens the right panel as a sheet only on This take; on Queue the
 * sheet stays shut behind a trigger that carries the tab's name.
 */
async function expectOpenedOn(page: Page, testInfo: TestInfo, tab: string): Promise<void> {
	if (shellOf(testInfo) === 'mobile' && tab === NOW_PLAYING_QUEUE_TAB) {
		await expect(
			page.getByRole('dialog').getByRole('button', { name: new RegExp(`${tab}$`) })
		).toBeVisible();
		await expect(page.getByRole('tab', { name: tab })).toBeHidden();
		return;
	}
	await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true');
}

test('one take queued opens Now Playing on This take', async ({ page, request }, testInfo) => {
	const library = readSeededLibrary();
	const playlist = await seedPlaylist(request, library, 1);
	await page.goto(`/playlist/${playlist.slug}`);

	await playCollection(page, 'playlist');
	await openNowPlayingFromBar(page, testInfo, playlist.songTitles[0]);

	await expectOpenedOn(page, testInfo, NOW_PLAYING_TAKE_TAB);
});

test('several takes queued open Now Playing on Queue', async ({ page, request }, testInfo) => {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	await page.goto(`/playlist/${playlist.slug}`);

	await playCollection(page, 'playlist');
	await openNowPlayingFromBar(page, testInfo, playlist.songTitles[0]);

	await expectOpenedOn(page, testInfo, NOW_PLAYING_QUEUE_TAB);
});

test('the album walk is "Pick album takes" and ends with "Done"', async ({ page }, testInfo) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);

	await workspace(page).getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
	await page
		.getByRole('dialog', { name: COLLECTION_MENU_LABEL })
		.getByRole('button', { name: COLLECTION_MENU_CURATE_LABEL, exact: true })
		.click();

	const walk = page.getByRole('group', { name: NOW_PLAYING_CURATE_GROUP_LABEL });
	await expect(walk).toContainText(
		new RegExp(`^${NOW_PLAYING_CURATE_GROUP_LABEL} · Song \\d+ of \\d+`)
	);
	// The phone opens the walk with the This take sheet over its card.
	if (shellOf(testInfo) === 'mobile') await page.keyboard.press('Escape');
	await walk.getByRole('button', { name: NOW_PLAYING_CURATE_DONE_LABEL, exact: true }).click();
	await expect(walk).toBeHidden();
});
