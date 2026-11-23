// album_rule_12 in docs/navigation.md: every album song row carries ⋯ after its ✎, opening the
// song menu of that song without Save version; Rename turns the row title into the title field,
// Move › takes the song to another own album, and Delete asks first and offers Undo.
// The albums are this run's own, archived afterwards.

import { expect, test, type Page } from './coverage-test';
import { words } from '../src/lib/words/en';
import { archiveOwnedAlbum } from './seed';
import { sameOriginHeaders, FlowGuard, workspace } from './helpers';

interface CreatedResource {
	id: string;
}

async function postJson<T>(page: Page, url: string, data: unknown): Promise<T> {
	const response = await page.request.post(url, { headers: await sameOriginHeaders(page), data });
	expect(response.ok(), `POST ${url} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

test('album_rule_12: an album song row opens the song menu to rename, move and delete with undo', async ({
	page
}) => {
	const marker = Date.now().toString(36);
	const home = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Row Menu ${marker}`,
		artist: 'E2E Artist'
	});
	const target = await postJson<CreatedResource>(page, '/api/albums', {
		title: `E2E Row Menu Target ${marker}`,
		artist: 'E2E Artist'
	});
	try {
		for (const title of ['Rename', 'Move', 'Delete']) {
			await postJson(page, '/api/songs', {
				title: `${title} ${marker}`,
				album_id: home.id,
				lyrics: `${title} words`,
				prompt: 'quiet test song'
			});
		}

		const guard = new FlowGuard(page);
		await page.goto(`/album/${home.id}`);
		const surface = workspace(page);
		const rowOf = (title: string) => surface.locator('.song-row').filter({ hasText: title });
		const menu = page.locator('.menu-panel');

		await rowOf(`Rename ${marker}`).locator('.menu-trigger').click();
		await expect(menu.locator('.menu-item')).toContainText([
			words['songMenu.rename'],
			words['songMenu.move'],
			words['songMenu.addTo'],
			words['songMenu.share'],
			words['songMenu.delete']
		]);
		await expect(menu.getByRole('button', { name: words['songMenu.save'] })).toHaveCount(0);

		await menu.getByRole('button', { name: words['songMenu.rename'] }).click();
		const field = surface.getByRole('textbox', { name: words['songHeader.title'] });
		await expect(field).toBeFocused();
		await field.fill(`Renamed ${marker}`);
		await field.press('Enter');
		await expect(rowOf(`Renamed ${marker}`)).toBeVisible();
		await expect(field).toHaveCount(0);

		await rowOf(`Move ${marker}`).locator('.menu-trigger').click();
		await menu.getByRole('button', { name: words['songMenu.move'] }).click();
		await menu
			.locator('.pk-list .pk-row')
			.filter({ hasText: `Target ${marker}` })
			.click();
		await expect(rowOf(`Move ${marker}`)).toHaveCount(0);

		await rowOf(`Delete ${marker}`).locator('.menu-trigger').click();
		await menu.getByRole('button', { name: words['songMenu.delete'] }).click();
		await page.getByRole('button', { name: words['songPage.deleteConfirm'] }).click();
		await expect(rowOf(`Delete ${marker}`)).toHaveCount(0);
		await page.getByRole('button', { name: words['songPage.undo'] }).click();
		await expect(rowOf(`Delete ${marker}`)).toBeVisible();
		guard.assertClean();
	} finally {
		await archiveOwnedAlbum(page.request, home.id);
		await archiveOwnedAlbum(page.request, target.id);
	}
});
