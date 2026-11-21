// The two steps every Now Playing flow starts with: play the open collection,
// then open Now Playing from the transport bar.

import { expect, type Page, type TestInfo } from './coverage-test';
import { shellOf, workspace } from './helpers';
import { words } from '../src/lib/words/en';

/** Presses the open collection's play button and waits for the bar to show it playing. */
export async function playCollection(page: Page, kind: 'album' | 'playlist'): Promise<void> {
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
export async function openNowPlayingFromBar(
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
