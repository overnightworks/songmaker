import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';
import {
	COLLECTION_MENU_COVER_REMOVE_LABEL,
	COLLECTION_MENU_LABEL,
	PLAYLISTS_PAGE_LABEL,
	RAIL_PLAYLISTS_NAV_LABEL
} from '../src/lib/constants';
import { sameOriginHeaders, openPlaylistsPage, openRailNav } from './helpers';
import { archiveOwnedAlbum } from './seed';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const COVER_PNG = readFileSync(path.join(E2E_DIR, '..', 'static', 'icon-192.png'));

interface CreatedResource {
	id: string;
	slug: string;
}

async function postJson<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { headers: await sameOriginHeaders(page), data });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

async function railPlaylistRow(page: Page, title: string) {
	const rail = await openRailNav(page, 'desktop');
	const group = rail.getByRole('button', { name: PLAYLISTS_PAGE_LABEL, exact: true });
	if ((await group.getAttribute('aria-expanded')) === 'false') await group.click();
	return rail
		.getByRole('navigation', { name: RAIL_PLAYLISTS_NAV_LABEL })
		.getByRole('listitem')
		.filter({ hasText: title });
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

test('1354_37b_71_rail 1354_65_C4 1354_37a_A6: playlist wall, detail and desktop rail covers follow mosaic, upload and removal', async ({
	page,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const marker = Date.now().toString(36);
	const playlistTitle = `E2E Playlist Mosaic ${marker}`;
	let playlist: CreatedResource | undefined;
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Mosaic Album ${marker}`,
		artist: 'E2E Cover Artist'
	});
	const song = await postJson<CreatedResource>(page, '/api/songs', {
		title: `E2E Mosaic Song ${marker}`,
		album_id: album.id,
		lyrics: 'A playlist mosaic needs one covered album.',
		prompt: 'quiet test song'
	});
	const reimport = await page.request.post(`/api/songs/${song.id}/reimport`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(reimport.ok(), `Take import failed: ${await reimport.text()}`).toBeTruthy();
	const take = (await reimport.json()) as CreatedResource;
	const cover = await page.request.post(`/api/albums/${album.id}/cover`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			file: { name: 'cover.png', mimeType: 'image/png', buffer: COVER_PNG }
		}
	});
	expect(cover.ok(), `Cover upload failed: ${await cover.text()}`).toBeTruthy();
	try {
		playlist = await postJson<CreatedResource>(page, '/api/playlists', {
			title: playlistTitle
		});
		await postJson(page, `/api/playlists/${playlist.id}/entries/generation`, {
			generation_id: take.id
		});
		await archiveOwnedAlbum(page.request, album.id);

		let foldedRailCoverRequests = 0;
		let railIsFolded = false;
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (
				railIsFolded &&
				request.method() === 'GET' &&
				url.pathname === `/api/albums/${album.id}/cover` &&
				url.searchParams.get('variant') === 'card'
			) {
				foldedRailCoverRequests += 1;
			}
		});

		await page.goto('/playlists');
		const wallPlaylistTile = page
			.locator('.library-wall .tile-grid')
			.getByRole('button', { name: `Open playlist ${playlistTitle}`, exact: true });
		const wallCover = wallPlaylistTile.locator('.playlist-cover-cell img');
		await expect(wallCover).toHaveCount(1);
		await expect(wallCover).toHaveJSProperty('complete', true);
		if (!isMobile) {
			const rail = await openRailNav(page, 'desktop');
			const playlistsGroup = rail.getByRole('button', {
				name: PLAYLISTS_PAGE_LABEL,
				exact: true
			});
			const collapsedMosaicRow = rail
				.locator('#rail-playlists-group li')
				.filter({ hasText: playlistTitle });
			// A group is unfolded on its own page (#1354 D3), so the rail row fetches its
			// cover there. Let that fetch finish, then fold the group with its caret:
			// from here on the rail must stay off the network.
			await expect(playlistsGroup).toHaveAttribute('aria-expanded', 'true');
			const unfoldedRailCover = collapsedMosaicRow.locator('.playlist-cover-cell img');
			await expect(unfoldedRailCover).toHaveCount(1);
			await expect(unfoldedRailCover).toHaveJSProperty('complete', true);
			railIsFolded = true;
			await playlistsGroup.click();
			await expect(playlistsGroup).toHaveAttribute('aria-expanded', 'false');
			await expect(collapsedMosaicRow.locator('.playlist-cover-cell')).toHaveCount(4);
			await expect(collapsedMosaicRow.locator('.playlist-cover-cell img')).toHaveCount(0);
			expect(foldedRailCoverRequests).toBe(0);
			const row = await railPlaylistRow(page, playlistTitle);

			await expect(row.locator('.playlist-cover-cell')).toHaveCount(4);
			await expect(row.locator('.playlist-cover-cell img')).toHaveCount(1);
			await expect(row.locator('.playlist-cover-initials')).toHaveCount(3);
			await row.getByRole('button', { name: new RegExp(`^${playlistTitle}`) }).click();
			await expect(page.getByRole('heading', { name: playlistTitle })).toBeVisible();
			await openPlaylistsPage(page, 'desktop');
		}
		await wallPlaylistTile.click();
		await expect(page.getByRole('heading', { name: playlistTitle })).toBeVisible();

		await page.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await page.getByRole('button', { name: 'Upload…', exact: true }).click();
		await page.locator('.cover-file-input').setInputFiles({
			name: 'playlist-cover.png',
			mimeType: 'image/png',
			buffer: COVER_PNG
		});
		const headerCover = page.locator('.collection-header .header-cover img');
		await expect(headerCover).toHaveAttribute(
			'src',
			new RegExp(`/api/playlists/${playlist.id}/cover\\?variant=detail`)
		);

		await openPlaylistsPage(page, isMobile ? 'mobile' : 'desktop');
		await expect(wallPlaylistTile.locator('.tile-cover img')).toHaveAttribute(
			'src',
			new RegExp(`/api/playlists/${playlist.id}/cover\\?variant=card`)
		);
		if (!isMobile) {
			const refreshedRow = await railPlaylistRow(page, playlistTitle);
			await expect(refreshedRow.locator('.playlist-cover-image')).toHaveAttribute(
				'src',
				new RegExp(`/api/playlists/${playlist.id}/cover\\?variant=card`)
			);
			const [railCoverBox, playlistCoverBox] = await Promise.all([
				refreshedRow.locator('.playlist-cover').boundingBox(),
				refreshedRow.locator('.playlist-cover-image').boundingBox()
			]);
			expect(playlistCoverBox).toEqual(railCoverBox);
		}

		await wallPlaylistTile.click();
		await expect(page.getByRole('heading', { name: playlistTitle })).toBeVisible();
		await page.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await page
			.getByRole('button', { name: COLLECTION_MENU_COVER_REMOVE_LABEL, exact: true })
			.click();
		await expect(page.locator('.collection-header .header-cover .playlist-cover-cell')).toHaveCount(
			4
		);

		await openPlaylistsPage(page, isMobile ? 'mobile' : 'desktop');
		await expect(wallPlaylistTile.locator('.playlist-cover-cell')).toHaveCount(4);
		if (!isMobile) {
			const restoredRow = await railPlaylistRow(page, playlistTitle);
			await expect(restoredRow.locator('.playlist-cover-cell')).toHaveCount(4);
		}
	} finally {
		try {
			if (playlist) await deleteOwnedPlaylist(page, playlist.id);
		} finally {
			await archiveOwnedAlbum(page.request, album.id);
		}
	}
});

// defect:#1091: the wall sized its covers '100%', so the initials came out a
// fraction of a pixel. Wall initials scale with the cover, with a readable floor on phone rows.
const INITIALS_SHARE_OF_COVER = 0.32;
const READABLE_INITIALS_PX = 14;

test('defect:#1091: a playlist without covers shows readable initials on the Playlists wall', async ({
	page
}) => {
	const playlistTitle = `E2E Plain Playlist ${Date.now().toString(36)}`;
	const playlist = await postJson<CreatedResource>(page, '/api/playlists', {
		title: playlistTitle
	});
	try {
		await page.goto('/playlists');
		const cover = page
			.locator('.library-wall .tile-grid')
			.getByRole('button', { name: `Open playlist ${playlistTitle}`, exact: true })
			.locator('.playlist-cover');
		const initials = cover.locator('.playlist-cover-initials').first();
		await expect(initials).toBeVisible();

		const coverWidth = (await cover.boundingBox())?.width ?? 0;
		const initialsSize = await initials.evaluate((cell) =>
			parseFloat(getComputedStyle(cell).fontSize)
		);

		expect(initialsSize).toBeGreaterThanOrEqual(READABLE_INITIALS_PX);
		expect(initialsSize).toBeCloseTo(
			Math.max(READABLE_INITIALS_PX, coverWidth * INITIALS_SHARE_OF_COVER),
			1
		);
	} finally {
		await deleteOwnedPlaylist(page, playlist.id);
	}
});
