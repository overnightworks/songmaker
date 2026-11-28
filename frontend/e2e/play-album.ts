import { expect, type Page } from '@playwright/test';
import { words } from '../src/lib/words/en';
import { nameStartingWith, workspace, type Shell } from './helpers';

/** Starts the open album from its header's play button. */
export async function playOpenAlbum(page: Page, text: typeof words = words): Promise<void> {
	await workspace(page)
		.getByRole('button', { name: text['collectionHeader.playAlbum'], exact: true })
		.click();
}

/** The bar's own Now Playing button: the phone's title target, the desktop's labelled button. */
export async function openNowPlayingFromBar(
	page: Page,
	shell: Shell,
	songTitle: string,
	text: typeof words = words
): Promise<void> {
	await page
		.getByRole('contentinfo')
		.getByRole('button', {
			name:
				shell === 'mobile'
					? text['player.openNowPlaying']({ title: songTitle })
					: text['transport.nowPlaying'],
			exact: true
		})
		.click();
}

/**
 * Now Playing's This take panel, raised from the bar. On the phone the panel
 * is a sheet: a song of one take opens it already (and on This take), a
 * song of several leaves it shut behind the tab strip's trigger.
 */
export async function openThisTakeFromBar(
	page: Page,
	shell: Shell,
	songTitle: string
): Promise<void> {
	await openNowPlayingFromBar(page, shell, songTitle);
	const takeTab = page.getByRole('tab', { name: words['nowPlaying.takeTab'] });
	if (shell === 'mobile') {
		const closedSheetTrigger = page.getByRole('dialog', { name: songTitle }).getByRole('button', {
			name: new RegExp(`${words['nowPlaying.queueTab']}$`),
			expanded: false
		});
		// The sheet either opens itself on mount or waits behind its trigger.
		await expect(takeTab.or(closedSheetTrigger)).toBeVisible();
		if (await closedSheetTrigger.isVisible()) await closedSheetTrigger.click();
	}
	await takeTab.click();
}

/** The phone's Now Playing leaves for the playing song through its take menu: Open version, or Go to song for an imported take. */
export async function leaveNowPlayingForSong(page: Page, songTitle: string): Promise<void> {
	const nowPlaying = page.getByRole('dialog', { name: songTitle });
	await nowPlaying.getByRole('button', { name: words['takeMenu.label'] }).click();
	const leave = nameStartingWith(words['takeMenu.openVersion'], words['takeMenu.goToSong']);
	await nowPlaying.getByRole('button', { name: leave }).click();
}
