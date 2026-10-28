import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';
import { LIBRARY_PAGE_LABEL, RAIL_LIBRARY_NAV_LABEL, RAIL_NAV_LABEL } from '../src/lib/constants';
import { archiveOwnedAlbum, BASE_URL } from './seed';
import {
	boundingBoxes,
	sameOriginHeaders,
	FlowGuard,
	LIBRARY_PATH,
	loadedImages,
	ONLY_IN_SHELL
} from './helpers';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const COVER_PNG = readFileSync(path.join(E2E_DIR, '..', 'static', 'icon-192.png'));

interface CreatedResource {
	id: string;
}

interface ShareResult {
	share_url: string;
}

async function postJson<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { headers: await sameOriginHeaders(page), data });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

// A song of the album with one real take imported, as a share presents it.
async function createSongWithTake(
	page: Page,
	albumId: string,
	song: { title: string; lyrics: string }
): Promise<{ song: CreatedResource; take: CreatedResource }> {
	const created = await postJson<CreatedResource>(page, '/api/songs', {
		...song,
		album_id: albumId,
		prompt: 'quiet test song'
	});
	const reimport = await page.request.post(`/api/songs/${created.id}/reimport`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(reimport.ok(), `Take import failed: ${await reimport.text()}`).toBeTruthy();
	return { song: created, take: (await reimport.json()) as CreatedResource };
}

async function postCover(page: Page, albumId: string): Promise<void> {
	const response = await page.request.post(`/api/albums/${albumId}/cover`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			file: { name: 'cover.png', mimeType: 'image/png', buffer: COVER_PNG }
		}
	});
	expect(response.ok(), `Cover upload failed: ${await response.text()}`).toBeTruthy();
}

async function putPlaylistCover(page: Page, playlistId: string): Promise<void> {
	const response = await page.request.put(`/api/playlists/${playlistId}/cover`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			file: { name: 'playlist-cover.png', mimeType: 'image/png', buffer: COVER_PNG }
		}
	});
	expect(response.ok(), `Playlist cover upload failed: ${await response.text()}`).toBeTruthy();
}

async function deletePlaylistCover(page: Page, playlistId: string): Promise<void> {
	const response = await page.request.delete(`/api/playlists/${playlistId}/cover`, {
		headers: await sameOriginHeaders(page)
	});
	expect(response.ok(), `Playlist cover removal failed: ${await response.text()}`).toBeTruthy();
}

async function deleteOwnedPlaylist(page: Page, playlistId: string): Promise<void> {
	const response = await page.request.delete(`/api/playlists/${playlistId}`, {
		headers: await sameOriginHeaders(page)
	});
	expect(
		response.ok(),
		`DELETE /api/playlists/${playlistId} failed: ${await response.text()}`
	).toBeTruthy();
}

async function createCoveredAlbum(
	page: Page
): Promise<{ album: CreatedResource; albumTitle: string }> {
	const albumTitle = `E2E Cover Rail ${Date.now().toString(36)}`;
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: albumTitle,
		artist: 'E2E Cover Artist'
	});
	await postCover(page, album.id);
	return { album, albumTitle };
}

