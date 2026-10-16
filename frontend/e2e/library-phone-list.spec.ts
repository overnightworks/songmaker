import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	FlowGuard,
	LIBRARY_PATH,
	LIBRARY_URL,
	observePlayingAudio,
	ONLY_IN_SHELL,
	playingAudioState,
	SUCCESSOR_TAKES_TEST_TIMEOUT_MS,
	workspace
} from './helpers';
import {
	archivePhoneLibrary,
	BASE_URL,
	createAccount,
	seedPhoneLibrary,
	type PhoneLibraryFixture
} from './seed';

let guard: FlowGuard;
let fixture: PhoneLibraryFixture;
let account: APIRequestContext;

const screenshotDirectory = process.env.PHONE_LIBRARY_SCREENSHOTS;
async function screenshot(page: Page, name: string): Promise<void> {
	if (!screenshotDirectory) return;
	mkdirSync(screenshotDirectory, { recursive: true });
	await page.screenshot({ path: path.join(screenshotDirectory, `${name}.png`) });
}

function takePathsOf(albumId: string): string[] {
	return fixture.tracks[albumId].map((track) => track.audioPath);
}

function row(page: Page, title: string): Locator {
	return workspace(page)
		.locator('.wall-tile')
		.filter({ has: page.getByRole('button', { name: `Open album ${title}`, exact: true }) });
}

async function expectRows(page: Page): Promise<void> {
	const rows = workspace(page).locator('.wall-tile');
	await expect(rows).toHaveCount(43);
	const boxes = await rows.evaluateAll((elements) =>
		elements.map((el) => {
			const box = el.getBoundingClientRect();
			return { x: box.x, width: box.width, height: box.height, top: box.top };
		})
	);
	expect(
		boxes.every((box) => box.height === 58 && box.x === boxes[0].x && box.width === boxes[0].width)
	).toBe(true);
	for (let index = 1; index < boxes.length; index++)
		expect(boxes[index].top - boxes[index - 1].top).toBe(58);
	await expect(rows.locator('.tile-subtitle')).toHaveText(
		fixture.albums.map((album) => `${album.count} ${album.count === 1 ? 'song' : 'songs'}`)
	);
}

test.beforeEach(async ({ page, request, playwright }) => {
	test.setTimeout(SUCCESSOR_TAKES_TEST_TIMEOUT_MS);
	guard = new FlowGuard(page);
	const credentials = { username: `e2e-phone-${randomUUID()}`, password: randomUUID() };
	await createAccount(request, credentials.username, credentials.password);
	account = await playwright.request.newContext({ baseURL: BASE_URL });
	fixture = await seedPhoneLibrary(account, credentials);
	await page.context().clearCookies();
	await page.context().addCookies((await account.storageState()).cookies);
	await observePlayingAudio(page);
});

test.afterEach(async () => {
	try {
		guard.assertClean();
	} finally {
		if (fixture && account) await archivePhoneLibrary(account, fixture);
		await account?.dispose();
	}
});

