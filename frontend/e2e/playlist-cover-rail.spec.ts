import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';
import {
	COLLECTION_MENU_COVER_REMOVE_LABEL,
	COLLECTION_MENU_LABEL,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_NAV_LABEL,
	RAIL_PLAYLISTS_LABEL,
	RAIL_PLAYLISTS_NAV_LABEL
} from '../src/lib/constants';
import { BASE_URL } from './seed';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const COVER_PNG = readFileSync(path.join(E2E_DIR, '..', 'static', 'icon-192.png'));

interface CreatedResource {
	id: string;
	slug: string;
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
	const csrf = (await page.context().cookies(BASE_URL)).find(
		(cookie) => cookie.name === 'csrf_token'
	);
	if (!csrf) throw new Error('The E2E session has no CSRF token');
	return { 'x-csrf-token': csrf.value, origin: BASE_URL };
}

async function postJson<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { headers: await csrfHeaders(page), data });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

async function deleteOwnedPlaylist(page: Page, playlistId: string): Promise<void> {
	const response = await page.request.delete(`/api/playlists/${playlistId}`, {
		headers: await csrfHeaders(page)
	});
	expect(
		response.ok(),
		`DELETE /api/playlists/${playlistId} failed: ${await response.text()}`
	).toBeTruthy();
}

async function deleteOwnedAlbum(page: Page, albumId: string): Promise<void> {
	const response = await page.request.delete(`/api/albums/${albumId}`, {
		headers: await csrfHeaders(page)
	});
	expect(
		response.ok(),
		`DELETE /api/albums/${albumId} failed: ${await response.text()}`
	).toBeTruthy();
}

test('a playlist rail row shows its album-cover mosaic and opens with one click at desktop and 375 px', async ({
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
		headers: await csrfHeaders(page),
		multipart: {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(reimport.ok(), `Take import failed: ${await reimport.text()}`).toBeTruthy();
	const take = (await reimport.json()) as CreatedResource;
	const cover = await page.request.post(`/api/albums/${album.id}/cover`, {
		headers: await csrfHeaders(page),
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
		await postJson(page, `/api/albums/${album.id}/archive`, {});

		let wallCoverRequests = 0;
		let railCoverRequests = 0;
		let measuringRailCoverRequests = false;
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (
				request.method() === 'GET' &&
				url.pathname === `/api/albums/${album.id}/cover` &&
				url.searchParams.get('variant') === 'card'
			) {
				if (measuringRailCoverRequests) railCoverRequests += 1;
				else wallCoverRequests += 1;
			}
		});

		await page.goto('/');
		const wallPlaylistTile = page
			.locator('.library-wall .tile-grid')
			.getByRole('button', { name: `Open playlist ${playlistTitle}`, exact: true });
		await expect(wallPlaylistTile.locator('.playlist-cover-cell img')).toHaveCount(1);
		if (isMobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		const rail = isMobile
			? page
					.getByRole('dialog', { name: RAIL_DRAWER_LABEL })
					.getByRole('navigation', { name: RAIL_NAV_LABEL })
			: page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		const playlistsGroup = rail.getByRole('button', { name: RAIL_PLAYLISTS_LABEL, exact: true });
		const collapsedMosaicRow = rail
			.locator('#rail-playlists-group li')
			.filter({ hasText: playlistTitle });
		await expect(playlistsGroup).toHaveAttribute('aria-expanded', 'false');
		await expect(collapsedMosaicRow.locator('.playlist-cover-cell')).toHaveCount(4);
		await expect(collapsedMosaicRow.locator('.playlist-cover-cell img')).toHaveCount(0);
		// The visible 6C wall tile legitimately consumes one lazy image request.
		// Count it separately: the collapsed rail has no image element and must not request a cover.
		expect(wallCoverRequests).toBe(1);
		measuringRailCoverRequests = true;
		expect(railCoverRequests).toBe(0);
		if ((await playlistsGroup.getAttribute('aria-expanded')) === 'false')
			await playlistsGroup.click();
		const row = rail
			.getByRole('navigation', { name: RAIL_PLAYLISTS_NAV_LABEL })
			.getByRole('listitem')
			.filter({ hasText: playlistTitle });

		await expect(row.locator('.playlist-cover-cell')).toHaveCount(4);
		await expect(row.locator('.playlist-cover-cell img')).toHaveCount(1);
		await expect(row.locator('.playlist-cover-initials')).toHaveCount(3);
		await row.getByRole('button', { name: new RegExp(`^${playlistTitle}`) }).click();
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

		await page
			.locator('.collection-header')
			.getByRole('button', { name: RAIL_LIBRARY_LABEL, exact: true })
			.click();
		await expect(wallPlaylistTile.locator('.tile-cover img')).toHaveAttribute(
			'src',
			new RegExp(`/api/playlists/${playlist.id}/cover\\?variant=card`)
		);
		if (isMobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		const refreshedRail = isMobile
			? page
					.getByRole('dialog', { name: RAIL_DRAWER_LABEL })
					.getByRole('navigation', { name: RAIL_NAV_LABEL })
			: page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		const refreshedPlaylistsGroup = refreshedRail.getByRole('button', {
			name: RAIL_PLAYLISTS_LABEL,
			exact: true
		});
		if ((await refreshedPlaylistsGroup.getAttribute('aria-expanded')) === 'false') {
			await refreshedPlaylistsGroup.click();
		}
		const refreshedRow = refreshedRail
			.getByRole('navigation', { name: RAIL_PLAYLISTS_NAV_LABEL })
			.getByRole('listitem')
			.filter({ hasText: playlistTitle });
		await expect(refreshedRow.locator('.playlist-cover-image')).toHaveAttribute(
			'src',
			new RegExp(`/api/playlists/${playlist.id}/cover\\?variant=card`)
		);
		const [railCoverBox, playlistCoverBox] = await Promise.all([
			refreshedRow.locator('.playlist-cover').boundingBox(),
			refreshedRow.locator('.playlist-cover-image').boundingBox()
		]);
		expect(playlistCoverBox).toEqual(railCoverBox);
		if (isMobile) {
			await page.keyboard.press('Escape');
			await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeHidden();
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

		await page
			.locator('.collection-header')
			.getByRole('button', { name: RAIL_LIBRARY_LABEL, exact: true })
			.click();
		await expect(wallPlaylistTile.locator('.playlist-cover-cell')).toHaveCount(4);
		if (isMobile) await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		const restoredRail = isMobile
			? page
					.getByRole('dialog', { name: RAIL_DRAWER_LABEL })
					.getByRole('navigation', { name: RAIL_NAV_LABEL })
			: page.getByRole('navigation', { name: RAIL_NAV_LABEL });
		const restoredPlaylistsGroup = restoredRail.getByRole('button', {
			name: RAIL_PLAYLISTS_LABEL,
			exact: true
		});
		if ((await restoredPlaylistsGroup.getAttribute('aria-expanded')) === 'false') {
			await restoredPlaylistsGroup.click();
		}
		const restoredRow = restoredRail
			.getByRole('navigation', { name: RAIL_PLAYLISTS_NAV_LABEL })
			.getByRole('listitem')
			.filter({ hasText: playlistTitle });
		await expect(restoredRow.locator('.playlist-cover-cell')).toHaveCount(4);
	} finally {
		try {
			if (playlist) await deleteOwnedPlaylist(page, playlist.id);
		} finally {
			await deleteOwnedAlbum(page, album.id);
		}
	}
});
