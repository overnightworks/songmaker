// Typing on the phone (issues #999, #1017): while a text field has focus and
// the on-screen keyboard is open, the keyboard owns the bottom of the screen,
// so the mini-player and the Generate bar step aside and come back once the
// field is left or the keyboard closes; on the Co-writer tab only the
// player steps aside, the composer keeps its Send, and a tap on Send sends
// without handing the bottom back first (#1063). Mobile project only — the
// rule follows the compact layout, and desktop keeps every bar (the unit
// suite pins that side in routes/layout.test.ts).
//
// Chromium's device emulation opens no on-screen keyboard, so the spec stands
// one in: the visual viewport shortens the way a phone's does while the
// layout viewport keeps its height (`showOnScreenKeyboard`).
//
// Its songs and the running generation are seeded directly against the
// database (`seedSongPhoneSong`, `seedRunningGenerationJob`), into the album
// song-phone.spec.ts already owns for phone-only songs.

import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import {
	APP_NAME,
	COWRITER_TURN_PATH,
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_GENERATE_TAKE_TEMPLATE,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_SEARCH_LABEL,
	SONG_TITLE_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { appBar, FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary, runMarker, seedRunningGenerationJob, seedSongPhoneSong } from './seed';

const PHONE_TYPING_SONG_TITLE = 'Phone Typing';
const COWRITER_COMPOSER_PLACEHOLDER = /^Ask for a rewrite/;
const COWRITER_SEND_LABEL = 'Send';
const NO_RESERVED_ROOM = '0px';
const ON_SCREEN_KEYBOARD_HEIGHT_PX = 320;
const LONG_LYRICS = Array.from({ length: 60 }, (_, line) => `Line ${line + 1} of the song`).join(
	'\n'
);
const LYRICS_TYPED_ON = ' and on';
const COWRITER_MESSAGE = 'Kürz den Refrain auf zwei Zeilen';
const CONVERSATIONS_PATH = '/api/conversations';
// The route error frame the server ends a turn with when the provider cannot
// run; the panel names the provider in front of the library's reason.
const COWRITER_TURN_REFUSAL_FRAME = {
	type: 'error',
	status: 503,
	provider: 'claude',
	route: null,
	reason: { code: 'cli_binary_unavailable', message: 'CLI is unavailable.' }
};
const COWRITER_TURN_REFUSAL = 'Claude: CLI is unavailable.';
const RUNNING_JOB = {
	progress: 0.36,
	takeIndex: 1,
	takeCount: 2,
	phase: 'rendering',
	generationStartedOffsetSeconds: 64
} as const;
const RUNNING_JOB_TAKE_COUNTER = EDITOR_GENERATE_TAKE_TEMPLATE.replace(
	'{index}',
	String(RUNNING_JOB.takeIndex)
).replace('{count}', String(RUNNING_JOB.takeCount));
const RUNNING_JOB_PERCENT = `${Math.round(RUNNING_JOB.progress * 100)}%`;

async function showOnScreenKeyboard(page: Page, open: boolean): Promise<void> {
	await page.evaluate(
		({ open, keyboardHeight }) => {
			const viewport = window.visualViewport;
			if (!viewport) throw new Error('This browser has no visual viewport');
			if (open) {
				Object.defineProperty(viewport, 'height', {
					configurable: true,
					get: () => document.documentElement.clientHeight - keyboardHeight
				});
			} else {
				Reflect.deleteProperty(viewport, 'height');
			}
			viewport.dispatchEvent(new Event('resize'));
		},
		{ open, keyboardHeight: ON_SCREEN_KEYBOARD_HEIGHT_PX }
	);
}

// The room every layout keeps free for the transport bar (app.css owns it):
// while the keyboard owns the bottom, the page takes it back.
function reservedTransportBarRoom(page: Page): Promise<string> {
	return page.evaluate(() =>
		getComputedStyle(document.documentElement).getPropertyValue('--player-height').trim()
	);
}

// The Generate bar's button, whether it can run or names inside its own box
// why it cannot: CI's stack runs no ACE-Step worker, so once `/health` answers
// it reads "Generate — No GPU worker online" (#1011).
function generateButton(page: Page): Locator {
	return page
		.getByRole('tabpanel')
		.getByRole('button', { name: nameStartingWith(EDITOR_GENERATE_MODE_LABELS.generate) });
}

// Opens a freshly seeded song from its album row, the way a musician reaches
// it, so browser back returns to that album page.
// A song arranged beforehand (a running generation) is picked up by that
// same open.
async function openSeededSongFromItsAlbum(
	page: Page,
	arrange: (songId: string) => Promise<unknown> = async () => {}
): Promise<void> {
	const library = readSeededLibrary();
	const songTitle = `${PHONE_TYPING_SONG_TITLE} ${runMarker()}`;
	await arrange(await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1));
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

	test('the mini-player and the Generate bar step aside while the keyboard is open in a field, and come back after', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page);

		const miniPlayer = page.getByRole('contentinfo');
		const generate = generateButton(page);
		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();

		// A hardware keyboard opens nothing on screen: the bars stay.
		await lyrics.click();
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();

		await showOnScreenKeyboard(page, true);
		await expect(miniPlayer).toBeHidden();
		await expect(generate).toBeHidden();
		await expect(appBar(page)).toBeVisible();
		await expect(lyrics).toBeInViewport();
		expect(await reservedTransportBarRoom(page)).toBe(NO_RESERVED_ROOM);

		// Android's back gesture closes the keyboard and leaves the field focused.
		await showOnScreenKeyboard(page, false);
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();
		await expect(lyrics).toBeFocused();
		expect(await reservedTransportBarRoom(page)).not.toBe(NO_RESERVED_ROOM);

		await showOnScreenKeyboard(page, true);
		await expect(miniPlayer).toBeHidden();
		await lyrics.blur();
		await expect(miniPlayer).toBeVisible();
		await expect(generate).toBeVisible();
		expect(await reservedTransportBarRoom(page)).not.toBe(NO_RESERVED_ROOM);

		await page.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
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

	// #999's T3, T4 and T8 at 390 px, with lyrics long enough that the
	// focused field fills the whole page and leaves no outside to tap (#1017).
	test('playback runs on, the tabs scroll away, and a running generation shows its progress again once the keyboard closes', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page, (songId) =>
			seedRunningGenerationJob(songId, RUNNING_JOB)
		);
		const panel = page.getByRole('tabpanel');
		const miniPlayer = page.getByRole('contentinfo');
		const pause = miniPlayer.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
		const editTab = page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL });

		await page.getByRole('tab', { name: /Takes/ }).click();
		await panel.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) }).click();
		await expect(pause).toBeVisible();
		await editTab.click();
		const progress = panel.getByRole('status');
		await expect(progress.getByText(RUNNING_JOB_TAKE_COUNTER)).toBeVisible();

		const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
		await lyrics.click();
		await showOnScreenKeyboard(page, true);
		// A pasted block leaves the page where it was; typing on at its end is
		// what carries the caret, and the page with it, down past the tabs.
		await lyrics.fill(LONG_LYRICS);
		await page.keyboard.type(LYRICS_TYPED_ON);
		await expect(miniPlayer).toBeHidden();
		await expect(progress).toBeHidden();
		await expect(editTab).not.toBeInViewport();

		await showOnScreenKeyboard(page, false);
		await expect(lyrics).toBeFocused();
		await expect(pause).toBeVisible();
		await expect(progress.getByText(RUNNING_JOB_TAKE_COUNTER)).toBeVisible();
		await expect(progress.getByText(RUNNING_JOB_PERCENT)).toBeVisible();
		await expect(editTab).toBeInViewport();

		guard.assertClean();
	});

	test('the mini-player and the Generate bar come back when a focused field leaves the page', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.getByRole('textbox', { name: /^Lyrics/ }).click();
		// The client-side route change keeps this document, and with it the
		// open keyboard, for every field below.
		await showOnScreenKeyboard(page, true);
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
		await expect(generateButton(page)).toBeVisible();

		await appBar(page).getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		await page.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).click();
		await expect(miniPlayer).toBeHidden();
		await page.keyboard.press('Escape');
		await page.keyboard.press('Escape');
		await expect(miniPlayer).toBeVisible();

		guard.assertClean();
	});

	// Before #1063 the tap's own focus change brought the mini-player back and
	// moved Send up before the tap landed, so only Enter sent. CI's stack
	// configures no co-writer provider: the turn is answered here, and a
	// refusal keeps the chat from reading a conversation the server never
	// stored. The musician starts without a conversation: the one earlier
	// specs leave behind would otherwise be read in while the message is
	// typed, and a read landing after Send replaces the sent exchange (#1151).
	test('a tap on Send with the keyboard open sends the message and keeps the keyboard for the next one', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await page.route(`**${CONVERSATIONS_PATH}`, (route: Route) =>
			route.fulfill({ json: { conversations: [] } })
		);
		const sentMessages: string[] = [];
		await page.route(`**${COWRITER_TURN_PATH}`, (route: Route) => {
			const { message } = route.request().postDataJSON() as { message: string };
			sentMessages.push(message);
			return route.fulfill({
				contentType: 'text/event-stream',
				body: `data: ${JSON.stringify(COWRITER_TURN_REFUSAL_FRAME)}\n\n`
			});
		});
		await openSeededSongFromItsAlbum(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
		const composer = page.getByPlaceholder(COWRITER_COMPOSER_PLACEHOLDER);
		await composer.click();
		await showOnScreenKeyboard(page, true);
		await composer.fill(COWRITER_MESSAGE);
		await expect(miniPlayer).toBeHidden();

		await page.getByRole('button', { name: COWRITER_SEND_LABEL, exact: true }).tap();

		await expect.poll(() => sentMessages).toEqual([COWRITER_MESSAGE]);
		await expect(page.getByText(COWRITER_TURN_REFUSAL)).toBeVisible();
		await expect(composer).toHaveValue('');
		await expect(composer).toBeFocused();
		await expect(miniPlayer).toBeHidden();

		guard.assertClean();
	});

	test('going back from a focused co-writer composer shows the album page with its own app bar', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await openSeededSongFromItsAlbum(page);

		await page.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
		await page.getByPlaceholder(COWRITER_COMPOSER_PLACEHOLDER).click();
		await page.goBack();

		await expect(appBar(page).getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL })).toBeVisible();
		await expect(appBar(page).getByRole('button', { name: APP_NAME })).toBeVisible();
		await expect(page.getByRole('contentinfo')).toBeVisible();

		guard.assertClean();
	});
});
