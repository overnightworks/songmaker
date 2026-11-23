// A tap on an editor take row plays that take and the listener stays on the
// song (#3419): the row has no ▶, the playing row shows the equalizer, a tap on
// it pauses, Now Playing stays closed, and Ctrl or ⌘ with the click ticks the
// take instead of playing it. Both shells: the row is the same on the phone's
// Takes tab and in the desktop workspace.

import { expect, test, type Page } from './coverage-test';
import { FlowGuard, shellOf, workspace } from './helpers';
import { createAlbum, showTab } from './foldedSong';
import { archiveOwnedAlbum, seedTakeStripSong } from './seed';
import { words } from '../src/lib/words/en';

const TAKE_COUNT = 3;
const SONG_TITLE = 'Take tap song';
const TAKE_TAP_FLOW_API_REQUEST_BUDGET = 40;

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Take-tap flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(TAKE_TAP_FLOW_API_REQUEST_BUDGET);
});

async function openTakesOf(page: Page, albumId: string): Promise<void> {
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: words['songRow.openInEditor']({ title: SONG_TITLE }) })
		.click();
	await showTab(page, words['songTabs.takes']);
	await expect(workspace(page).locator('.take-row')).toHaveCount(TAKE_COUNT);
}

test('a tap plays the take and stays on the song, a tap on the playing row pauses', async ({
	page
}, testInfo) => {
	const albumId = await createAlbum(page);
	try {
		await seedTakeStripSong(albumId, SONG_TITLE, TAKE_COUNT);
		await openTakesOf(page, albumId);
		const rows = workspace(page).locator('.take-row');
		const equalizer = workspace(page).getByRole('img', { name: words['playingMark.playing'] });

		await expect(rows.locator('.play-btn')).toHaveCount(0);
		await rows.first().locator('.take-summary').click();

		await expect(rows.first()).toHaveClass(/playing/);
		await expect(equalizer).toHaveCount(1);
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(page.getByRole('heading', { name: SONG_TITLE, exact: true })).toBeVisible();
		if (shellOf(testInfo) === 'mobile') {
			await expect(
				page.getByText(words['nowPlaying.fromSource']({ title: SONG_TITLE }))
			).toBeVisible();
		}

		await rows.first().locator('.take-summary').click();
		await expect(equalizer).toHaveClass(/paused/);
		await expect(equalizer).toHaveCount(1);
	} finally {
		await archiveOwnedAlbum(page.request, albumId);
	}
});

test('Ctrl or ⌘ with the click ticks the take and plays nothing', async ({ page }) => {
	const albumId = await createAlbum(page);
	try {
		await seedTakeStripSong(albumId, SONG_TITLE, TAKE_COUNT);
		await openTakesOf(page, albumId);
		const rows = workspace(page).locator('.take-row');

		await rows
			.nth(1)
			.locator('.take-summary')
			.click({ modifiers: ['ControlOrMeta'] });

		await expect(workspace(page).locator('.selection-toolbar')).toContainText(
			words['takesList.selectedCount'](1)
		);
		await expect(rows.nth(1).locator('.select-btn')).toHaveAttribute('aria-pressed', 'true');
		await expect(
			workspace(page).getByRole('img', { name: words['playingMark.playing'] })
		).toHaveCount(0);
	} finally {
		await archiveOwnedAlbum(page.request, albumId);
	}
});
