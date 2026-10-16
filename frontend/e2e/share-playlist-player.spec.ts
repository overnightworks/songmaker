import { expect, test as base, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import type { SharedPlaylistPayload } from '../src/lib/api/types';
import { FlowGuard, boundingBoxes, nameStartingWith } from './helpers';
import {
	PLAYLIST_API,
	PLAYLIST_TITLE,
	PLAYLIST_URL,
	albumTitle,
	coverOf,
	createRealPlaylist,
	mockPlaylist,
	playlistPayload,
	songLyrics,
	songTitle,
	type RealPlaylist
} from './share-playlist-fixtures';

const test = base.extend<{ visitor: Page; realPlaylist: RealPlaylist }>({
	visitor: async ({ browser }, use, testInfo) => {
		const { viewport, isMobile, hasTouch } = testInfo.project.use;
		const context = await browser.newContext({
			storageState: undefined,
			viewport,
			isMobile,
			hasTouch,
			// Independent visitors must not share the public endpoint's six-stream rate window.
			extraHTTPHeaders: {
				'x-forwarded-for': `192.0.2.${createHash('sha256').update(testInfo.testId).digest()[0] || 1}`
			}
		});
		const page = await context.newPage();
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [
				{ path: `${PLAYLIST_API}/stream`, statuses: [503] },
				{ path: '/shared/playlist/', statuses: [404] }
			]
		});
		try {
			await use(page);
		} finally {
			try {
				guard.assertClean();
			} finally {
				await context.close();
			}
		}
	},
	realPlaylist: async ({ page }, use) => {
		const playlist = await createRealPlaylist(page);
		try {
			await use(playlist);
		} finally {
			await playlist.cleanup();
		}
	}
});

const control = (page: Page, name: string) =>
	page.locator('.now-playing.page').getByRole('button', { name, exact: true });
const row = (page: Page, position: number) =>
	page.locator('.queue-row').filter({
		has: page.locator('.queue-title', { hasText: new RegExp(`^${songTitle(position)}$`) })
	});
const slider = (page: Page) =>
	page.locator('.now-playing.page').getByRole('slider', { name: 'Seek playback' });
const bar = (page: Page) => page.locator('footer.player-bar');

async function openMock(page: Page, payload = playlistPayload()) {
	await mockPlaylist(page, payload);
	await page.goto(PLAYLIST_URL);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(PLAYLIST_TITLE);
	await page.evaluate(() => document.fonts.ready);
}

async function selected(page: Page, position: number, total = 3) {
	await expect(row(page, position)).toHaveAttribute('aria-current', 'true');
	await expect(row(page, position).locator('.queue-subtitle')).toHaveText(albumTitle(position));
	await expect(page.locator('.lyrics-heading')).toHaveText(`Lyrics · ${songTitle(position)}`);
	await expect(page.locator('.np-page-lyrics')).toContainText(songLyrics(position));
	await expect(page.locator('.now-playing-line')).toHaveText(
		`Now playing · ${songTitle(position)} · ${position} of ${total}`
	);
}

async function scroll(page: Page, edge: 'top' | 'bottom') {
	await page
		.locator('.shared-page')
		.evaluate(
			(element, edge) => element.scrollTo(0, edge === 'top' ? 0 : element.scrollHeight),
			edge
		);
}

function realCover(playlist: RealPlaylist, position: number): string {
	const cover = playlist.payload.entries[position - 1].album_cover;
	if (!cover) throw new Error(`Fixture song ${position} needs its member album cover`);
	return cover.card;
}

async function currentCover(page: Page, cover: string) {
	const viewport = page.viewportSize();
	if (!viewport) throw new Error('A viewport is required');
	await page.setViewportSize({ width: viewport.width, height: 600 });
	await scroll(page, 'bottom');
	await expect(bar(page)).toBeVisible();
	await expect(bar(page).locator('.track-cover img')).toHaveAttribute('src', cover);
	await expect
		.poll(() =>
			bar(page)
				.locator('.track-cover img')
				.evaluate((image: HTMLImageElement) => image.naturalWidth)
		)
		.toBeGreaterThan(0);
	await bar(page).getByRole('button', { name: 'Back to the player' }).first().click();
	await expect(bar(page)).toBeHidden();
	await page.setViewportSize(viewport);
}

async function screenshot(page: Page, name: string, width: number) {
	const directory = process.env.SHARE_PLAYLIST_SCREENSHOTS;
	if (!directory) return;
	mkdirSync(directory, { recursive: true });
	await page.screenshot({ path: `${directory}/playlist-${name}-${width}.png` });
}