test('1354_65_C1 1354_37a_A6: a fresh album cover reaches wall, album header, desktop rail, and every share page at desktop and 375 px', async ({
	page,
	browser,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const marker = Date.now().toString(36);
	const { album, albumTitle } = await createCoveredAlbum(page);
	try {
		const { song, take } = await createSongWithTake(page, album.id, {
			title: `E2E Cover Song ${marker}`,
			lyrics: 'A cover belongs to this album.'
		});

		const [albumShare, songShare, takeShare] = await Promise.all([
			postJson<ShareResult>(page, `/api/albums/${album.id}/share`, {}),
			postJson<ShareResult>(page, `/api/songs/${song.id}/share`, {}),
			postJson<ShareResult>(page, `/api/generations/${take.id}/share`, {})
		]);

		await page.goto(LIBRARY_PATH);
		const wallTile = page.locator('.wall-tile').filter({ hasText: albumTitle });
		await expect(wallTile.locator('.tile-cover img')).toBeVisible();
		await expect(wallTile.locator('.tile-cover img')).toHaveAttribute('alt', `Album ${albumTitle}`);

		await page.goto(`/album/${album.id}`);
		await expect(page.locator('.collection-header .header-cover img')).toBeVisible();
		if (!isMobile) {
			const rail = page.getByRole('navigation', { name: RAIL_NAV_LABEL });
			const libraryGroup = rail.getByRole('button', { name: new RegExp(`^${LIBRARY_PAGE_LABEL}`) });
			if ((await libraryGroup.getAttribute('aria-expanded')) === 'false')
				await libraryGroup.click();
			const railAlbum = rail
				.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
				.getByRole('listitem')
				.filter({ hasText: albumTitle });
			await expect(railAlbum.getByRole('img', { name: `Album ${albumTitle}` })).toBeVisible();
		}

		const publicContext = await browser.newContext({
			storageState: undefined,
			viewport: page.viewportSize(),
			isMobile: Boolean(isMobile),
			hasTouch: Boolean(isMobile)
		});
		try {
			// A shared album, song or take opens as the player, its big cover the album's (#1391).
			for (const share of [albumShare, songShare, takeShare]) {
				const publicPage = await publicContext.newPage();
				const guard = new FlowGuard(publicPage);
				try {
					await publicPage.goto(share.share_url);
					await expect(publicPage.locator('.now-playing.page .cover-art img')).toBeVisible();
					await expect(publicPage.locator('.now-playing.page .cover-art img')).toHaveAttribute(
						'src',
						/\/shared\/(((song|gen)\/)?[^/]+\/(album-)?)cover\?/
					);
				} finally {
					try {
						guard.assertClean();
					} finally {
						await publicPage.close();
					}
				}
			}
		} finally {
			await publicContext.close();
		}
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
});

test('1354_65_C2 1354_37b_62_A: a shared playlist replaces its upload with the current mosaic and disappears after unshare at desktop and 375 px', async ({
	page,
	browser,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const marker = Date.now().toString(36);
	let playlistId: string | undefined;
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Shared Playlist Album ${marker}`,
		artist: 'E2E Cover Artist'
	});
	try {
		const { take } = await createSongWithTake(page, album.id, {
			title: `E2E Shared Playlist Song ${marker}`,
			lyrics: 'A shared playlist cover should be current.'
		});
		await postCover(page, album.id);
		const playlist = await postJson<CreatedResource>(page, '/api/playlists', {
			title: `E2E Shared Playlist ${marker}`
		});
		playlistId = playlist.id;
		await postJson(page, `/api/playlists/${playlist.id}/entries/generation`, {
			generation_id: take.id
		});
		await putPlaylistCover(page, playlist.id);
		const share = await postJson<ShareResult>(page, `/api/playlists/${playlist.id}/share`, {});

		const publicContext = await browser.newContext({
			storageState: undefined,
			viewport: page.viewportSize(),
			isMobile: Boolean(isMobile),
			hasTouch: Boolean(isMobile)
		});
		const publicPage = await publicContext.newPage();
		const guard = new FlowGuard(publicPage, {
			refusalsExpectedOn: [
				{ path: new URL(share.share_url).pathname.replace('/share/', '/shared/'), statuses: [404] }
			]
		});
		try {
			await publicPage.goto(share.share_url);
			await expect(publicPage.locator('.cover-art .playlist-cover-image')).toHaveAttribute(
				'src',
				/\/shared\/playlist\/[^/]+\/cover\?variant=card&v=/
			);
			await loadedImages(publicPage.locator('.cover-art .playlist-cover-image'));

			await deletePlaylistCover(page, playlist.id);
			await publicPage.reload();
			await expect(publicPage.locator('.cover-art .playlist-cover-image')).toHaveCount(0);
			await expect(publicPage.locator('.cover-art .playlist-cover-cell')).toHaveCount(4);
			await expect(publicPage.locator('.cover-art .playlist-cover-cell img')).toHaveCount(1);
			await loadedImages(publicPage.locator('.cover-art .playlist-cover-cell img'));

			const unshare = await page.request.delete(`/api/playlists/${playlist.id}/share`, {
				headers: await sameOriginHeaders(page)
			});
			expect(unshare.ok(), `Playlist unshare failed: ${await unshare.text()}`).toBeTruthy();
			await publicPage.reload();
			await expect(publicPage.getByRole('heading', { name: 'Playlist not found' })).toBeVisible();
			await expect(publicPage.locator('.cover-art')).toHaveCount(0);
		} finally {
			try {
				guard.assertClean();
			} finally {
				await publicContext.close();
			}
		}
	} finally {
		try {
			if (playlistId) await deleteOwnedPlaylist(page, playlistId);
		} finally {
			await archiveOwnedAlbum(page.request, album.id);
		}
	}
});

// What a phone's browser leaves of its screen, upright and on its side, down
// to an iPhone's in Safari with its toolbars (#1391). Each project drives them
// with its own pointer: a touch phone, and a desktop window just as narrow.
const PHONE_SCREENS = [
	{ width: 390, height: 844 },
	{ width: 390, height: 664 },
	{ width: 375, height: 667 },
	{ width: 360, height: 640 },
	{ width: 844, height: 390 }
];
// The words keep room for a few lines however short the screen.
const WORDS_MIN_HEIGHT_PX = 80;

test('1354_65_C3 1354_37b_62_B: a shared song shows Play and its words in one screen at every phone height (#1391)', async ({
	page,
	browser,
	isMobile
}) => {
	const marker = Date.now().toString(36);
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Phone Screens ${marker}`,
		artist: 'E2E Cover Artist'
	});
	try {
		const lines = Array.from({ length: 24 }, (_, index) => `Line ${index + 1} of the shared song`);
		const { song } = await createSongWithTake(page, album.id, {
			title: `E2E Phone Song ${marker}`,
			lyrics: lines.join('\n')
		});
		const share = await postJson<ShareResult>(page, `/api/songs/${song.id}/share`, {});

		const publicContext = await browser.newContext({
			storageState: undefined,
			isMobile: Boolean(isMobile),
			hasTouch: Boolean(isMobile)
		});
		const publicPage = await publicContext.newPage();
		const guard = new FlowGuard(publicPage);
		try {
			for (const screen of PHONE_SCREENS) {
				await publicPage.setViewportSize(screen);
				await publicPage.goto(share.share_url);
				await expect(publicPage.locator('.now-playing.page .play-btn')).toBeVisible();
				const play = await publicPage.locator('.now-playing.page .play-btn').boundingBox();
				const words = await publicPage.locator('.now-playing.page .np-lyrics').boundingBox();
				if (!play || !words) throw new Error(`No player at ${screen.width}x${screen.height}`);
				const onScreen = (box: { y: number; height: number }) =>
					box.y >= 0 && Math.round(box.y + box.height) <= screen.height;
				expect(
					{
						play: onScreen(play),
						words: onScreen(words),
						wordsTall: words.height >= WORDS_MIN_HEIGHT_PX
					},
					`${screen.width}x${screen.height}: play ${JSON.stringify(play)}, words ${JSON.stringify(words)}`
				).toEqual({ play: true, words: true, wordsTall: true });
			}
		} finally {
			try {
				guard.assertClean();
			} finally {
				await publicContext.close();
			}
		}
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
});

for (const kind of ['song', 'gen'] as const) {
	for (const height of [900, 600]) {
		test(
			`1374_rule_11 shared ${kind} keeps player and plain lyrics reachable at ${height}`,
			{ tag: height === 600 ? ONLY_IN_SHELL.desktop : [] },
			async ({ browser }, info) => {
				const phone = info.project.name === 'mobile';
				const viewport = phone ? { width: 390, height: 844 } : { width: 1440, height };
				const context = await browser.newContext({
					storageState: undefined,
					viewport,
					isMobile: phone,
					hasTouch: phone
				});
				const page = await context.newPage();
				const guard = new FlowGuard(page);
				const payload = {
					title: 'Shared plain words',
					artist: 'Share Artist',
					album_title: 'Share Album',
					generation_number: 1,
					generation_id: 'shared-take',
					audio_duration: 3,
					audio_url: '/shared/layout-proof/audio',
					album_cover: null,
					whisper_cues: null,
					lyrics: Array.from({ length: 100 }, (_, i) => `Plain line ${i + 1}`).join('\n')
				};
				try {
					await page.route(`**/shared/${kind}/layout-proof`, (route) =>
						route.fulfill({ json: payload })
					);
					await page.route('**/shared/layout-proof/audio', (route) =>
						route.fulfill({ contentType: 'audio/mpeg', body: readFileSync(TAKE_FIXTURE) })
					);
					await page.goto(`${BASE_URL}/share/${kind}/layout-proof`);
					const player = page.locator('.now-playing.page');
					await expect(player.getByRole('button', { name: 'Play', exact: true })).toBeInViewport({
						ratio: 1
					});
					await expect(player.getByRole('slider')).toBeInViewport({ ratio: 1 });
					await expect(player.locator('.lyrics-text')).toHaveText(payload.lyrics);
					const cover = await player.locator('.cover-art').boundingBox();
					const title = await page.getByRole('heading', { level: 1 }).boundingBox();
					const lyrics = await player.locator('.np-lyrics').boundingBox();
					if (!cover || !title || !lyrics) throw new Error('Missing shared player geometry');
					if (!phone) expect(cover.x + cover.width).toBeLessThanOrEqual(title.x);
					expect(lyrics.y + lyrics.height).toBeLessThanOrEqual(viewport.height);
					expect(lyrics.height).toBeGreaterThanOrEqual(80);
					await expect(page.locator('.queue-row, footer.player-bar')).toHaveCount(0);
					await expect(player.getByRole('button', { name: 'Shuffle', exact: true })).toHaveCount(0);
					const directory = process.env.SHARE_PLAYLIST_SCREENSHOTS;
					if (directory)
						await page.screenshot({
							path: `${directory}/${kind}-${viewport.width}-${viewport.height}.png`
						});
					await player.getByRole('slider').fill('1');
					await expect(player.getByRole('slider')).toHaveValue('1');
					await player.getByRole('button', { name: 'Play', exact: true }).click();
					await expect(player.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
					if (kind === 'gen') {
						await page.route(`**/shared/${kind}/layout-proof`, (route) =>
							route.fulfill({ json: { ...payload, audio_url: null } })
						);
						await page.reload();
						await expect(page.getByRole('status')).toHaveText('No audio available yet.');
						await expect(page.locator('.np-page-lyrics')).toHaveCount(0);
						await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeDisabled();
						if (!phone) {
							const [column, progress] = await boundingBoxes(
								player.locator('.np-player-col'),
								player.locator('.progress')
							);
							expect(column.y + column.height).toBeCloseTo(progress.y + progress.height, 0);
						}
					}
				} finally {
					try {
						guard.assertClean();
					} finally {
						await context.close();
					}
				}
			}
		);
	}
}
