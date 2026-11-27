// Spec: REQ-PLAYER-04 -- in the signed-in player's Now Playing, a judging card in the take column holds Pick, Keep, the rating slider and the note on every surface; they save without a Save button, the rating when the slider is released and the note after a pause in typing and when the field is left.
//
// Both shells walk the flow; the desktop also walks the docked panel and the full surface's card geometry.

import { expect, test, type Page, type Request } from './coverage-test';
import { contrastRatio, expectEmulatedTheme, paintedRgb } from './contrast';
import { FlowGuard, ONLY_IN_SHELL, shellOf } from './helpers';
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

/** The header names the surface only: the kicker is there and the song's title is not. */
async function expectHeaderWithoutTitle(page: Page) {
	const header = page.locator('.np-header');
	await expect(header).toContainText(words['nowPlaying.kicker']);
	await expect(header).not.toContainText(readSeededLibrary().albumTracks[0].songTitle);
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

test(
	'the judging card stands in the docked panel and stays when it is expanded',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const card = await openJudgingCard(page, 'desktop');

		await expect(
			page
				.getByRole('complementary')
				.getByRole('region', { name: words['nowPlayingJudging.label'] })
		).toBeVisible();
		await expectHeaderWithoutTitle(page);

		await page.getByRole('button', { name: words['nowPlaying.expand'], exact: true }).click();

		await expect(page.getByRole('complementary')).toHaveCount(0);
		await expect(card).toBeVisible();
		await expectHeaderWithoutTitle(page);
	}
);

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

test('a pressed pill keeps its label as its name and says its state only in aria-pressed', async ({
	page
}, testInfo) => {
	const card = await openJudgingCard(page, shellOf(testInfo));

	for (const word of ['pick', 'keep'] as const) {
		const name = words[`nowPlayingJudging.${word}`];
		const pill = card.getByRole('button', { name, exact: true });
		const wasPressed = (await pill.getAttribute('aria-pressed')) === 'true';

		await pill.click();

		await expect(pill).toHaveAttribute('aria-pressed', String(!wasPressed));
		await expect(
			card.getByRole('button', { name, pressed: !wasPressed, exact: true })
		).toBeVisible();
		await expect(pill).toHaveAccessibleName(name);

		await pill.click();
		await expect(pill).toHaveAttribute('aria-pressed', String(wasPressed));
	}
});

for (const colorScheme of ['light', 'dark'] as const) {
	test(`the pressed pill labels and the note placeholder read at 4.5:1 in the ${colorScheme} theme`, async ({
		page
	}, testInfo) => {
		await page.emulateMedia({ colorScheme });
		const card = await openJudgingCard(page, shellOf(testInfo));
		await expectEmulatedTheme(page, colorScheme);

		for (const word of ['pick', 'keep'] as const) {
			const pill = card.getByRole('button', {
				name: words[`nowPlayingJudging.${word}`],
				exact: true
			});
			const wasPressed = (await pill.getAttribute('aria-pressed')) === 'true';
			if (!wasPressed) await pill.click();
			await expect(pill).toHaveAttribute('aria-pressed', 'true');
			const { ink, fill } = await pill.evaluate((element) => ({
				ink: getComputedStyle(element).color,
				fill: getComputedStyle(element).backgroundColor
			}));
			expect(
				contrastRatio(await paintedRgb(page, ink), await paintedRgb(page, fill))
			).toBeGreaterThanOrEqual(4.5);
			if (!wasPressed) {
				await pill.click();
				await expect(pill).toHaveAttribute('aria-pressed', 'false');
			}
		}

		const note = card.getByRole('textbox', { name: words['nowPlayingJudging.ratingNotes'] });
		const { placeholder, field } = await note.evaluate((element) => ({
			placeholder: getComputedStyle(element, '::placeholder').color,
			field: getComputedStyle(element).backgroundColor
		}));
		expect(
			contrastRatio(await paintedRgb(page, placeholder), await paintedRgb(page, field))
		).toBeGreaterThanOrEqual(4.5);
	});
}

test(
	'a fine pointer keeps the pills above the compact hitbox height',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const card = await openJudgingCard(page, 'desktop');
		const compact = await page.evaluate(() =>
			Number.parseFloat(
				getComputedStyle(document.documentElement).getPropertyValue('--hitbox-compact')
			)
		);

		for (const word of ['pick', 'keep'] as const) {
			const box = await card
				.getByRole('button', { name: words[`nowPlayingJudging.${word}`], exact: true })
				.boundingBox();
			expect(box?.height).toBeGreaterThan(compact);
		}
	}
);

test(
	'the full desktop card shares the cover column left edge and width',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const card = await openJudgingCard(page, 'desktop');
		await page.getByRole('button', { name: words['nowPlaying.expand'], exact: true }).click();

		const cardBox = await card.boundingBox();
		const coverBox = await page.locator('.cover-art').boundingBox();
		if (!cardBox || !coverBox) throw new Error('Expected a laid out card and cover');
		expect(cardBox.x).toBeCloseTo(coverBox.x, 0);
		expect(cardBox.width).toBeCloseTo(coverBox.width, 0);
	}
);