async function startStream(page: Page, playlist: RealPlaylist, start: () => Promise<void>) {
	const manifestResponse = page.waitForResponse(
		(response) =>
			response.url().endsWith(`${playlist.api}/stream`) && response.request().method() === 'POST'
	);
	const audioResponse = page.waitForResponse(
		(response) =>
			/\/shared\/queue-streams\/[^/]+\/audio/.test(response.url()) && response.status() === 206
	);
	await start();
	const manifest = await manifestResponse;
	expect(manifest.ok()).toBeTruthy();
	const payload = await manifest.json();
	expect(payload.tracks).toHaveLength(3);
	const audio = await audioResponse;
	expect(new URL(audio.url()).pathname).toBe(payload.stream_url);
	expect(audio.request().headers()['range']).toMatch(/^bytes=/);
	expect(audio.headers()['content-range']).toMatch(/^bytes /);
	expect(await audio.finished()).toBeNull();
	await expect.poll(async () => Number(await slider(page).inputValue())).toBeGreaterThan(0);
	return payload;
}

test('1374_rule_2 P1: playlist player stands ready before Play', async ({
	visitor: page
}, info) => {
	await openMock(page);
	await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
	await expect(page.locator('.cover-line').first()).toHaveText('Playlist · 3 songs');
	await expect(page.locator('.cover-art .playlist-cover-cell img')).toHaveCount(3);
	await expect(page.locator('.np-page-lyrics')).toContainText(songLyrics(1));
	for (const name of ['Shuffle', 'Previous song', 'Play', 'Next song'])
		await expect(control(page, name)).toBeVisible();
	await expect(slider(page)).toBeVisible();
	await expect(page.locator('.queue-title')).toHaveText([1, 2, 3].map(songTitle));
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'NOW PLAYING', exact: true })).toHaveCount(0);
	const boxes = await boundingBoxes(
		page.getByRole('heading', { level: 1 }),
		page.locator('.now-playing-line'),
		control(page, 'Play'),
		slider(page),
		page.locator('.lyrics-heading'),
		page.getByRole('heading', { name: 'Songs', exact: true })
	);
	for (let i = 1; i < boxes.length; i++) expect(boxes[i].y).toBeGreaterThan(boxes[i - 1].y);
	await screenshot(page, 'before-play', info.project.use.viewport?.width ?? 1440);
});

test('1374_rule_5 P2: numbered rows name their album beneath the title', async ({
	visitor: page
}) => {
	await openMock(page);
	await expect(page.locator('.queue-position')).toHaveText(['1', '2', '3']);
	await expect(page.locator('.queue-duration')).toHaveText(['2:00', '2:00', '2:00']);
	for (const position of [1, 2, 3]) {
		await expect(row(page, position)).toHaveAccessibleName(nameStartingWith(songTitle(position)));
		await expect(row(page, position).locator('.queue-subtitle')).toHaveText(albumTitle(position));
		const [title, subtitle] = await boundingBoxes(
			row(page, position).locator('.queue-title'),
			row(page, position).locator('.queue-subtitle')
		);
		expect(subtitle.y).toBeGreaterThan(title.y);
	}
});

test('1374_rule_5 P3: classic row play pause resume and return stay aligned', async ({
	visitor: page
}) => {
	await openMock(page);
	await row(page, 2).click();
	await selected(page, 2);
	await currentCover(page, coverOf(2).card);
	await row(page, 2).click();
	await expect(control(page, 'Play')).toBeVisible();
	await row(page, 2).click();
	await expect(control(page, 'Pause')).toBeVisible();
	await row(page, 1).click();
	await selected(page, 1);
	await currentCover(page, coverOf(1).card);
});

test('1374_rule_2 P4: previous and next follow songs and stop at endpoints', async ({
	visitor: page
}) => {
	await openMock(page);
	await expect(control(page, 'Previous song')).toBeDisabled();
	await control(page, 'Play').click();
	await control(page, 'Next song').click();
	await selected(page, 2);
	await control(page, 'Next song').click();
	await selected(page, 3);
	await expect(control(page, 'Next song')).toBeDisabled();
	await control(page, 'Previous song').click();
	await selected(page, 2);
	await control(page, 'Previous song').click();
	await selected(page, 1);
	await expect(control(page, 'Previous song')).toBeDisabled();
});

test('1374_rule_14 P5: seek before Play stages a paused song and resumes there', async ({
	visitor: page
}) => {
	await openMock(page);
	await slider(page).fill('45');
	await expect(slider(page)).toHaveValue('45');
	await expect(control(page, 'Play')).toBeVisible();
	await selected(page, 1);
	await control(page, 'Play').click();
	await expect(control(page, 'Pause')).toBeVisible();
	await expect.poll(async () => Number(await slider(page).inputValue())).toBeGreaterThan(45);
});

