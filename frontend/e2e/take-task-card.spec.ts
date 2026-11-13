// The take's Repaint and Cover open a task card under that take (#1912, S4 of
// #1804): it sends one repaint or cover request with the card's values, stays
// open until its cross removes it, never opens the Recipe, and the page
// scrolls as one. The job endpoints are answered here, so no worker is needed.
// With a card open the Recipe has no Repaint row and the header Generate stays
// plain (#1923, S4 and S8). Both projects run it: 390 px (Takes tab) and 1440 px.

import { expect, test, type Locator, type Page } from './coverage-test';
import { EDITOR_GENERATE_LABEL } from '../src/lib/constants/song';
import { sameOriginHeaders, shellOf } from './helpers';
import { archiveOwnedAlbum, seedSongPhoneSong } from './seed';
import { words } from '../src/lib/words/en';

const SONG_TITLE = 'Take task card cells';
const TAKE_COUNT = 3;
const QUEUED_JOB = { id: 'e2e-task-job', type: 'generate', status: 'queued', progress: 0 };

async function onOwnTakes(page: Page, flow: () => Promise<void>): Promise<void> {
	const headers = await sameOriginHeaders(page);
	const album = await page.request.post('/api/albums', {
		headers,
		data: { title: `E2E Take task card ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	const { id: albumId } = (await album.json()) as { id: string };
	try {
		const songId = await seedSongPhoneSong(albumId, SONG_TITLE, 1, TAKE_COUNT);
		const song = await page.request.get(`/api/songs/${songId}`);
		const { slug } = (await song.json()) as { slug: string };
		await page.goto(`/album/${albumId}/${slug}`);
		await expect(page.getByRole('heading', { name: SONG_TITLE, exact: true })).toBeVisible();
		await flow();
	} finally {
		await archiveOwnedAlbum(page.request, albumId);
	}
}

function openVerb(page: Page, verb: string): Promise<void> {
	return (async () => {
		await page
			.locator('.take-row')
			.first()
			.getByRole('button', { name: words['takeMenu.label'] })
			.click();
		await page
			.getByRole('dialog', { name: words['takeMenu.label'] })
			.getByRole('button', { name: verb })
			.click();
	})();
}

function card(page: Page): Locator {
	return page.locator('.task');
}

test('Repaint opens a card under the take and its button sends the range (S4, #1912 acceptance 1, 2, 4)', async ({
	page
}, testInfo) => {
	await onOwnTakes(page, async () => {
		if (shellOf(testInfo) === 'mobile') {
			await page.getByRole('tab', { name: new RegExp(words['songTabs.takes']) }).click();
		}
		await openVerb(page, words['takeTask.repaint']);
		await expect(card(page)).toHaveCount(1);
		await expect(page.locator('.take-row').first().locator('+ .task')).toBeVisible();
		await expect(
			page.getByRole('region', { name: words['recipe.panel'], exact: true })
		).toHaveCount(0);

		const request = page.waitForRequest(/\/api\/generations\/[^/]+\/repaint$/);
		await page.route(/\/api\/generations\/[^/]+\/repaint$/, (route) =>
			route.fulfill({ json: QUEUED_JOB })
		);
		await card(page).locator('.task-foot button').click();
		const body = (await request).postDataJSON() as Record<string, unknown>;
		expect(body).toMatchObject({ repainting_start: 0, repainting_end: 1 });
		await expect(card(page)).toHaveCount(1);

		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth > window.innerWidth
		);
		expect(overflow).toBe(false);
		const ownScrollbar = await card(page).evaluate((el) => el.scrollHeight > el.clientHeight);
		expect(ownScrollbar).toBe(false);

		await card(page).getByRole('button', { name: words['takeTask.close'] }).click();
		await expect(card(page)).toHaveCount(0);
	});
});

test('Cover swaps the card and its button sends the cover request (S4, #1912 acceptance 3, 4, 6)', async ({
	page
}, testInfo) => {
	await onOwnTakes(page, async () => {
		if (shellOf(testInfo) === 'mobile') {
			await page.getByRole('tab', { name: new RegExp(words['songTabs.takes']) }).click();
		}
		await openVerb(page, words['takeTask.repaint']);
		await openVerb(page, words['takeTask.cover']);
		await expect(card(page)).toHaveCount(1);
		await expect(card(page).locator('.what')).toHaveText(words['takeTask.cover']);

		const trackWidths = await card(page)
			.locator('input[type="range"]')
			.evaluateAll((inputs) => inputs.map((input) => input.getBoundingClientRect().width));
		expect(trackWidths.length).toBeGreaterThan(1);
		for (const width of trackWidths) {
			expect(width).toBeGreaterThanOrEqual(Math.max(...trackWidths) - 4);
		}

		const request = page.waitForRequest(/\/api\/generations\/[^/]+\/cover$/);
		await page.route(/\/api\/generations\/[^/]+\/cover$/, (route) =>
			route.fulfill({ json: QUEUED_JOB })
		);
		await card(page).locator('.task-foot button').click();
		const body = (await request).postDataJSON() as Record<string, unknown>;
		expect(body).toHaveProperty('audio_cover_strength');
	});
});

test('With a card open the Recipe holds no Repaint row, no Off and no Source bar (S8, #1923 acceptance 1)', async ({
	page
}, testInfo) => {
	const mobile = shellOf(testInfo) === 'mobile';
	await onOwnTakes(page, async () => {
		if (mobile) await page.getByRole('tab', { name: new RegExp(words['songTabs.takes']) }).click();
		await openVerb(page, words['takeTask.repaint']);
		await expect(card(page)).toHaveCount(1);
		if (mobile) await page.getByRole('tab', { name: new RegExp(words['songTabs.edit']) }).click();
		await page.locator('.recipe-line').click();
		const recipe = page.getByRole('region', { name: words['recipe.panel'], exact: true });
		await expect(recipe).toBeVisible();
		await expect(recipe).not.toContainText(words['takeTask.repaint']);
		await expect(recipe).not.toContainText('Off');
		await expect(recipe).not.toContainText('Source');
	});
});

test('The header Generate stays plain with a card open and sends no repaint (S4, #1923 acceptance 3)', async ({
	page
}, testInfo) => {
	const mobile = shellOf(testInfo) === 'mobile';
	await onOwnTakes(page, async () => {
		if (mobile) await page.getByRole('tab', { name: new RegExp(words['songTabs.takes']) }).click();
		await openVerb(page, words['takeTask.repaint']);
		await expect(card(page)).toHaveCount(1);
		if (mobile) await page.getByRole('tab', { name: new RegExp(words['songTabs.edit']) }).click();

		const sent: string[] = [];
		page.on('request', (request) => {
			if (request.method() === 'POST') sent.push(new URL(request.url()).pathname);
		});
		const request = page.waitForRequest(/\/api\/songs\/[^/]+\/generate$/);
		await page.route(/\/api\/songs\/[^/]+\/generate$/, (route) =>
			route.fulfill({ json: QUEUED_JOB })
		);
		const generate = page.getByRole('button', { name: EDITOR_GENERATE_LABEL, exact: true });
		await expect(generate).toBeEnabled();
		await generate.click();
		await request;
		expect(sent.filter((path) => /\/(repaint|cover)$/.test(path))).toEqual([]);
		if (mobile) await page.getByRole('tab', { name: new RegExp(words['songTabs.takes']) }).click();
		await expect(card(page)).toHaveCount(1);
	});
});
