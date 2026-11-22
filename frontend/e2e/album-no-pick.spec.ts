// album_rule_11 in docs/navigation.md: an album song row with takes and no
// Pick carries a No Pick badge, a song without takes carries none, the header
// counts the songs without a Pick, and the album's share page shows neither.
// The album is this run's own, archived afterwards.

import { expect, test, type Page } from './coverage-test';
import { words } from '../src/lib/words/en';
import { archiveOwnedAlbum, seedTake } from './seed';
import { sameOriginHeaders, FlowGuard, workspace } from './helpers';

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

async function createSong(page: Page, albumId: string, title: string): Promise<CreatedResource> {
	return postJson<CreatedResource>(page, '/api/songs', {
		title,
		album_id: albumId,
		lyrics: `${title} words`,
		prompt: 'quiet test song'
	});
}

test('album_rule_11: a seeded album with one song without a Pick shows the badge and the count, and its share page shows neither', async ({
	page,
	browser,
	isMobile
}) => {
	const marker = Date.now().toString(36);
	const album = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E No Pick ${marker}`,
		artist: 'E2E Artist'
	});
	try {
		const picked = await createSong(page, album.id, `Picked ${marker}`);
		const waiting = await createSong(page, album.id, `Waiting ${marker}`);
		await createSong(page, album.id, `Empty ${marker}`);
		const pickedTake = await seedTake(page.request, picked.id);
		await seedTake(page.request, waiting.id);
		await postJson(page, `/api/generations/${pickedTake.id}/pick`, {});
		const share = await postJson<ShareResult>(page, `/api/albums/${album.id}/share`, {});

		const guard = new FlowGuard(page);
		await page.goto(`/album/${album.id}`);
		const surface = workspace(page);
		const rowOf = (title: string) => surface.locator('.song-row').filter({ hasText: title });
		const badge = words['songRow.noPick'];
		await expect(rowOf(`Waiting ${marker}`).getByText(badge, { exact: true })).toBeVisible();
		await expect(rowOf(`Picked ${marker}`).getByText(badge, { exact: true })).toHaveCount(0);
		await expect(rowOf(`Empty ${marker}`).getByText(badge, { exact: true })).toHaveCount(0);
		await expect(surface.locator('.collection-header .header-count')).toHaveText(
			`${words['collectionHeader.songCount'](3)} · ${words['collectionHeader.withoutPick']({ count: 1 })}`
		);
		guard.assertClean();

		const publicContext = await browser.newContext({
			storageState: undefined,
			viewport: page.viewportSize(),
			isMobile: Boolean(isMobile),
			hasTouch: Boolean(isMobile)
		});
		try {
			const publicPage = await publicContext.newPage();
			await publicPage.goto(share.share_url);
			await expect(publicPage.locator('.now-playing.page')).toBeVisible();
			await expect(publicPage.getByText(badge, { exact: true })).toHaveCount(0);
			await expect(
				publicPage.getByText(words['collectionHeader.withoutPick']({ count: 1 }))
			).toHaveCount(0);
		} finally {
			await publicContext.close();
		}
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
});
