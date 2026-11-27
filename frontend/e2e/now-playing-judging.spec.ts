// Spec: REQ-PLAYER-04 -- in the signed-in player's Now Playing, a judging card in the take column holds Pick, Keep, the rating slider and the note on every surface; they save without a Save button, the rating when the slider is released and the note after a pause in typing and when the field is left.
//
// Both shells walk the flow; the desktop also walks the docked panel.

import { expect, test, type Page, type Request } from './coverage-test';
import { FlowGuard, shellOf } from './helpers';
import { openNowPlayingFromBar, playOpenAlbum } from './play-album';
import { readSeededLibrary } from './seed';
import { words } from '../src/lib/words/en';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

async function openJudgingCard(page: Page, shell: 'desktop' | 'mobile') {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	await playOpenAlbum(page);
	await openNowPlayingFromBar(page, shell, library.albumTracks[0].songTitle);
	return page.getByRole('region', { name: words['nowPlayingJudging.label'] });
}

function isRating(request: Request): boolean {
	return request.method() === 'POST' && request.url().endsWith('/rate');
}

test('the judging card stands in the take column with no Save button', async ({
	page
}, testInfo) => {
	const card = await openJudgingCard(page, shellOf(testInfo));

	await expect(card.getByRole('button', { name: words['nowPlayingJudging.pick'] })).toBeVisible();
	await expect(card.getByRole('button', { name: words['nowPlayingJudging.keep'] })).toBeVisible();
	await expect(card.getByRole('slider', { name: words['nowPlayingJudging.rating'] })).toBeVisible();
	await expect(
		card.getByRole('textbox', { name: words['nowPlayingJudging.ratingNotes'] })
	).toBeVisible();
	await expect(card.getByRole('button', { name: /save/i })).toHaveCount(0);
	for (const word of ['pick', 'keep', 'rating'] as const) {
		await expect(card.getByText(words[`nowPlayingJudging.${word}`], { exact: true })).toBeVisible();
	}
});

test('the judging card stands in the docked panel and stays when it is expanded', async ({
	page
}, testInfo) => {
	test.skip(shellOf(testInfo) !== 'desktop', 'the phone has no docked panel');
	const card = await openJudgingCard(page, 'desktop');

	await expect(
		page.getByRole('complementary').getByRole('region', { name: words['nowPlayingJudging.label'] })
	).toBeVisible();

	await page.getByRole('button', { name: words['nowPlaying.expand'], exact: true }).click();

	await expect(page.getByRole('complementary')).toHaveCount(0);
	await expect(card).toBeVisible();
});

test('releasing the slider saves the rating without a toast', async ({ page }, testInfo) => {
	const card = await openJudgingCard(page, shellOf(testInfo));
	const slider = card.getByRole('slider', { name: words['nowPlayingJudging.rating'] });
	await slider.focus();
	const saved = page.waitForRequest(isRating);

	await slider.press('ArrowRight');

	const request = await saved;
	expect(request.postDataJSON()).toMatchObject({ rating: expect.any(Number) });
	await request.response();
	await expect(page.getByRole('alert')).toHaveCount(0);
});

test('a pause in typing saves the note and leaving the field saves the rest', async ({
	page
}, testInfo) => {
	const card = await openJudgingCard(page, shellOf(testInfo));
	const note = card.getByRole('textbox', { name: words['nowPlayingJudging.ratingNotes'] });
	const pauseSaved = page.waitForRequest(isRating);

	await note.fill('Loved the bridge');

	expect((await pauseSaved).postDataJSON()).toMatchObject({ notes: 'Loved the bridge' });

	const leaveSaved = page.waitForRequest(isRating);
	await note.pressSequentially(' and the end');
	await note.blur();

	expect((await leaveSaved).postDataJSON()).toMatchObject({
		notes: 'Loved the bridge and the end'
	});
	await expect(note).toHaveValue('Loved the bridge and the end');
});
