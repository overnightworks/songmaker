import type { Page } from '@playwright/test';
import { words } from '../src/lib/words/en';
import { workspace, type Shell } from './helpers';

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
