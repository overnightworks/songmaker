// Spec: REQ-PLAYER-04 -- every take has one menu: Open version (Go to song for an imported take), Repaint, Cover, Use seed, Re-score, Add to… and Share, plus Delete in the editor; Now Playing carries it in its title row. Re-score is disabled while the take re-scores; the Scores carry no control and no Rating; the frame has no Go to song button, so nothing in the docked panel covers another control.
//
// Both shells walk the menu in Now Playing and in the editor; the desktop also walks the docked panel.

import { expect, test, type Locator, type Page } from './coverage-test';
import {
	FlowGuard,
	type FlowGuardOptions,
	MOBILE_VIEWPORT,
	ONLY_IN_SHELL,
	sameOriginHeaders,
	shellOf,
	workspace
} from './helpers';
import { showTab } from './foldedSong';
import { openNowPlayingFromBar, playOpenAlbum, scoreTheTakes } from './play-album';
import { archiveOwnedAlbum, seedSongPhoneSong, seedTakeStripSong } from './seed';
import { words } from '../src/lib/words/en';
import { takeMenuRows } from './take-menu-rows';

const TAKE_SEED = 4127730;
const SCORE_ROUTE = /\/api\/generations\/[^/]+\/score$/;

let guard: FlowGuard;
let albumId: string;
let songTitle: string;
let songId: string;

