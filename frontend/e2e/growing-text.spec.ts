// Style and lyrics show their whole text and the page scrolls (issue #1819,
// slice 1 of #1804, rules S1 and S2): no field keeps a scrollbar of its own
// at either shell, and `[Intro]`-style labels stand out while staying
// ordinary editable text. Runs in both shells (1440 and 390 wide).
//
// The song is seeded straight against the database into the album
// song-phone.spec.ts owns, once per shell: every song seeded there adds a
// request to that spec's API budget (SONG_PHONE_FLOW_API_REQUEST_BUDGET).

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

async function openSeededSong(page: Page, songTitle: string): Promise<void> {
	const library = readSeededLibrary();
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

// The textarea's own height for its text, measured on a throwaway copy that
// sits beside it with the same styling and no mirror to hold it open.
async function ownTextHeight(field: Locator): Promise<number> {
	return field.evaluate((node: HTMLTextAreaElement) => {
		const copy = node.cloneNode(true) as HTMLTextAreaElement;
		copy.removeAttribute('id');
		copy.style.gridArea = 'auto';
		copy.style.height = '0';
		node.after(copy);
		const height = copy.scrollHeight + (node.offsetHeight - node.clientHeight);
		copy.remove();
		return height;
	});
}

// Clicks the bottom-right corner of the field, where the painted text ends,
// and returns how many characters lie after the caret.
async function charactersAfterCaretClickedAtTheEnd(field: Locator): Promise<number> {
	const box = await field.boundingBox();
	if (!box) throw new Error('field has no box');
	await field.click({ position: { x: box.width - 4, y: box.height - 4 } });
	return field.evaluate((node) => {
		const textarea = node as HTMLTextAreaElement;
		return textarea.value.length - textarea.selectionStart;
	});
}

test.describe('text that is never clipped', () => {
	let songTitle: string;

	test.beforeAll(async () => {
		songTitle = `${GROWING_TEXT_SONG_TITLE} ${runMarker()}`;
		await seedSongPhoneSong(readSeededLibrary().songPhoneAlbumId, songTitle, 1, 1);
	});

	test('a 60-line lyric and a 6-line style show whole, and the page scrolls to their end', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSong(page, songTitle);

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
		await openSeededSong(page, songTitle);

		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await lyrics.fill('[Intro]\nla la');
		await lyrics.pressSequentially('\n[Verse 1]');

		await expect(lyrics).toHaveValue('[Intro]\nla la\n[Verse 1]');
		await expect(page.locator('.mirror .section-label')).toHaveText(['[Intro]', '[Verse 1]']);

		guard.assertClean();
	});

	test('a tagged style with a long word and a lyric ending in a newline keep the painted text aligned with the field', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSong(page, songTitle);

		const style = page.getByRole('textbox', { name: /^Style/ });
		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		// Letters such as v, w and y are wider bold: a tag styled that way moves a line
		// break somewhere; sweeping the length finds one.
		for (let tags = 30; tags < 70; tags += 1) {
			await style.fill(`${'[wavy vox] '.repeat(tags)}${'unbroken'.repeat(30)}`);
			expect(await hasNoScrollbarOfItsOwn(style)).toBe(true);
			const styleHeight = (await style.boundingBox())?.height ?? 0;
			expect(styleHeight).toBeCloseTo(await ownTextHeight(style), 0);
		}
		await lyrics.fill(`${LYRICS}\n`);
		expect(await hasNoScrollbarOfItsOwn(lyrics)).toBe(true);
		expect(await charactersAfterCaretClickedAtTheEnd(style)).toBe(0);
		expect(await charactersAfterCaretClickedAtTheEnd(lyrics)).toBe(0);

		const heightBeforeEnter = (await lyrics.boundingBox())?.height ?? 0;
		await lyrics.press('Enter');
		await expect(lyrics).toHaveValue(`${LYRICS}\n\n`);
		const heightAfterEnter = (await lyrics.boundingBox())?.height ?? 0;
		expect(heightAfterEnter).toBeGreaterThan(heightBeforeEnter);
		expect(await hasNoScrollbarOfItsOwn(lyrics)).toBe(true);

		guard.assertClean();
	});
});
