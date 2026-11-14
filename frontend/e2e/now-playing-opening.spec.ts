// Now Playing opens on the tab its queue calls for, and the album walk carries
// its ruled name (#1831, N1 and N3 of #1816): a queue of one take opens on
// This take, several on Queue, and the album ⋯ row, the walk's card and its
// way out say "Pick album takes" and "Done". Both shells walk the flow.

import { expect, test, type Page, type TestInfo } from './coverage-test';
import { FlowGuard, ONLY_IN_SHELL, openAlbumFromRail, shellOf, workspace } from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';
import { words } from '../src/lib/words/en';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

async function playCollection(page: Page, kind: 'album' | 'playlist'): Promise<void> {
	const play = workspace(page).getByRole('button', {
		name: words[kind === 'album' ? 'collectionHeader.playAlbum' : 'collectionHeader.playPlaylist'],
		exact: true
	});
	await play.click();
	await expect(
		page
			.getByRole('contentinfo')
			.getByRole('button', { name: words['transport.pause'], exact: true })
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
			name:
				shellOf(testInfo) === 'mobile'
					? words['player.openNowPlaying']({ title: songTitle })
					: words['transport.nowPlaying'],
			exact: true
		})
		.click();
}

/**
 * The phone opens the right panel as a sheet only on This take; on Queue the
 * sheet stays shut behind a trigger that carries the tab's name.
 */
async function expectOpenedOn(page: Page, testInfo: TestInfo, tab: string): Promise<void> {
	if (shellOf(testInfo) === 'mobile' && tab === words['nowPlaying.queueTab']) {
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

	await expectOpenedOn(page, testInfo, words['nowPlaying.takeTab']);
});

test('several takes queued open Now Playing on Queue', async ({ page, request }, testInfo) => {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	await page.goto(`/playlist/${playlist.slug}`);

	await playCollection(page, 'playlist');
	await openNowPlayingFromBar(page, testInfo, playlist.songTitles[0]);

	await expectOpenedOn(page, testInfo, words['nowPlaying.queueTab']);
});

// The album's queue starts as the one take that plays and widens a moment
// later, so the bar reads the album, not the queue so far.
test(
	'an album played from its page opens Now Playing on Queue at once',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }, testInfo) => {
		const library = readSeededLibrary();
		expect(library.albumTracks.length).toBeGreaterThan(1);
		await page.goto(`/album/${library.albumId}`);

		await playCollection(page, 'album');
		await openNowPlayingFromBar(page, testInfo, library.albumTracks[0].songTitle);

		await expectOpenedOn(page, testInfo, words['nowPlaying.queueTab']);
	}
);

test(
	'Now Playing stays on This take while the queue grows behind it',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, request }, testInfo) => {
		const library = readSeededLibrary();
		const playlist = await seedPlaylist(request, library, 1);
		await page.goto(`/playlist/${playlist.slug}`);
		await playCollection(page, 'playlist');
		await openNowPlayingFromBar(page, testInfo, playlist.songTitles[0]);
		await expectOpenedOn(page, testInfo, words['nowPlaying.takeTab']);

		await openAlbumFromRail(page, shellOf(testInfo), library.albumTitle);
		await playCollection(page, 'album');
		await expect(
			page.getByRole('contentinfo').getByRole('button', { name: 'Next', exact: true })
		).toBeEnabled();
		// Next is enabled only with two queued takes, and the album's takes are set in
		// one call, so the queue has grown behind the tab, which stays where it opened.

		await expectOpenedOn(page, testInfo, words['nowPlaying.takeTab']);
		await page.getByRole('tab', { name: words['nowPlaying.queueTab'] }).click();
		await expect(page.locator('.queue-row')).toHaveCount(library.albumTracks.length);
	}
);

test('the album walk is "Pick album takes" and ends with "Done"', async ({ page }, testInfo) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);

	await workspace(page)
		.getByRole('button', { name: words['collectionMenu.label'], exact: true })
		.click();
	await page
		.getByRole('dialog', { name: words['collectionMenu.label'] })
		.getByRole('button', { name: words['collectionMenu.curate'], exact: true })
		.click();

	const walk = page.getByRole('group', { name: words['nowPlaying.curateGroup'] });
	await expect(walk).toContainText(
		new RegExp(`^${words['nowPlaying.curateGroup']} · Song \\d+ of \\d+`)
	);
	// The phone opens the walk with the This take sheet over its card.
	if (shellOf(testInfo) === 'mobile') await page.keyboard.press('Escape');
	await walk.getByRole('button', { name: words['nowPlaying.done'], exact: true }).click();
	await expect(walk).toBeHidden();
});