test(
	'1354_rule_10 1354_rule_11 1354_rule_13: P1–P6 phone Library rows',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const [empty, archived, playable] = fixture.albums;
		const long = fixture.albums[41];
		const last = fixture.albums[42];
		const songsRead: string[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname === '/api/songs' && url.searchParams.has('album_id'))
				songsRead.push(request.url());
		});
		await page.goto(LIBRARY_PATH);
		await expectRows(page);
		expect(songsRead).toHaveLength(0);
		await expect(row(page, empty.title).locator('.tile-cover')).toBeVisible();
		await expect(row(page, empty.title).getByRole('button')).toHaveCount(1);
		await expect(row(page, archived.title).locator('.tile-subtitle')).toHaveText('1 song');
		await expect(row(page, archived.title).getByRole('button')).toHaveCount(1);
		await expect(page.getByText('No takes', { exact: true })).toHaveCount(0);
		const spacer = row(page, empty.title).locator('.row-play-spacer');
		await expect(spacer).toHaveAttribute('aria-hidden', 'true');
		const spacerBox = await spacer.boundingBox();
		expect(spacerBox?.width).toBe(44);
		expect(spacerBox?.height).toBe(44);
		const textRight = async (title: string) =>
			row(page, title)
				.locator('.tile-meta')
				.evaluate((el) => el.getBoundingClientRect().right);
		expect(await textRight(empty.title)).toBe(await textRight(playable.title));
		await screenshot(page, 'ordinary');
		await row(page, empty.title).getByRole('button').click();
		await expect(
			workspace(page).getByRole('heading', { name: empty.title, exact: true })
		).toBeVisible();
		await page.getByRole('button', { name: 'Back to Library', exact: true }).click();
		await expect(page).toHaveURL(LIBRARY_URL);

		const play = row(page, playable.title).getByRole('button', {
			name: `Play ${playable.title}`,
			exact: true
		});
		const open = row(page, playable.title).getByRole('button', {
			name: `Open album ${playable.title}`,
			exact: true
		});
		await open.focus();
		await page.keyboard.press('Tab');
		await expect(play).toBeFocused();
		const hitbox = await play.boundingBox();
		expect(hitbox?.width).toBe(44);
		expect(hitbox?.height).toBe(44);
		const scroll = workspace(page).locator('.wall-body');
		const before = await scroll.evaluate((el) => el.scrollTop);
		const audioResponse = page.waitForResponse(
			(response) => new URL(response.url()).pathname === fixture.tracks[playable.id][0].audioPath
		);
		const secondTrack = fixture.tracks[playable.id][1];
		const secondAudioResponse = page.waitForResponse(
			(response) => new URL(response.url()).pathname === secondTrack.audioPath
		);
		await page.keyboard.press('Enter');
		expect((await audioResponse).ok()).toBe(true);
		const pause = row(page, playable.title).getByRole('button', {
			name: `Pause ${playable.title}`,
			exact: true
		});
		await expect(pause).toBeVisible();
		await expect.poll(async () => (await playingAudioState(page)).time).toBeGreaterThan(0);
		await expect(page).toHaveURL(LIBRARY_URL);
		expect(await scroll.evaluate((el) => el.scrollTop)).toBe(before);
		await expect(row(page, playable.title).getByRole('img', { name: 'Playing' })).toBeVisible();
		const title = row(page, playable.title).locator('.tile-title');
		expect(await title.evaluate((el) => getComputedStyle(el).color)).toBe(
			await title.evaluate((el) => {
				const probe = document.createElement('span');
				probe.style.color = 'var(--accent)';
				el.append(probe);
				const color = getComputedStyle(probe).color;
				probe.remove();
				return color;
			})
		);
		await screenshot(page, 'playing');
		const playerBar = page.locator('.player-bar');
		await guard.abandoningTakes(takePathsOf(playable.id), secondTrack.audioPath, async () => {
			await playerBar.getByRole('button', { name: 'Next', exact: true }).click();
			await expect(playerBar).toContainText(secondTrack.title);
			expect((await secondAudioResponse).ok()).toBe(true);
		});
		await pause.click();
		await expect(play).toBeVisible();
		const paused = await playingAudioState(page);
		expect(paused.paused).toBe(true);
		await expect(row(page, playable.title).getByRole('img', { name: 'Playing' })).toBeVisible();
		await play.click();
		await expect(pause).toBeVisible();
		const resumed = await playingAudioState(page);
		expect(resumed.src).toBe(paused.src);
		expect(resumed.time).toBeGreaterThanOrEqual(paused.time);
		await expect(playerBar).toContainText(secondTrack.title);
		await expect
			.poll(async () => (await playingAudioState(page)).time)
			.toBeGreaterThan(paused.time + 0.2);
		await row(page, empty.title).getByRole('button').click();
		await page.getByRole('button', { name: 'Back to Library', exact: true }).click();
		await expect(row(page, playable.title).getByRole('img', { name: 'Playing' })).toBeVisible();

		await row(page, long.title).scrollIntoViewIfNeeded();
		const longTitle = row(page, long.title).locator('.tile-title');
		expect(
			await longTitle.evaluate((el) => ({
				overflow: getComputedStyle(el).textOverflow,
				clipped: el.scrollWidth > el.clientWidth
			}))
		).toEqual({ overflow: 'ellipsis', clipped: true });
		await expect(
			row(page, long.title).getByRole('button', { name: `Open album ${long.title}`, exact: true })
		).toBeVisible();
		await expect(row(page, long.title).locator('.tile-subtitle')).toBeVisible();
		await expect(row(page, long.title).locator('.row-play')).toBeVisible();
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
		await row(page, last.title).scrollIntoViewIfNeeded();
		const bottomBefore = await scroll.evaluate((el) => el.scrollTop);
		await guard.abandoningTakes(takePathsOf(playable.id), takePathsOf(last.id)[0], async () => {
			await row(page, last.title)
				.getByRole('button', { name: `Play ${last.title}`, exact: true })
				.click();
			await expect(
				row(page, last.title).getByRole('button', { name: `Pause ${last.title}`, exact: true })
			).toBeVisible();
		});
		await expect(page).toHaveURL(LIBRARY_URL);
		expect(await scroll.evaluate((el) => el.scrollTop)).toBe(bottomBefore);
		await expect(row(page, playable.title).getByRole('img', { name: 'Playing' })).toHaveCount(0);
		await screenshot(page, 'bottom-of-list');
		await expectRows(page);
		await page.getByRole('button', { name: 'Last played', exact: true }).click();
		await expect(workspace(page).locator('.wall-tile').first()).toContainText(last.title);
		await expect(workspace(page).locator('.wall-tile').nth(1)).toContainText(playable.title);
		const counts = await workspace(page).locator('.wall-tile .tile-subtitle').allTextContents();
		expect(counts.filter((text) => text.trim() === '1 song')).toHaveLength(3);
		expect(counts.filter((text) => text.trim() === '2 songs')).toHaveLength(1);
		await page.getByRole('button', { name: 'A–Z', exact: true }).click();
		await expect(workspace(page).locator('.wall-tile .tile-title')).toHaveText(
			fixture.albums.map((album) => album.title)
		);
		await page.goto('/playlists');
		const playlistRow = workspace(page).locator('.wall-tile');
		await expect(playlistRow).toHaveCount(1);
		await expect(playlistRow.getByRole('button')).toHaveCount(1);
		await expect(playlistRow.getByRole('button')).toHaveAccessibleName(
			`Open playlist ${fixture.playlist.title}`
		);
		expect((await playlistRow.boundingBox())?.height).toBe(58);
		await expect(playlistRow.locator('.tile-subtitle')).toHaveText('0 songs');
		await screenshot(page, 'playlist');
		await page.getByRole('button', { name: 'Last played', exact: true }).click();
		await expect(playlistRow.locator('.tile-subtitle')).toHaveText('0 songs');
		expect(
			await playlistRow.locator('.tile-title').evaluate((el) => el.scrollWidth > el.clientWidth)
		).toBe(true);
		await playlistRow.getByRole('button').click();
		await expect(
			workspace(page).getByRole('heading', { name: fixture.playlist.title, exact: true })
		).toBeVisible();
	}
);

