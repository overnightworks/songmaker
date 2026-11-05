import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page } from '@playwright/test';
import { EDITOR_LYRICS_LABEL, RAIL_LIBRARY_NAV_LABEL, RAIL_NAV_LABEL } from '../src/lib/constants';
import { NOW_PLAYING_UNPICK_LABEL } from '../src/lib/constants/now-playing';
import { archiveOwnedAlbum } from './seed';
import { ONLY_IN_SHELL, sameOriginHeaders } from './helpers';

const TAKE_FIXTURE = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	'fixtures',
	'take.mp3'
);

interface CreatedResource {
	id: string;
}

async function postJson<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { headers: await sameOriginHeaders(page), data });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

async function createSongWithTake(
	page: Page,
	albumId: string,
	title: string,
	options: { picked: boolean }
): Promise<string> {
	const song = await postJson<CreatedResource>(page, '/api/songs', {
		title,
		lyrics: 'A pick the rail must show.',
		album_id: albumId,
		prompt: 'quiet test song'
	});
	const imported = await page.request.post(`/api/songs/${song.id}/reimport`, {
		headers: await sameOriginHeaders(page),
		multipart: {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(imported.ok(), `Take import failed: ${await imported.text()}`).toBeTruthy();
	if (!options.picked) return song.id;
	const take = (await imported.json()) as CreatedResource;
	await postJson(page, `/api/generations/${take.id}/pick`, {});
	return song.id;
}

test(`${ONLY_IN_SHELL.desktop} rail rows show a song's pick while only its album is open, and after the song opens`, async ({
	page
}) => {
	const marker = Date.now().toString(36);
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Rail Pick ${marker}`,
		artist: 'E2E Ensemble'
	});
	const pickedTitle = `Picked ${marker}`;
	const unpickedTitle = `Unpicked ${marker}`;
	try {
		const pickedId = await createSongWithTake(page, album.id, pickedTitle, { picked: true });
		await createSongWithTake(page, album.id, unpickedTitle, { picked: false });

		await page.goto(`/album/${album.id}`);
		const railLibrary = page
			.getByRole('navigation', { name: RAIL_NAV_LABEL })
			.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL });
		const pickedRow = railLibrary.getByRole('button', { name: new RegExp(pickedTitle) });
		const unpickedRow = railLibrary.getByRole('button', { name: new RegExp(unpickedTitle) });

		await expect(pickedRow).toContainText('1 take · pick');
		await expect(unpickedRow).toContainText('1 take');
		await expect(unpickedRow).not.toContainText('· pick');

		const detailLoaded = page.waitForResponse(
			(response) =>
				response.request().method() === 'GET' &&
				new URL(response.url()).pathname === `/api/songs/${pickedId}` &&
				response.status() === 200
		);
		await pickedRow.click();
		await (await detailLoaded).finished();
		// Album list items carry no takes, so a take row exists only once the detail response is
		// merged into the song list, in the same update as its has_pick.
		await expect(
			page.getByRole('button', { name: new RegExp(`^${NOW_PLAYING_UNPICK_LABEL} take`) })
		).toBeVisible();
		await expect(
			page.getByRole('textbox', { name: new RegExp(`^${EDITOR_LYRICS_LABEL}`) })
		).toBeVisible();
		await expect(page).toHaveURL(/\/album\/[^/]+\/[^/]+/);
		await expect(pickedRow).toContainText('1 take · pick');
		await expect(unpickedRow).not.toContainText('· pick');
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
});
