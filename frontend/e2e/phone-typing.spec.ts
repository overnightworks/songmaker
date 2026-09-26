// Typing on the phone (issue #999): while a text field has focus the keyboard
// owns the bottom of the screen, so the mini-player and the Generate bar step
// aside and come back once the field is left; on the co-writer screen only
// the player steps aside, the composer keeps its Send. Mobile project only —
// the rule follows the compact layout, and desktop keeps every bar (the unit
// suite pins that side in routes/layout.test.ts).
//
// Its song is seeded directly against the database (`seedSongPhoneSong`),
// into the album song-phone.spec.ts already owns for phone-only songs.

import { expect, test } from '@playwright/test';
import { EDITOR_GENERATE_MODE_LABELS, EDITOR_VIEW_COWRITER_LABEL } from '../src/lib/constants';
import { appBar, FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

const PHONE_TYPING_SONG_TITLE = 'Phone Typing';
const COWRITER_COMPOSER_PLACEHOLDER = /^Ask the co-writer/;
const COWRITER_SEND_LABEL = 'Send';

test.describe('typing on the phone', () => {
	test('the mini-player and the Generate bar step aside while a field has focus, and come back after', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell rule; see the file header.');
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		const songTitle = `${PHONE_TYPING_SONG_TITLE} ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();

		const miniPlayer = page.getByRole('contentinfo');
		const generate = page
			.getByRole('tabpanel')
			.getByRole('button', { name: EDITOR_GENERATE_MODE_LABELS.generate, exact: true });
		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();

		await lyrics.click();
		await expect(miniPlayer).toBeHidden();
		await expect(generate).toBeHidden();
		await expect(appBar(page)).toBeVisible();
		await expect(lyrics).toBeInViewport();

		await lyrics.blur();
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();

		await page.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL }).click();
		const composer = page.getByPlaceholder(COWRITER_COMPOSER_PLACEHOLDER);
		await composer.click();
		await expect(miniPlayer).toBeHidden();
		await expect(
			page.getByRole('button', { name: COWRITER_SEND_LABEL, exact: true })
		).toBeVisible();

		await composer.blur();
		await expect(miniPlayer).toBeVisible();

		guard.assertClean();
	});
});