test(
	'1354_rule_13: D1 desktop retains cover grids and open behaviour',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await page.goto(LIBRARY_PATH);
		const tiles = workspace(page).locator('.wall-tile');
		await expect(tiles).toHaveCount(43);
		await expect(workspace(page).locator('.row-play')).toHaveCount(0);
		const first = await tiles.nth(0).boundingBox();
		const second = await tiles.nth(1).boundingBox();
		expect(first?.y).toBe(second?.y);
		expect(first?.width).toBe(208);
		const cover = await tiles.first().locator('.tile-cover').boundingBox();
		expect(cover?.width).toBe(cover?.height);
		await expect(tiles.first().locator('.tile-subtitle')).toHaveText('0 songs');
		await tiles.first().getByRole('button').focus();
		await page.keyboard.press('Enter');
		await expect(
			workspace(page).getByRole('heading', { name: fixture.albums[0].title, exact: true })
		).toBeVisible();
		await page.goto('/playlists');
		await expect(tiles).toHaveCount(1);
		await expect(tiles.locator('.row-play')).toHaveCount(0);
		expect((await tiles.first().boundingBox())?.width).toBe(208);
		await expect(tiles.first().locator('.tile-subtitle')).toHaveText('0 songs');
		await tiles.first().getByRole('button').click();
		await expect(
			workspace(page).getByRole('heading', { name: fixture.playlist.title, exact: true })
		).toBeVisible();
	}
);

test(
	'1354_rule_10: P4 direct audio keeps the second track through row pause and resume',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		// Browsers without MSE use a media URL; the ordinary P1–P6 flow above
		// keeps Chromium's continuous blob-backed deck enabled.
		await page.addInitScript(() => Reflect.deleteProperty(window, 'MediaSource'));
		const playable = fixture.albums[2];
		const secondTrack = fixture.tracks[playable.id][1];
		await page.goto(LIBRARY_PATH);
		const play = row(page, playable.title).getByRole('button', {
			name: `Play ${playable.title}`,
			exact: true
		});
		await play.click();
		await expect.poll(async () => (await playingAudioState(page)).time).toBeGreaterThan(0);
		await guard.abandoningTakes(takePathsOf(playable.id), secondTrack.audioPath, async () => {
			await page.locator('.player-bar').getByRole('button', { name: 'Next', exact: true }).click();
			await expect
				.poll(async () => new URL((await playingAudioState(page)).src).pathname)
				.toBe(secondTrack.audioPath);
		});
		await row(page, playable.title)
			.getByRole('button', { name: `Pause ${playable.title}`, exact: true })
			.click();
		const paused = await playingAudioState(page);
		expect(paused.paused).toBe(true);
		await play.click();
		await expect
			.poll(async () => (await playingAudioState(page)).time)
			.toBeGreaterThan(paused.time + 0.2);
		expect(new URL((await playingAudioState(page)).src).pathname).toBe(secondTrack.audioPath);
		await expect(page).toHaveURL(LIBRARY_URL);
	}
);
