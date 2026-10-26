import { scrollWallTo } from './wall-scroll';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import {
	csrfHeaders,
	expectLibraryWallLoaded,
	FlowGuard,
	LIBRARY_PATH,
	listenRegion,
	LIBRARY_URL,
	nameStartingWith,
	observePlayingAudio,
	ONLY_IN_SHELL,
	openHome,
	openLibraryWall,
	openRailNav,
	playingAudioState,
	shellOf,
	SUCCESSOR_TAKES_TEST_TIMEOUT_MS,
	type Shell,
	wallBody,
	workspace
} from './helpers';
import {
	archivePhoneLibrary,
	seedAccount,
	seedPhoneLibrary,
	signedInApi,
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

test.beforeEach(async ({ page }) => {
	test.setTimeout(SUCCESSOR_TAKES_TEST_TIMEOUT_MS);
	guard = new FlowGuard(page);
	const seeded = await seedAccount(`e2e-phone-${randomUUID()}`);
	account = await signedInApi(seeded);
	fixture = await seedPhoneLibrary(account);
	await page.context().clearCookies();
	await page.context().addCookies(seeded.cookies);
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

const LIGHT_UPS_KEY = '__rowLightUps';
const LIGHT_UP_ANIMATION_SUFFIX = 'light-up';
const SCROLL_LANDING_TOLERANCE_PX = 1;

interface LightUps {
	marked: string[];
	animated: string[];
}

// Records every moment a phone row is marked as the place just returned from,
// and every animation that marking starts, for the page's whole document.
async function watchLightUps(page: Page): Promise<void> {
	await page.evaluate(
		({ key, animation }) => {
			const seen: LightUps = { marked: [], animated: [] };
			Reflect.set(window, key, seen);
			const titleOf = (element: Element) => element.querySelector('.tile-title')?.textContent ?? '';
			const isLit = (element: Element) =>
				element.classList.contains('library-row') && element.classList.contains('lit');
			new MutationObserver((records) => {
				for (const record of records) {
					const target = record.target as Element;
					const wasLit = (record.oldValue ?? '').split(' ').includes('lit');
					if (isLit(target) && !wasLit) seen.marked.push(titleOf(target));
				}
			}).observe(document.body, {
				subtree: true,
				attributes: true,
				attributeOldValue: true,
				attributeFilter: ['class']
			});
			document.addEventListener(
				'animationstart',
				(event) => {
					if (event.animationName.endsWith(animation))
						seen.animated.push(titleOf(event.target as Element));
				},
				true
			);
		},
		{ key: LIGHT_UPS_KEY, animation: LIGHT_UP_ANIMATION_SUFFIX }
	);
}

function lightUps(page: Page): Promise<LightUps> {
	return page.evaluate((key) => Reflect.get(window, key) as LightUps, LIGHT_UPS_KEY);
}

async function expectLandedAt(page: Page, scrollTop: number): Promise<void> {
	const landed = await wallBody(page).evaluate((body) => body.scrollTop);
	expect(Math.abs(landed - scrollTop)).toBeLessThanOrEqual(SCROLL_LANDING_TOLERANCE_PX);
}

// The phone turned to landscape swaps the rows for tiles, and turned back
// swaps them again: the row that lit once is a new row by then.
async function turnPhoneToLandscapeAndBack(page: Page): Promise<void> {
	const portrait = page.viewportSize();
	if (!portrait) throw new Error('Expected a viewport to turn');
	await page.setViewportSize({ width: portrait.height, height: portrait.width });
	await expect(workspace(page).locator('.library-row')).toHaveCount(0);
	await page.setViewportSize(portrait);
	await expect(workspace(page).locator('.library-row')).toHaveCount(fixture.albums.length);
	await expectRows(page);
}

const RETURN_CELLS = [
	{ name: 'bottom album, ‹', where: 'bottom', via: 'chevron', reducedMotion: false, turns: false },
	{
		name: 'bottom album, the phone Back',
		where: 'bottom',
		via: 'back',
		reducedMotion: false,
		turns: false
	},
	{ name: 'middle album, ‹', where: 'middle', via: 'chevron', reducedMotion: false, turns: false },
	{
		name: 'bottom album, ‹, reduced motion',
		where: 'bottom',
		via: 'chevron',
		reducedMotion: true,
		turns: false
	},
	{
		name: 'bottom album, ‹, the phone turned to landscape and back',
		where: 'bottom',
		via: 'chevron',
		reducedMotion: false,
		turns: true
	}
] as const;

for (const cell of RETURN_CELLS) {
	test(
		`1354_rule_12: S4 ${cell.name} lands the list exactly and the album lights up once`,
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const album = fixture.albums[cell.where === 'bottom' ? 42 : 21];
			if (cell.reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' });
			await page.goto(LIBRARY_PATH);
			await expectLibraryWallLoaded(page);
			await expectRows(page);
			if (cell.where === 'middle') await scrollWallTo(page, 'halfway');
			else await row(page, album.title).scrollIntoViewIfNeeded();
			const wall = await wallBody(page).evaluate((body) => ({
				before: body.scrollTop,
				end: body.scrollHeight - body.clientHeight
			}));
			if (cell.where === 'bottom') expect(wall.end - wall.before).toBeLessThanOrEqual(1);
			else expect(wall.before).toBeGreaterThan(0);
			await watchLightUps(page);
			await row(page, album.title)
				.getByRole('button', { name: `Open album ${album.title}`, exact: true })
				.click();
			await expect(
				workspace(page).getByRole('heading', { name: album.title, exact: true })
			).toBeVisible();

			if (cell.via === 'back') await page.goBack();
			else await page.getByRole('button', { name: 'Back to Library', exact: true }).click();

			await expect(page).toHaveURL(LIBRARY_URL);
			const lit = workspace(page).locator('.library-row.lit');
			await expect(lit).toHaveCount(1);
			await expect(lit).toContainText(album.title);
			const motion = await lit.evaluate((element) => {
				const style = getComputedStyle(element);
				return { animation: style.animationName, background: style.backgroundColor };
			});
			if (cell.reducedMotion) {
				expect(motion.animation).toBe('none');
				expect(motion.background).not.toBe('rgba(0, 0, 0, 0)');
			} else {
				expect(motion.animation).toContain(LIGHT_UP_ANIMATION_SUFFIX);
			}
			await screenshot(page, cell.name);
			await expectLandedAt(page, wall.before);

			await expect(lit).toHaveCount(0);
			await expectLandedAt(page, wall.before);
			if (cell.turns) {
				await turnPhoneToLandscapeAndBack(page);
				await expect(lit).toHaveCount(0);
			}
			await wallBody(page).evaluate((body) => (body.scrollTop -= 200));
			await page.getByRole('button', { name: 'Last played', exact: true }).click();
			await page.getByRole('button', { name: 'A–Z', exact: true }).click();
			await expectRows(page);
			const seen = await lightUps(page);
			expect(seen.marked).toEqual([album.title]);
			expect(seen.animated).toEqual(cell.reducedMotion ? [] : [album.title]);
		}
	);
}

test(
	'1354_rule_12: D1 desktop returns to its tiles where they were left, with no row lit',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const album = fixture.albums[21];
		await page.goto(LIBRARY_PATH);
		await expectLibraryWallLoaded(page);
		await expect(workspace(page).locator('.wall-tile')).toHaveCount(43);
		await row(page, album.title).scrollIntoViewIfNeeded();
		const before = await wallBody(page).evaluate((body) => body.scrollTop);
		expect(before).toBeGreaterThan(0);
		await watchLightUps(page);
		await row(page, album.title)
			.getByRole('button', { name: `Open album ${album.title}`, exact: true })
			.click();
		await expect(
			workspace(page).getByRole('heading', { name: album.title, exact: true })
		).toBeVisible();

		await page.goBack();

		await expect(page).toHaveURL(LIBRARY_URL);
		await expect(row(page, album.title)).toBeVisible();
		await expectLandedAt(page, before);
		await expect(workspace(page).locator('.library-row, .lit')).toHaveCount(0);
		expect((await lightUps(page)).marked).toEqual([]);
	}
);

const PAINTED_ORDERS_KEY = '__paintedOrders';
const LISTEN_READ_PATH = '/api/library/listen';
const SONG_READ_PATH = /^\/api\/songs\/[^/]+$/;
// Listen answers after the lists do, as it would behind a busy server: the
// order in which A–Z, if it were painted first, would show.
const LISTEN_ANSWER_DELAY_MS = 400;

interface PaintedOrders {
	wall: string[][];
	rail: string[][];
}

// Records the order the wall and the rail group stand in on every frame that
// painted a different one, for the whole document: a poll that waits for the
// final order cannot see an A–Z order that stood in front of it first.
async function recordPaintedOrders(
	page: Page,
	selectors: Record<keyof PaintedOrders, string>
): Promise<void> {
	await page.addInitScript(
		({ key, rows }) => {
			const painted: PaintedOrders = { wall: [], rail: [] };
			Reflect.set(window, key, painted);
			const sample = () => {
				for (const surface of ['wall', 'rail'] as const) {
					const titles = [...document.querySelectorAll(rows[surface])].map(
						(title) => title.textContent ?? ''
					);
					const previous = painted[surface].at(-1);
					if (titles.length > 0 && previous?.join('\n') !== titles.join('\n'))
						painted[surface].push(titles);
				}
				requestAnimationFrame(sample);
			};
			requestAnimationFrame(sample);
		},
		{ key: PAINTED_ORDERS_KEY, rows: selectors }
	);
}

function paintedOrders(page: Page): Promise<PaintedOrders> {
	return page.evaluate((key) => Reflect.get(window, key) as PaintedOrders, PAINTED_ORDERS_KEY);
}

async function firstSongOf(page: Page, albumId: string): Promise<string> {
	const songs = await page.request.get(`/api/songs?album_id=${albumId}`);
	expect(songs.ok()).toBe(true);
	const [song] = (await songs.json()).items as Array<{ id: string }>;
	return song.id;
}

async function listenIn(page: Page, songId: string, playlistId?: string): Promise<void> {
	const listen = await page.request.post(`/api/songs/${songId}/listen`, {
		headers: await csrfHeaders(page),
		data: playlistId ? { playlist_id: playlistId } : undefined
	});
	expect(listen.ok()).toBe(true);
}

async function seedPlaylistHolding(page: Page, title: string, songId: string): Promise<string> {
	const headers = await csrfHeaders(page);
	const created = await page.request.post('/api/playlists', { headers, data: { title } });
	expect(created.ok()).toBe(true);
	const { id } = (await created.json()) as { id: string };
	const added = await page.request.post(`/api/playlists/${id}/entries/song`, {
		headers,
		data: { song_id: songId }
	});
	expect(added.ok()).toBe(true);
	return id;
}

// Plays the album's first take from the Library wall and waits until its
// listen is recorded.
async function playFirstTakeFromTheWall(
	page: Page,
	shell: Shell,
	album: PhoneLibraryFixture['albums'][number]
): Promise<void> {
	const listenRecorded = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			/^\/api\/songs\/[^/]+\/listen$/.test(new URL(response.url()).pathname)
	);
	await workspace(page)
		.getByRole('button', { name: `Open album ${album.title}`, exact: true })
		.click();
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(fixture.tracks[album.id][0].title) })
		.click();
	if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
	const take = workspace(page).locator('.take-row');
	await expect(take).toHaveCount(1);
	await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();
	expect((await listenRecorded).ok()).toBe(true);
}