async function createAlbum(page: Page): Promise<string> {
	const album = await page.request.post('/api/albums', {
		headers: await sameOriginHeaders(page),
		data: { title: `E2E Take menu ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	return ((await album.json()) as { id: string }).id;
}

test.beforeEach(async ({ page }) => {
	albumId = await createAlbum(page);
	// Long enough to wrap onto a second line on a phone and onto several in the dock.
	songTitle = `Wrapping take menu song ${Date.now()}`;
	songId = await seedSongPhoneSong(albumId, songTitle, 1, 2, TAKE_SEED);
});

test.afterEach(async ({ page }) => {
	await page.unrouteAll({ behavior: 'ignoreErrors' });
	await archiveOwnedAlbum(page.request, albumId);
	guard.assertClean();
});

async function openNowPlaying(
	page: Page,
	shell: 'desktop' | 'mobile',
	options?: FlowGuardOptions
): Promise<Locator> {
	guard = new FlowGuard(page, options);
	await page.goto(`/album/${albumId}`);
	await playOpenAlbum(page);
	await openNowPlayingFromBar(page, shell, songTitle);
	const sheetBackdrop = page.locator('.mobile-sheet-backdrop');
	// A song of several takes can open the phone's sheet over the title row.
	if (await sheetBackdrop.isVisible()) await sheetBackdrop.click();
	return page.locator('.now-playing');
}

function menuOf(page: Page): Locator {
	return page.getByRole('dialog', { name: words['takeMenu.label'], exact: true });
}

/** The words of an open menu's rows, hints (the seed, on or off) cut off. */
async function rowWords(menu: Locator): Promise<string[]> {
	const rows = await menu.getByRole('button').allTextContents();
	const known = [
		words['takeMenu.openVersion'],
		words['takeMenu.goToSong'],
		words['takeMenu.repaint'],
		words['takeMenu.cover'],
		words['takeMenu.useSeed'],
		words['takeMenu.rescore'],
		words['takeMenu.addTo'],
		words['takeMenu.share'],
		words['takeMenu.delete']
	];
	return rows.map((row) => known.find((word) => row.trim().startsWith(word)) ?? row.trim());
}

const MENU_ROWS = takeMenuRows(true);

/** Whether a click at the element's centre reaches it, with nothing laid over it. */
async function isOnTop(element: Locator): Promise<boolean> {
	return element.evaluate((own) => {
		const box = own.getBoundingClientRect();
		const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
		return hit !== null && (own === hit || own.contains(hit));
	});
}

test("Now Playing's title row carries the take menu, with no pencil beside it", async ({
	page
}, testInfo) => {
	const surface = await openNowPlaying(page, shellOf(testInfo));
	const titleRow = surface.locator('.title-line');

	await titleRow.getByRole('button', { name: words['takeMenu.label'], exact: true }).click();

	expect(await rowWords(menuOf(page))).toEqual(MENU_ROWS);
	await page.keyboard.press('Escape');
	await expect(menuOf(page)).toHaveCount(0);
	await expect(titleRow.getByRole('button')).toHaveCount(1);
});

test('the editor take row carries the same rows with Delete last', async ({ page }) => {
	guard = new FlowGuard(page);
	await page.goto(`/album/${albumId}`);
	await workspace(page)
		.getByRole('button', { name: words['songRow.openInEditor']({ title: songTitle }) })
		.click();
	await showTab(page, words['songTabs.takes']);

	await workspace(page)
		.locator('.take-row')
		.first()
		.getByRole('button', { name: words['takeMenu.label'], exact: true })
		.click();

	expect(await rowWords(menuOf(page))).toEqual([...MENU_ROWS, words['takeMenu.delete']]);
});

test('Re-score is disabled while the take re-scores and the Scores show the pending word', async ({
	page
}, testInfo) => {
	// The request stays out until the end: the take is re-scoring from the moment it leaves.
	let answer: () => void = () => undefined;
	const answered = new Promise<void>((resolve) => (answer = resolve));
	await page.route(SCORE_ROUTE, async (route) => {
		await answered;
		await route.fulfill({ status: 409, json: { detail: 'No scoring in this test' } });
	});
	await scoreTheTakes(page, songId);
	const surface = await openNowPlaying(page, shellOf(testInfo), {
		refusalsExpectedOn: [{ statuses: [409], path: '/api/generations/' }]
	});
	const menuTrigger = surface
		.locator('.title-line')
		.getByRole('button', { name: words['takeMenu.label'], exact: true });
	await menuTrigger.click();
	const requested = page.waitForRequest(SCORE_ROUTE);

	await menuOf(page).getByRole('button', { name: words['takeMenu.rescore'] }).click();
	await requested;

	await expect(
		surface.getByRole('region', { name: words['nowPlayingScores.heading'] })
	).toContainText(words['nowPlayingScores.rescoring']);
	await menuTrigger.click();
	await expect(
		menuOf(page).getByRole('button', { name: words['takeMenu.rescore'] })
	).toBeDisabled();
	answer();
});

test('the Scores carry no control and no Rating, and the frame has no Go to song', async ({
	page
}, testInfo) => {
	await scoreTheTakes(page, songId);
	const surface = await openNowPlaying(page, shellOf(testInfo));

	const scores = surface.getByRole('region', { name: words['nowPlayingScores.heading'] });
	await expect(scores).toBeVisible();
	await expect(scores.locator('button, a, input')).toHaveCount(0);
	await expect(scores).toContainText(words['nowPlayingScores.lyricsSung']);
	await expect(scores).not.toContainText(words['nowPlayingJudging.rating']);
	await expect(surface.getByRole('button', { name: words['takeMenu.goToSong'] })).toHaveCount(0);
});

test(
	'nothing in the docked panel covers another control or a score',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await scoreTheTakes(page, songId);
		await openNowPlaying(page, 'desktop');
		const docked = page.getByRole('complementary');
		const scores = docked.getByRole('region', { name: words['nowPlayingScores.heading'] });
		await expect(scores).toBeVisible();

		const controls = [
			...(await docked.getByRole('button').all()),
			...(await scores.locator('li').all())
		];
		expect(controls.length).toBeGreaterThan(0);
		for (const control of controls) {
			await control.scrollIntoViewIfNeeded();
			if (!(await control.isVisible())) continue;
			expect(await isOnTop(control), await control.innerText()).toBe(true);
		}
	}
);

test(
	'a judged take with long words keeps the Scores, both tabs and the first Queue row in the dock at 1440x900',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		// An album of its own, so the judged song is the one it starts with.
		await archiveOwnedAlbum(page.request, albumId);
		albumId = await createAlbum(page);
		// Wraps onto two lines in the dock's title.
		const judgedTitle = `Docked judged song whose title runs onto a second line ${Date.now()}`;
		const lyrics = Array.from({ length: 70 }, (_, index) => `Line ${index + 1} of the words`);
		const judgedSongId = await seedTakeStripSong(albumId, judgedTitle, 1, lyrics.join('\n'));
		// A second song fills the Queue beyond the playing one.
		await seedSongPhoneSong(albumId, `Take menu queued song ${Date.now()}`, 1, 1);
		const headers = await sameOriginHeaders(page);
		const song = await page.request.get(`/api/songs/${judgedSongId}`);
		const [take] = ((await song.json()) as { generations: { id: string }[] }).generations;
		for (const [path, data] of [
			['pick', {}],
			['keep', {}],
			['rate', { rating: 72, notes: 'Chorus lands late, the bridge is the keeper' }]
		] as const) {
			const judged = await page.request.post(`/api/generations/${take.id}/${path}`, {
				headers,
				data
			});
			expect(judged.ok(), path).toBe(true);
		}
		await scoreTheTakes(page, judgedSongId);
		guard = new FlowGuard(page);
		await page.goto(`/album/${albumId}`);
		await playOpenAlbum(page);
		const bar = page.getByRole('contentinfo');
		// The seeded takes last seconds: paused, the judged take stays the one playing.
		await bar.getByRole('button', { name: words['transport.pause'], exact: true }).click();
		await expect(bar).toContainText(judgedTitle);
		await openNowPlayingFromBar(page, 'desktop', judgedTitle);
		const docked = page.getByRole('complementary');
		await expect(docked).toContainText(lyrics[lyrics.length - 1]);

		const parts = [
			docked.getByRole('region', { name: words['nowPlayingScores.heading'] }),
			docked.getByRole('tab', { name: words['nowPlaying.queueTab'] }),
			docked.getByRole('tab', { name: words['nowPlaying.takeTab'] }),
			docked.getByRole('tabpanel').getByRole('listitem').first()
		];
		const dock = await docked.evaluate((own) => own.getBoundingClientRect().toJSON() as DOMRect);
		for (const part of parts) {
			await expect(part).toBeInViewport({ ratio: 1 });
			const box = await part.evaluate((own) => own.getBoundingClientRect().toJSON() as DOMRect);
			expect(box.top, String(part)).toBeGreaterThanOrEqual(dock.top);
			expect(box.bottom, String(part)).toBeLessThanOrEqual(dock.bottom);
			expect(await isOnTop(part), String(part)).toBe(true);
		}
	}
);

test(
	'a phone with scores keeps the transport on the first screen at 390x664',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		await page.setViewportSize({ width: MOBILE_VIEWPORT.width, height: 664 });
		// A next song gives the Queue row its Up next line.
		await seedSongPhoneSong(albumId, `Take menu second song ${Date.now()}`, 1, 1);
		await scoreTheTakes(page, songId);
		const surface = await openNowPlaying(page, 'mobile');

		await expect(
			surface.getByRole('region', { name: words['nowPlayingScores.heading'] })
		).toBeVisible();
		expect(
			await surface.locator('.phone-body').evaluate((body) => body.scrollHeight - body.clientHeight)
		).toBeLessThanOrEqual(0);
		await expect(surface.getByRole('button', { name: words['transport.pause'] })).toBeInViewport();
	}
);
