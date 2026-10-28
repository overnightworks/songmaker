import { expect, test as base, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { LEGAL_SECTIONS } from '../src/lib/constants/legal';
// 1354_65_A4: playlist transport proofs use the shared-player control owner.
import { control } from './share-album-fixtures';
import type { SharedPlaylistPayload } from '../src/lib/api/types';
import {
	FlowGuard,
	boundingBoxes,
	nameStartingWith,
	ONLY_IN_SHELL,
	type ExpectedRefusal
} from './helpers';
import { loadedImages } from './loaded-images';
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

const test = base.extend<{
	visitor: Page;
	realPlaylist: RealPlaylist;
	expectedRefusals: ExpectedRefusal[];
}>({
	// eslint-disable-next-line no-empty-pattern -- Playwright requires destructuring even for a fixture with no dependencies
	expectedRefusals: async ({}, use) => {
		await use([]);
	},
	visitor: async ({ browser, expectedRefusals }, use, testInfo) => {
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
			refusalsExpectedOn: expectedRefusals
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
	await page.setViewportSize({ width: 390, height: 600 });
	await expect
		.poll(async () => {
			const [lyrics, songs] = await Promise.all([
				page.locator('.np-page-lyrics').boundingBox(),
				page.locator('.np-page-songs').boundingBox()
			]);
			return lyrics !== null && songs !== null && songs.y >= lyrics.y + lyrics.height;
		})
		.toBe(true);
	await scroll(page, 'bottom');
	await expect(bar(page)).toBeVisible();
	await expect(bar(page).locator('.track-cover img')).toHaveAttribute('src', cover);
	await loadedImages(bar(page).locator('.track-cover img'));
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

async function requestStream(page: Page, playlist: RealPlaylist, start: () => Promise<void>) {
	const manifestResponse = page.waitForResponse(
		(response) =>
			response.url().endsWith(`${playlist.api}/stream`) && response.request().method() === 'POST'
	);
	await start();
	const manifest = await manifestResponse;
	expect(manifest.ok()).toBeTruthy();
	const payload = await manifest.json();
	expect(payload.tracks).toHaveLength(3);
	return payload;
}

async function startStream(page: Page, playlist: RealPlaylist, start: () => Promise<void>) {
	const audioResponse = page.waitForResponse(
		(response) =>
			/\/shared\/queue-streams\/[^/]+\/audio/.test(response.url()) && response.status() === 206
	);
	const payload = await requestStream(page, playlist, start);
	const audio = await audioResponse;
	expect(new URL(audio.url()).pathname).toBe(payload.stream_url);
	expect(audio.request().headers()['range']).toMatch(/^bytes=/);
	expect(audio.headers()['content-range']).toMatch(/^bytes /);
	expect(await audio.finished()).toBeNull();
	await expect.poll(async () => Number(await slider(page).inputValue())).toBeGreaterThan(0);
	return payload;
}

for (const height of [900, 600]) {
	test(
		`1374_rule_11 P1 at ${height}: playlist player stands ready before Play`,
		{ tag: height === 600 ? ONLY_IN_SHELL.desktop : [] },
		async ({ visitor: page, expectedRefusals }, info) => {
			expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
			if (info.project.name === 'desktop') await page.setViewportSize({ width: 1440, height });
			await openMock(page);
			await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
			await expect(page.locator('.cover-line').first()).toHaveText(/^Playlist · 3 songs\b/);
			await expect(page.locator('.cover-art .playlist-cover-cell img')).toHaveCount(3);
			await loadedImages(page.locator('.cover-art .playlist-cover-cell img'));
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
			const vertical = (page.viewportSize()?.width ?? 1440) <= 768 ? boxes : boxes.slice(0, 4);
			for (let i = 1; i < vertical.length; i++)
				expect(vertical[i].y).toBeGreaterThan(vertical[i - 1].y);
			if ((page.viewportSize()?.width ?? 1440) > 768) {
				expect(boxes[3].x + boxes[3].width).toBeLessThanOrEqual(boxes[4].x);
				expect(boxes[4].x + boxes[4].width).toBeLessThanOrEqual(boxes[5].x);
			}
			const [artwork] = await boundingBoxes(page.locator('.cover-art'));
			expect(artwork.width).toBeGreaterThan(100);
			expect(artwork.height).toBeCloseTo(artwork.width, 0);
			const [lyrics] = await boundingBoxes(page.locator('.np-page-lyrics'));
			if (info.project.name === 'desktop')
				expect(lyrics.y + lyrics.height).toBeLessThanOrEqual(height);
			await screenshot(
				page,
				`before-play-${page.viewportSize()?.height ?? 900}`,
				info.project.use.viewport?.width ?? 1440
			);
			await row(page, 2).click();
			await selected(page, 2);
			await expect(page.getByRole('heading', { level: 1 })).toHaveText(PLAYLIST_TITLE);
		}
	);
}

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
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
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
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
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
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
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
	const initialStream = await startStream(page, realPlaylist, () => control(page, 'Play').click());
	await selected(page, 1);
	await currentCover(page, realCover(realPlaylist, 1));
	await page.evaluate(() => {
		Math.random = () => 0;
	});
	const classic = page.waitForResponse(
		(response) =>
			new URL(response.url()).pathname === realPlaylist.payload.entries[0].audio_url &&
			response.ok()
	);
	await control(page, 'Shuffle').click();
	const classicResponse = await classic;
	expect(classicResponse.status()).toBe(206);
	expect(await classicResponse.finished()).toBeNull();
	await expect(control(page, 'Disable shuffle')).toHaveAttribute('aria-pressed', 'true');
	await expect(page.locator('.queue-title')).not.toHaveText([1, 2, 3].map(songTitle));
	await selected(page, 1);
	for (const position of [1, 2, 3]) {
		await expect(row(page, position).locator('.queue-subtitle')).toHaveText(albumTitle(position));
	}
	await currentCover(page, realCover(realPlaylist, 1));
	// Chromium can reuse the loaded media for this URL without another audio response.
	const restoredStream = await requestStream(page, realPlaylist, () =>
		control(page, 'Disable shuffle').click()
	);
	// The server reuses the snapshot when the original queue order returns.
	expect(restoredStream.stream_url).toBe(initialStream.stream_url);
	await expect(control(page, 'Pause')).toBeVisible();
	const resumedAt = Number(await slider(page).inputValue());
	await expect.poll(async () => Number(await slider(page).inputValue())).toBeGreaterThan(resumedAt);
	await expect(page.locator('.queue-title')).toHaveText([1, 2, 3].map(songTitle));
	await selected(page, 1);
	await currentCover(page, realCover(realPlaylist, 1));
});

async function finishAndReplay(page: Page, order = [1, 2, 3]) {
	const maximum = Number(await slider(page).getAttribute('max'));
	await slider(page).fill((maximum - 0.4).toFixed(1));
	await expect(page.locator('.play-again')).toBeVisible({ timeout: 15000 });
	const step = Number(await slider(page).getAttribute('step'));
	await expect
		.poll(
			async () =>
				Number(await slider(page).getAttribute('max')) - Number(await slider(page).inputValue())
		)
		.toBeLessThan(step);
	const [line, played] = await boundingBoxes(
		page.locator('.now-playing.page .seek-line'),
		page.locator('.now-playing.page .seek-played')
	);
	expect(played.width).toBeCloseTo(line.width, 1);
	await expect(row(page, order[order.length - 1])).toHaveAttribute('aria-current', 'true');
	await page.locator('.play-again').click();
	await expect(row(page, order[0])).toHaveAttribute('aria-current', 'true');
	await expect(page.locator('.np-page-lyrics')).toContainText(songLyrics(order[0]));
	await expect(page.locator('.play-again')).toBeHidden();
	await expect(control(page, 'Pause')).toBeVisible();
}

test('1374_rule_7 P7: classic replay starts the first entry with shuffle off and on', async ({
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
	await openMock(page);
	await row(page, 3).click();
	await expect(control(page, 'Pause')).toBeVisible();
	await finishAndReplay(page);
	await row(page, 2).click();
	await selected(page, 2);
	await page.evaluate(() => {
		Math.random = () => 0;
	});
	await control(page, 'Shuffle').click();
	await expect(control(page, 'Disable shuffle')).toHaveAttribute('aria-pressed', 'true');
	const titles = await page.locator('.queue-title').allTextContents();
	const order = titles.map((title) => {
		const position = [1, 2, 3].find((position) => songTitle(position) === title);
		if (position === undefined) throw new Error(`Unexpected queue title: ${title}`);
		return position;
	});
	expect(order[0]).toBe(2);
	for (const position of order.slice(1)) {
		const maximum = Number(await slider(page).getAttribute('max'));
		await slider(page).fill((maximum - 0.4).toFixed(1));
		await expect(row(page, position)).toHaveAttribute('aria-current', 'true');
	}
	await finishAndReplay(page, order);
	await expect(page.locator('.queue-title')).toHaveText(titles);
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
	await expect(page.locator('.cover-line').first()).toHaveText(/^Playlist · 2 songs\b/);
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
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
	expectedRefusals.push({ path: `${PLAYLIST_API}/album-covers/2`, statuses: [404] });
	const payload = playlistPayload();
	payload.entries[0].lyrics = null;
	payload.entries[0].album_cover = null;
	await mockPlaylist(page, payload);
	await page.route(`**${PLAYLIST_API}/album-covers/2?*`, (route) => route.fulfill({ status: 404 }));
	await page.goto(PLAYLIST_URL);
	await page.setViewportSize({ width: 390, height: 600 });
	await expect(page.locator('.lyrics-empty')).toHaveText('No lyrics');
	await row(page, 1).click();
	await scroll(page, 'bottom');
	await expect(bar(page).locator('.track-cover')).toHaveText('J1');
	await row(page, 2).click();
	await selected(page, 2);
	await scroll(page, 'bottom');
	await expect(bar(page)).toBeVisible();
	await expect(bar(page).locator('.track-cover img')).toHaveCount(0);
	await expect(bar(page).locator('.track-cover')).toHaveText('J2');
	await row(page, 3).click();
	await selected(page, 3);
	await currentCover(page, coverOf(3).card);
});

test('1374_rule_16 P12: 24 rows remain reachable with bounded lyrics at full and short heights', async ({
	visitor: page,
	expectedRefusals
}) => {
	expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
	const payload = playlistPayload(24);
	payload.entries.forEach((entry) => {
		entry.whisper_cues = Array.from({ length: 300 }, (_, i) => ({
			text: `Long line ${i}`,
			start: i * 0.4,
			end: (i + 1) * 0.4
		}));
		entry.lyrics = entry.whisper_cues.map((cue) => cue.text).join('\n');
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
			await expect(page.locator('.lyrics-line').first()).toBeVisible();
			// A Follow pressed during the smooth PageDown scroll is re-paused by its tail (#1374); wait for the scroll to end first.
			const readerScrolled = await page.locator('.lyrics').evaluateHandle((box) => ({
				ended: new Promise<void>((resolve) =>
					box.addEventListener('scrollend', () => resolve(), { once: true })
				)
			}));
			await page.locator('.lyrics').press('PageDown');
			await readerScrolled.evaluate(({ ended }) => ended);
			await readerScrolled.dispose();
			const follow = page.getByRole('button', { name: 'Follow', exact: true });
			await expect(follow).toBeInViewport({ ratio: 1 });
			await follow.click();
			await expect(follow).toBeHidden();
			const [lyrics] = await boundingBoxes(page.locator('.np-page-lyrics'));
			expect(lyrics.height).toBeLessThanOrEqual(height);
			if ((page.viewportSize()?.width ?? 1440) > 768) {
				await expect(control(page, 'Pause')).toBeInViewport({ ratio: 1 });
				expect(lyrics.y).toBeGreaterThanOrEqual(0);
				expect(lyrics.y + lyrics.height).toBeLessThanOrEqual(height);
				await expect(bar(page)).toBeHidden();
			}
			expect(
				await page.locator('.shared-page').evaluate((root) => root.scrollWidth <= root.clientWidth)
			).toBe(true);
		}
	}
});

for (const height of [900, 600]) {
	test(
		`1374_rule_11 P13 scrolling at ${height} keeps desktop transport and phone return available`,
		{ tag: height === 600 ? ONLY_IN_SHELL.desktop : [] },
		async ({ visitor: page, expectedRefusals }, info) => {
			expectedRefusals.push({ path: `${PLAYLIST_API}/stream`, statuses: [404] });
			if (info.project.name === 'desktop') await page.setViewportSize({ width: 1440, height });
			await openMock(page, playlistPayload(24));
			await control(page, 'Play').click();
			await control(page, 'Next song').click();
			await selected(page, 2, 24);
			const history = await page.evaluate(() => window.history.length);
			await scroll(page, 'bottom');
			if (info.project.name === 'desktop') {
				await expect(control(page, 'Pause')).toBeInViewport({ ratio: 1 });
				await expect(bar(page)).toBeHidden();
				return;
			}
			await expect(bar(page)).toBeVisible();
			await expect(bar(page).locator('.track-cover img')).toHaveAttribute('src', coverOf(2).card);
			await loadedImages(bar(page).locator('.track-cover img'));
			await screenshot(page, 'scrolled-bar', info.project.use.viewport?.width ?? 1440);
			await bar(page).getByRole('button', { name: 'Pause', exact: true }).click();
			await expect(bar(page).getByRole('button', { name: 'Play', exact: true })).toBeVisible();
			await bar(page).getByRole('button', { name: 'Play', exact: true }).click();
			await expect(bar(page).getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
			const [footer, transport] = await boundingBoxes(
				page.getByRole('link', { name: 'Impressum' }),
				bar(page)
			);
			expect(footer.y + footer.height).toBeLessThanOrEqual(transport.y);
			await bar(page).getByRole('button', { name: 'Back to the player' }).first().click();
			await expect(control(page, 'Pause')).toBeInViewport();
			await expect(bar(page)).toBeHidden();
			await expect(page.getByRole('dialog')).toHaveCount(0);
			expect(await page.evaluate(() => window.history.length)).toBe(history);
		}
	);
}

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
	).toEqual(['/', ...LEGAL_SECTIONS.map(({ href }) => href)]);
}

test('1374_rule_10 P14: uploaded cover mosaic revoke legal and signed-out rights', async ({
	visitor: page,
	realPlaylist,
	expectedRefusals
}) => {
	await realPlaylist.setUpload(true);
	await page.goto(realPlaylist.url);
	await expect(page.locator('.cover-art .playlist-cover-image')).toBeVisible();
	await loadedImages(page.locator('.cover-art .playlist-cover-image'));
	await rights(page, realPlaylist.payload);
	await startStream(page, realPlaylist, () => control(page, 'Play').click());
	await rights(page, realPlaylist.payload);
	await realPlaylist.setUpload(false);
	await page.reload();
	await expect(page.locator('.cover-art .playlist-cover-image')).toHaveCount(0);
	await expect(page.locator('.cover-art .playlist-cover-cell img')).toHaveCount(3);
	await loadedImages(page.locator('.cover-art .playlist-cover-cell img'));
	await realPlaylist.revoke();
	expectedRefusals.push({ path: realPlaylist.api, statuses: [404] });
	await page.reload();
	await expect(page.getByRole('heading', { name: 'Playlist not found' })).toBeVisible();
	await expect(page.locator('.now-playing, .queue-row')).toHaveCount(0);
});