test('1374_rule_5 P6: shuffle preserves the song across stream classic stream', async ({
	visitor: page,
	realPlaylist
}) => {
	await page.goto(realPlaylist.url);
	await startStream(page, realPlaylist, () => row(page, 2).click());
	const classic = page.waitForResponse(
		(response) =>
			new URL(response.url()).pathname === realPlaylist.payload.entries[1].audio_url &&
			response.ok()
	);
	await control(page, 'Shuffle').click();
	expect((await classic).status()).toBe(206);
	await expect(control(page, 'Disable shuffle')).toHaveAttribute('aria-pressed', 'true');
	await expect(row(page, 2)).toHaveAttribute('aria-current', 'true');
	await expect(row(page, 2).locator('.queue-subtitle')).toHaveText(albumTitle(2));
	await expect(page.locator('.np-page-lyrics')).toContainText(songLyrics(2));
	await currentCover(page, realCover(realPlaylist, 2));
	await startStream(page, realPlaylist, () => control(page, 'Disable shuffle').click());
	await expect(page.locator('.queue-title')).toHaveText([1, 2, 3].map(songTitle));
	await selected(page, 2);
});

async function finishAndReplay(page: Page) {
	const maximum = Number(await slider(page).getAttribute('max'));
	await slider(page).fill((maximum - 0.4).toFixed(1));
	await expect(page.locator('.play-again')).toBeVisible({ timeout: 15000 });
	await expect
		.poll(
			async () =>
				Number(await slider(page).inputValue()) / Number(await slider(page).getAttribute('max'))
		)
		.toBeGreaterThan(0.95);
	await expect(row(page, 3)).toHaveAttribute('aria-current', 'true');
	await page.locator('.play-again').click();
	await selected(page, 1);
	await expect(page.locator('.play-again')).toBeHidden();
	await expect(control(page, 'Pause')).toBeVisible();
}

test('1374_rule_7 P7: classic end stays full and Play again starts song one', async ({
	visitor: page
}) => {
	await openMock(page);
	await row(page, 3).click();
	await expect(control(page, 'Pause')).toBeVisible();
	await finishAndReplay(page);
});

test('1374_rule_10 P8: real stream crosses and jumps between member albums', async ({
	visitor: page,
	realPlaylist
}) => {
	await page.goto(realPlaylist.url);
	await startStream(page, realPlaylist, () => control(page, 'Play').click());
	await selected(page, 1);
	await slider(page).fill((Number(await slider(page).getAttribute('max')) - 0.5).toFixed(1));
	await selected(page, 2);
	await currentCover(page, realCover(realPlaylist, 2));
	await row(page, 3).click();
	await selected(page, 3);
	await currentCover(page, realCover(realPlaylist, 3));
	await row(page, 1).click();
	await selected(page, 1);
});

test('1374_rule_7 P9: real stream ends without wrapping and replays song one', async ({
	visitor: page,
	realPlaylist
}) => {
	await page.goto(realPlaylist.url);
	await startStream(page, realPlaylist, () => control(page, 'Play').click());
	await row(page, 3).click();
	await selected(page, 3);
	await finishAndReplay(page);
});

test('1374_rule_14 P10: unplayable entries are neither staged nor listed', async ({
	visitor: page
}) => {
	const payload = playlistPayload();
	payload.entries[0].audio_url = null;
	await openMock(page, payload);
	await expect(page.locator('.queue-title')).toHaveText([songTitle(2), songTitle(3)]);
	await expect(page.locator('.cover-line').first()).toHaveText('Playlist · 2 songs');
	await expect(page.locator('.np-page-lyrics')).toContainText(songLyrics(2));
	payload.entries.forEach((entry) => {
		entry.audio_url = null;
	});
	await page.reload();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(PLAYLIST_TITLE);
	await expect(page.getByRole('status')).toHaveText('No audio available yet.');
	await expect(page.locator('.now-playing, .queue-row, .np-page-lyrics, .player-bar')).toHaveCount(
		0
	);
});

test('1374_rule_10 P11: missing words and failed covers recover on the next song', async ({
	visitor: page
}) => {
	const payload = playlistPayload();
	payload.entries[0].lyrics = null;
	payload.entries[0].album_cover = null;
	await mockPlaylist(page, payload);
	await page.route(`**${PLAYLIST_API}/album-covers/2?*`, (route) => route.fulfill({ status: 404 }));
	await page.goto(PLAYLIST_URL);
	await page.setViewportSize({ width: page.viewportSize()?.width ?? 1440, height: 600 });
	await expect(page.locator('.lyrics-empty')).toHaveText('No lyrics');
	await row(page, 1).click();
	await scroll(page, 'bottom');
	await expect(bar(page).locator('.track-cover')).toHaveText('J1');
	await row(page, 2).click();
	await scroll(page, 'bottom');
	await expect(bar(page).locator('.track-cover img')).toHaveCount(0);
	await expect(bar(page).locator('.track-cover')).toHaveText('J2');
	await row(page, 3).click();
	await selected(page, 3);
	await currentCover(page, coverOf(3).card);
});