// Leaves a take paused, so that a reload restores it, as a page Android
// killed and the listener reopened.
async function pauseATakeToRestore(
	page: Page,
	shell: Shell,
	album: PhoneLibraryFixture['albums'][number]
): Promise<void> {
	await page.goto(LIBRARY_PATH);
	await playFirstTakeFromTheWall(page, shell, album);
	await expect.poll(async () => (await playingAudioState(page)).time).toBeGreaterThan(0);
	const transport = page.getByRole('contentinfo');
	await transport.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true }).click();
	await expect(
		transport.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true })
	).toBeVisible();
}

// The one switch sorts the Library, Playlists and the rail the same way
// (1354_rule_8): each page lists its places in A–Z, arranges listens that put
// a later one first under Last played, and names the rail rows that follow.
const LAST_PLAYED_PAGES = [
	{
		name: 'Library',
		path: LIBRARY_PATH,
		railRows: '.album-label .row-title',
		async arrange(page: Page) {
			const [newest, older] = [fixture.albums[2], fixture.albums[42]];
			await listenIn(page, await firstSongOf(page, older.id));
			await listenIn(page, await firstSongOf(page, newest.id));
			return {
				alphabetical: fixture.albums.map((album) => album.title),
				listenedLast: [newest.title, older.title]
			};
		}
	},
	{
		name: 'Playlists',
		path: '/playlists',
		railRows: '.playlist-label .row-title',
		async arrange(page: Page) {
			const [alpha, omega] = ['E2E Phone Playlist Alpha', 'E2E Phone Playlist Omega'];
			const alphaSong = await firstSongOf(page, fixture.albums[42].id);
			const omegaSong = await firstSongOf(page, fixture.albums[2].id);
			await seedPlaylistHolding(page, alpha, alphaSong);
			const omegaId = await seedPlaylistHolding(page, omega, omegaSong);
			await listenIn(page, omegaSong, omegaId);
			return {
				alphabetical: [alpha, omega, fixture.playlist.title],
				listenedLast: [omega]
			};
		}
	}
] as const;

