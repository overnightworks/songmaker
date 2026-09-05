import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';
import {
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_NAV_LABEL
} from '../src/lib/constants';
import { BASE_URL } from './seed';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const COVER_PNG = readFileSync(path.join(E2E_DIR, '..', 'static', 'icon-192.png'));

interface CreatedResource {
	id: string;
}

interface ShareResult {
	share_url: string;
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

async function postCover(page: Page, albumId: string): Promise<void> {
	const response = await page.request.post(`/api/albums/${albumId}/cover`, {
		headers: await csrfHeaders(page),
		multipart: {
			file: { name: 'cover.png', mimeType: 'image/png', buffer: COVER_PNG }
		}
	});
	expect(response.ok(), `Cover upload failed: ${await response.text()}`).toBeTruthy();
}

async function openRail(page: Page, isMobile: boolean) {
	if (isMobile) {
		const drawer = page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
		if (!(await drawer.isVisible())) {
			await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		}
	}
	return page.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

test('a fresh album cover reaches wall, album header, rail, and every share page at desktop and 375 px', async ({
	page,
	browser,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const marker = Date.now().toString(36);
	const albumTitle = `E2E Cover Rail ${marker}`;
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: albumTitle,
		artist: 'E2E Cover Artist'
	});
	const song = await postJson<CreatedResource>(page, '/api/songs', {
		title: `E2E Cover Song ${marker}`,
		album_id: album.id,
		lyrics: 'A cover belongs to this album.',
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
	await postCover(page, album.id);

	const [albumShare, songShare, takeShare] = await Promise.all([
		postJson<ShareResult>(page, `/api/albums/${album.id}/share`, {}),
		postJson<ShareResult>(page, `/api/songs/${song.id}/share`, {}),
		postJson<ShareResult>(page, `/api/generations/${take.id}/share`, {})
	]);

	await page.goto('/');
	const wallTile = page.locator('.wall-tile').filter({ hasText: albumTitle });
	await expect(wallTile.locator('.tile-cover img')).toBeVisible();
	await expect(wallTile.locator('.tile-cover img')).toHaveAttribute('alt', `Album ${albumTitle}`);

	await page.goto(`/album/${album.id}`);
	await expect(page.locator('.collection-header .header-cover img')).toBeVisible();
	const rail = await openRail(page, Boolean(isMobile));
	const libraryGroup = rail.getByRole('button', { name: new RegExp(`^${RAIL_LIBRARY_LABEL}`) });
	if ((await libraryGroup.getAttribute('aria-expanded')) === 'false') await libraryGroup.click();
	const railAlbum = rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('listitem')
		.filter({ hasText: albumTitle });
	await expect(railAlbum.getByRole('img', { name: `Album ${albumTitle}` })).toBeVisible();

	const publicContext = await browser.newContext({ storageState: undefined });
	try {
		for (const share of [albumShare, songShare, takeShare]) {
			const publicPage = await publicContext.newPage();
			await publicPage.goto(share.share_url);
			await expect(publicPage.locator('.header-cover img')).toBeVisible();
			await expect(publicPage.locator('.header-cover img')).toHaveAttribute(
				'alt',
				`Album ${albumTitle}`
			);
			await publicPage.close();
		}
	} finally {
		await publicContext.close();
	}
});
