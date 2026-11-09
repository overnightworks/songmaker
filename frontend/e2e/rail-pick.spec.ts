import { expect, test, type Page } from './coverage-test';
import { EDITOR_LYRICS_LABEL } from '../src/lib/constants/song';
import { RAIL_LIBRARY_NAV_LABEL, RAIL_NAV_LABEL } from '../src/lib/constants/rail';
import { NOW_PLAYING_UNPICK_LABEL } from '../src/lib/constants/now-playing';
import { archiveOwnedAlbum, seedTake } from './seed';
import { ONLY_IN_SHELL, sameOriginHeaders } from './helpers';

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
	const take = await seedTake(page.request, song.id);
	if (!options.picked) return song.id;
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
		const detail = await detailLoaded;
		await detail.finished();
		// Album list items carry no takes, so a take row exists only once the detail response is
		// merged into the song list, in the same update as its has_pick.
		await expect(
			page.getByRole('button', { name: new RegExp(`^${NOW_PLAYING_UNPICK_LABEL} take`) })
		).toBeVisible();
		// A later album-list refresh keeps the merged takes but takes has_pick from its summary, so the
		// detail response itself must carry the pick for the rail check below to prove it.
		expect(((await detail.json()) as { has_pick: boolean }).has_pick).toBe(true);
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