for (const [shell, surfaces, proof] of [
	['mobile', ['wall'], 'a fresh mobile'],
	['desktop', ['wall', 'rail'], 'a fresh desktop']
] as const) {
	for (const lastPlayedPage of LAST_PLAYED_PAGES) {
		test(
			`1354_rule_8: ${proof} ${lastPlayedPage.name} page under Last played, with a take restored, never paints A–Z first and reads Listen once`,
			{ tag: ONLY_IN_SHELL[shell] },
			async ({ page }) => {
				const { alphabetical, listenedLast } = await lastPlayedPage.arrange(page);
				const lastPlayed = [
					...listenedLast,
					...alphabetical.filter((title) => !listenedLast.includes(title))
				];
				expect(lastPlayed, 'the listens change the order').not.toEqual(alphabetical);
				await recordPaintedOrders(page, {
					wall: '.library-wall .tile-grid .tile-title',
					rail: lastPlayedPage.railRows
				});
				await pauseATakeToRestore(page, shell, fixture.albums[2]);
				await page.goto(lastPlayedPage.path);
				await page.getByRole('button', { name: 'Last played', exact: true }).click();
				await expect(workspace(page).locator('.tile-title').first()).toHaveText(lastPlayed[0]);
				let answerDelayMs = 0;
				await page.route(
					(url) => url.pathname === LISTEN_READ_PATH,
					async (route) => {
						await new Promise((resolve) => setTimeout(resolve, answerDelayMs));
						await route.continue();
					}
				);
				// Restore the take after the ranking, whatever order the server answers in.
				let takeReleased: Promise<void> = Promise.resolve();
				let releaseTake = () => {};
				await page.route(
					(url) => SONG_READ_PATH.test(url.pathname),
					async (route) => {
						await takeReleased;
						await route.continue();
					}
				);
				let listenReads = 0;
				page.on('request', (request) => {
					if (request.method() === 'GET' && new URL(request.url()).pathname === LISTEN_READ_PATH)
						listenReads++;
				});
				for (answerDelayMs of [LISTEN_ANSWER_DELAY_MS, 0]) {
					listenReads = 0;
					takeReleased = new Promise<void>((release) => (releaseTake = release));
					await page.reload();
					await expect(workspace(page).locator('.library-wall .tile-title')).toHaveText(lastPlayed);
					releaseTake();
					await expect(page.getByRole('contentinfo')).toContainText(
						fixture.tracks[fixture.albums[2].id][0].title
					);
					if (surfaces.some((surface) => surface === 'rail')) {
						const rail = await openRailNav(page, shell);
						await expect(rail.locator(lastPlayedPage.railRows)).toHaveCount(lastPlayed.length);
					}
					for (const surface of surfaces)
						await expect
							.poll(async () => (await paintedOrders(page))[surface].at(-1))
							.toEqual(lastPlayed);
					const painted = await paintedOrders(page);
					for (const surface of surfaces)
						for (const order of painted[surface])
							expect(order).toEqual(lastPlayed.filter((title) => order.includes(title)));
					expect(listenReads, `Listen reads with its answer ${answerDelayMs} ms late`).toBe(1);
				}
			}
		);
	}
}