test('1374_rule_16 P12: 24 rows remain reachable with bounded lyrics at full and short heights', async ({
	visitor: page
}) => {
	const payload = playlistPayload(24);
	payload.entries.forEach((entry) => {
		entry.lyrics = Array.from({ length: 300 }, (_, i) => `Long line ${i}`).join('\n');
	});
	await openMock(page, payload);
	for (const height of [page.viewportSize()?.height ?? 900, 600]) {
		await page.setViewportSize({ width: page.viewportSize()?.width ?? 1440, height });
		for (const position of [24, 20]) {
			await row(page, position).scrollIntoViewIfNeeded();
			await expect(row(page, position)).toBeInViewport();
			await row(page, position).click();
			await expect(row(page, position)).toHaveAttribute('aria-current', 'true');
			await expect(control(page, 'Pause')).toBeVisible();
			await expect(page.locator('.now-playing-line')).toContainText(`${position} of 24`);
			const [lyrics] = await boundingBoxes(page.locator('.np-page-lyrics'));
			expect(lyrics.height).toBeLessThanOrEqual(300);
		}
	}
});

test('1374_rule_16 P13: scrolled bar follows the song and returns without history', async ({
	visitor: page
}, info) => {
	await openMock(page, playlistPayload(24));
	await control(page, 'Play').click();
	await control(page, 'Next song').click();
	await selected(page, 2, 24);
	const history = await page.evaluate(() => window.history.length);
	await scroll(page, 'bottom');
	await expect(bar(page)).toBeVisible();
	await expect(bar(page).locator('.track-cover img')).toHaveAttribute('src', coverOf(2).card);
	await screenshot(page, 'scrolled-bar', info.project.use.viewport?.width ?? 1440);
	await bar(page).getByRole('button', { name: 'Pause', exact: true }).click();
	await expect(bar(page).getByRole('button', { name: 'Play', exact: true })).toBeVisible();
	await bar(page).getByRole('button', { name: 'Play', exact: true }).click();
	await expect(bar(page).getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
	const [footer, transport] = await boundingBoxes(
		page.getByRole('button', { name: 'Impressum' }),
		bar(page)
	);
	expect(footer.y + footer.height).toBeLessThanOrEqual(transport.y);
	await bar(page).getByRole('button', { name: 'Back to the player' }).first().click();
	await expect(control(page, 'Pause')).toBeInViewport();
	await expect(bar(page)).toBeHidden();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	expect(await page.evaluate(() => window.history.length)).toBe(history);
});

async function rights(page: Page, payload: SharedPlaylistPayload) {
	await expect(
		page.getByRole('button', { name: /edit|pencil|source|take|library|account/i })
	).toHaveCount(0);
	await expect(page.locator('.queue-take')).toHaveCount(0);
	await expect(page.getByText(/Go to song|\bTake\b|\bv\d+\b/)).toHaveCount(0);
	await expect(page.locator('.queue-title')).toHaveText(
		payload.entries.map((entry) => entry.song_title)
	);
	expect(
		await page
			.locator('.shared-page a')
			.evaluateAll((links) => links.map((link) => link.getAttribute('href')))
	).toEqual(['/']);
}

test('1374_rule_10 P14: uploaded cover mosaic revoke legal and signed-out rights', async ({
	visitor: page,
	realPlaylist
}) => {
	await realPlaylist.setUpload(true);
	await page.goto(realPlaylist.url);
	await expect(page.locator('.cover-art .playlist-cover-image')).toBeVisible();
	await rights(page, realPlaylist.payload);
	await startStream(page, realPlaylist, () => control(page, 'Play').click());
	await rights(page, realPlaylist.payload);
	for (const name of ['Impressum', 'Datenschutz', 'Nutzungsbedingungen']) {
		await page.getByRole('button', { name, exact: true }).click();
		await expect(page.getByRole('dialog', { name: 'Legal information' })).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog')).toHaveCount(0);
	}
	await realPlaylist.setUpload(false);
	await page.reload();
	await expect(page.locator('.cover-art .playlist-cover-image')).toHaveCount(0);
	await expect(page.locator('.cover-art .playlist-cover-cell img')).toHaveCount(3);
	await realPlaylist.revoke();
	await page.reload();
	await expect(page.getByRole('heading', { name: 'Playlist not found' })).toBeVisible();
	await expect(page.locator('.now-playing, .queue-row')).toHaveCount(0);
});
