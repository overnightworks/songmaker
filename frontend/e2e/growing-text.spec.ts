// Style and lyrics show their whole text and the page scrolls (issue #1819,
// slice 1 of #1804, rules S1 and S2): no field keeps a scrollbar of its own
// at either shell, and `[Intro]`-style labels stand out while staying
// ordinary editable text. Runs in both shells (1440 and 390 wide).
//
// The song is seeded straight against the database into the album
// song-phone.spec.ts owns.

import { expect, test, type Locator, type Page } from '@playwright/test';
import { songEditorOpenLabel } from '../src/lib/constants';
import { FlowGuard, workspace } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

const GROWING_TEXT_SONG_TITLE = 'Growing Text';
const LYRICS = [
	'[Intro]',
	...Array.from({ length: 58 }, (_, line) => `Line ${line + 1} of the song`),
	'[Outro]'
].join('\n');
const STYLE = Array.from({ length: 6 }, (_, line) => `style note ${line + 1}`).join('\n');

async function openSeededSong(page: Page): Promise<void> {
	const library = readSeededLibrary();
	const songTitle = `${GROWING_TEXT_SONG_TITLE} ${runMarker()}`;
	await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
	await page.goto(`/album/${library.songPhoneAlbumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(songTitle) })
		.click();
	await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();
	await expect(page).toHaveURL(new RegExp(`/album/${library.songPhoneAlbumId}/[^/]+$`));
}

async function hasNoScrollbarOfItsOwn(field: Locator): Promise<boolean> {
	return field.evaluate((node) => node.scrollHeight <= node.clientHeight);
}

async function endIsReachableByScrollingThePage(field: Locator): Promise<boolean> {
	return field.evaluate((node) => {
		node.scrollIntoView({ block: 'end' });
		return node.getBoundingClientRect().bottom <= window.innerHeight + 1;
	});
}

test.describe('text that is never clipped', () => {
	test('a 60-line lyric and a 6-line style show whole, and the page scrolls to their end', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSong(page);

		const style = page.getByRole('textbox', { name: /^Style/ });
		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await style.fill(STYLE);
		await lyrics.fill(LYRICS);

		await expect(lyrics).toHaveValue(LYRICS);
		await expect(style).toHaveValue(STYLE);
		for (const field of [style, lyrics]) {
			expect(await hasNoScrollbarOfItsOwn(field)).toBe(true);
			expect(await endIsReachableByScrollingThePage(field)).toBe(true);
		}
		const lyricsHeight = (await lyrics.boundingBox())?.height ?? 0;
		const viewportHeight = page.viewportSize()?.height ?? 0;
		expect(lyricsHeight).toBeGreaterThan(viewportHeight);

		guard.assertClean();
	});

	test('[Intro] and [Verse 1] stand out and stay plain text in the field', async ({ page }) => {
		const guard = new FlowGuard(page);
		await openSeededSong(page);

		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await lyrics.fill('[Intro]\nla la');
		await lyrics.pressSequentially('\n[Verse 1]');

		await expect(lyrics).toHaveValue('[Intro]\nla la\n[Verse 1]');
		await expect(page.locator('.mirror .section-label')).toHaveText(['[Intro]', '[Verse 1]']);

		guard.assertClean();
	});
});