test("1354_rule_8 1354_rule_14: a place played leads Home's Listen and the Library visited after it, on one Listen read", async ({
	page
}, testInfo) => {
	const shell = shellOf(testInfo);
	const [newest, older] = [fixture.albums[2], fixture.albums[42]];
	await listenIn(page, await firstSongOf(page, older.id));
	await recordPaintedOrders(page, {
		wall: '.library-wall .tile-grid .tile-title',
		rail: '.album-label .row-title'
	});
	await page.goto(LIBRARY_PATH);
	await page.getByRole('button', { name: 'Last played', exact: true }).click();
	const tileTitles = workspace(page).locator('.library-wall .tile-grid .tile-title');
	await expect(tileTitles.first()).toHaveText(older.title);
	await playFirstTakeFromTheWall(page, shell, newest);
	let listenReads = 0;
	page.on('request', (request) => {
		if (request.method() === 'GET' && new URL(request.url()).pathname === LISTEN_READ_PATH)
			listenReads++;
	});
	await openHome(page, shell);
	await expect(listenRegion(page).locator('.wall-tile-body').first()).toHaveAttribute(
		'aria-label',
		`Open album ${newest.title}`
	);

	const paintMark = (await paintedOrders(page)).wall.length;
	await openLibraryWall(page, shell);

	await expect(tileTitles.first()).toHaveText(newest.title);
	await expect(tileTitles.nth(1)).toHaveText(older.title);
	const lastPlayed = [
		newest.title,
		older.title,
		...fixture.albums
			.filter((album) => album !== newest && album !== older)
			.map((album) => album.title)
	];
	await expect
		.poll(async () => (await paintedOrders(page)).wall.slice(paintMark).at(-1))
		.toEqual(lastPlayed);
	for (const order of (await paintedOrders(page)).wall.slice(paintMark))
		expect(order).toEqual(lastPlayed);
	expect(listenReads, 'Listen reads on Home and the Library visited after it').toBe(1);
});
