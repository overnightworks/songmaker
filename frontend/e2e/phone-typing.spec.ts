// Typing on the phone (issue #999): while a text field has focus the keyboard
// owns the bottom of the screen, so the mini-player and the Generate bar step
// aside and come back once the field is left; on the co-writer screen only
// the player steps aside, the composer keeps its Send. Mobile project only —
// the rule follows the compact layout, and desktop keeps every bar (the unit
// suite pins that side in routes/layout.test.ts).
//
// Its song is seeded directly against the database (`seedSongPhoneSong`),
// into the album song-phone.spec.ts already owns for phone-only songs.

import { expect, test, type Page } from '@playwright/test';
import {
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_VIEW_COWRITER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_SEARCH_LABEL,
	SONG_TITLE_LABEL
} from '../src/lib/constants';
import { appBar, FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

const PHONE_TYPING_SONG_TITLE = 'Phone Typing';
const COWRITER_COMPOSER_PLACEHOLDER = /^Ask the co-writer/;
const COWRITER_SEND_LABEL = 'Send';
const NO_RESERVED_ROOM = '0px';

// The room every layout keeps free for the transport bar (app.css owns it):
// while the keyboard owns the bottom, the page takes it back.
function reservedTransportBarRoom(page: Page): Promise<string> {
	return page.evaluate(() =>
		getComputedStyle(document.documentElement).getPropertyValue('--player-height').trim()
	);
}

// Opens a freshly seeded song from its album row, the way a musician reaches
// it, so browser back returns to that album page.
async function openSeededSongFromItsAlbum(page: Page): Promise<void> {
	const library = readSeededLibrary();
	const songTitle = `${PHONE_TYPING_SONG_TITLE} ${runMarker()}`;
	await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
	await page.goto(`/album/${library.songPhoneAlbumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(songTitle) })
		.click();
	await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();
}

test.describe('typing on the phone', () => {
	test.beforeEach(({ isMobile }) => {
		test.skip(!isMobile, 'Mobile-only compact-shell rule; see the file header.');
	});

	test('the mini-player and the Generate bar step aside while a field has focus, and come back after', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page);

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
		expect(await reservedTransportBarRoom(page)).toBe(NO_RESERVED_ROOM);

		await lyrics.blur();
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();
		expect(await reservedTransportBarRoom(page)).not.toBe(NO_RESERVED_ROOM);

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

	test('the mini-player and the Generate bar come back when a focused field leaves the page', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.getByRole('textbox', { name: /^Lyrics/ }).click();
		await expect(miniPlayer).toBeHidden();
		await page.goBack();
		await expect(miniPlayer).toBeVisible();

		await page.goForward();
		await appBar(page)
			.getByRole('button', { name: `Edit ${SONG_TITLE_LABEL.toLowerCase()}` })
			.click();
		await expect(miniPlayer).toBeHidden();
		await page.keyboard.press('Escape');
		await expect(miniPlayer).toBeVisible();
		await expect(
			page
				.getByRole('tabpanel')
				.getByRole('button', { name: EDITOR_GENERATE_MODE_LABELS.generate, exact: true })
		).toBeVisible();

		await appBar(page).getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		await page.getByRole('searchbox', { name: RAIL_SEARCH_LABEL }).click();
		await expect(miniPlayer).toBeHidden();
		await page.keyboard.press('Escape');
		await page.keyboard.press('Escape');
		await expect(miniPlayer).toBeVisible();

		guard.assertClean();
	});
});
