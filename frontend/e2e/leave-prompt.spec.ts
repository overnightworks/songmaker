// A draft that holds changes no version holds asks before the document
// unloads; a clean one never asks.
// Each row registers its dialog listener before the trigger, because
// Playwright dismisses a dialog nobody listens for, which would cancel the
// leave.

import { expect, test, type Dialog, type Locator, type Page } from '@playwright/test';
import {
	EDITOR_UNSAVED_TITLE,
	SONG_MENU_LABEL,
	SONG_MENU_SAVE_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import { workspace } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

const TYPED_LINE = 'a line nobody saved';

interface OpenSong {
	lyrics: Locator;
	savedLyrics: string;
}

// Opened cold at its own address, then focused by a click: a person's focus,
// and the user activation Chromium wants before it shows a leave prompt.
async function openSongCold(page: Page): Promise<OpenSong> {
	const { songPhoneAlbumId } = readSeededLibrary();
	const title = `Leave Prompt ${runMarker()}`;
	await seedSongPhoneSong(songPhoneAlbumId, title, 1, 1);
	const discovery = await page.context().newPage();
	await discovery.goto(`/album/${songPhoneAlbumId}`);
	await workspace(discovery)
		.getByRole('button', { name: songEditorOpenLabel(title) })
		.click();
	await expect(discovery.getByRole('heading', { name: title })).toBeVisible();
	const address = discovery.url();
	await discovery.close();
	await page.goto(address);
	const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
	await expect(lyrics).toBeVisible();
	await lyrics.click();
	return { lyrics, savedLyrics: await lyrics.inputValue() };
}

async function typeUnsavedLine({ lyrics, savedLyrics }: OpenSong): Promise<void> {
	await lyrics.fill(`${savedLyrics}\n${TYPED_LINE}`);
}

function dialogsOf(page: Page): Dialog[] {
	const dialogs: Dialog[] = [];
	page.on('dialog', async (dialog) => {
		dialogs.push(dialog);
		await dialog.dismiss();
	});
	return dialogs;
}

async function nextDialog(page: Page): Promise<Dialog> {
	const dialog = await page.waitForEvent('dialog');
	expect(dialog.type()).toBe('beforeunload');
	return dialog;
}

async function dismissedNavigation(navigation: Promise<unknown>): Promise<void> {
	try {
		await navigation;
	} catch (error) {
		expect(String(error)).toContain('net::ERR_ABORTED');
	}
}

test.describe('leave prompt', () => {
	test('reload with unsaved typing asks, Stay keeps the text, Leave drops it', async ({
		page
	}, testInfo) => {
		const song = await openSongCold(page);
		await typeUnsavedLine(song);

		const asked = nextDialog(page);
		// Chromium navigation commands return even when Stay cancels the load.
		const browser = await page.context().newCDPSession(page);
		await browser.send('Page.reload');
		await (await asked).dismiss();
		await expect(song.lyrics).toHaveValue(`${song.savedLyrics}\n${TYPED_LINE}`);

		await page.screenshot({ path: testInfo.outputPath('dirty-stay.png') });
		const askedAgain = nextDialog(page);
		const reloadingAgain = page.reload();
		await (await askedAgain).accept();
		await reloadingAgain;
		await expect(song.lyrics).toHaveValue(song.savedLyrics);
	});

	test('reload of a draft retyped to the saved text, or never touched, asks nothing', async ({
		page
	}) => {
		const song = await openSongCold(page);
		const dialogs = dialogsOf(page);
		await page.reload();
		await song.lyrics.click();
		await typeUnsavedLine(song);
		await song.lyrics.fill(song.savedLyrics);

		await page.reload();

		await expect(song.lyrics).toHaveValue(song.savedLyrics);
		expect(dialogs).toEqual([]);
	});

	test('closing the tab with unsaved typing asks, and Stay keeps the page open', async ({
		page
	}) => {
		const song = await openSongCold(page);
		await typeUnsavedLine(song);

		const asked = nextDialog(page);
		await page.close({ runBeforeUnload: true });
		await (await asked).dismiss();

		expect(page.isClosed()).toBe(false);
	});

	test('Back out of the first app entry with unsaved typing asks', async ({ page }) => {
		const outside = 'data:text/html,<title>Outside Songmaker</title>Outside Songmaker';
		await page.goto(outside);
		const song = await openSongCold(page);
		await typeUnsavedLine(song);

		const asked = nextDialog(page);
		const browser = await page.context().newCDPSession(page);
		const history = await browser.send('Page.getNavigationHistory');
		const previous = history.entries[history.currentIndex - 1];
		expect(previous.url).toBe(outside);
		await browser.send('Page.navigateToHistoryEntry', { entryId: previous.id });
		await (await asked).dismiss();

		await expect(song.lyrics).toHaveValue(`${song.savedLyrics}\n${TYPED_LINE}`);
	});

	test('leaving the app for another document asks and Stay keeps the draft', async ({ page }) => {
		const song = await openSongCold(page);
		await typeUnsavedLine(song);
		const outside = 'data:text/html,<title>Outside Songmaker</title>Outside Songmaker';
		const asked = nextDialog(page);
		const leaving = dismissedNavigation(page.goto(outside));
		await (await asked).dismiss();
		await leaving;
		await expect(song.lyrics).toHaveValue(`${song.savedLyrics}\n${TYPED_LINE}`);
		const askedAgain = nextDialog(page);
		const leavingAgain = page.goto(outside);
		await (await askedAgain).accept();
		await leavingAgain;
		await expect(page).toHaveTitle('Outside Songmaker');
	});

	test('saving the edited version clears the browser prompt', async ({ page }) => {
		const song = await openSongCold(page);
		await typeUnsavedLine(song);
		await page.getByRole('button', { name: SONG_MENU_LABEL, exact: true }).click();
		const saved = page.waitForResponse(
			(response) =>
				response.url().includes('/api/songs/') &&
				response.request().method() === 'PUT' &&
				response.ok()
		);
		await page.getByRole('button', { name: SONG_MENU_SAVE_LABEL, exact: true }).click();
		await saved;
		await expect(page.getByText(/^Saved version \d+$/)).toBeVisible();
		const dialogs = dialogsOf(page);
		await page.reload();
		await expect(song.lyrics).toHaveValue(`${song.savedLyrics}\n${TYPED_LINE}`);
		expect(dialogs).toEqual([]);
	});

	test('leaving the song inside the app asks with the Unsaved changes dialog only', async ({
		page
	}) => {
		const song = await openSongCold(page);
		const dialogs = dialogsOf(page);
		await typeUnsavedLine(song);
		await song.lyrics.blur();

		await page.keyboard.press('Escape');

		await expect(page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE })).toBeVisible();
		expect(dialogs).toEqual([]);
	});
});
