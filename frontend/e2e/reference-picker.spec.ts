// The recipe's Reference track row is a picker: a reference uploaded from the opened row is
// chosen, saved with the version and still named after a reload. The flow uses an account of
// its own so the list holds only what it uploads.

import { readFileSync } from 'node:fs';
import { expect, test } from './coverage-test';
import { FlowGuard, workspace } from './helpers';
import {
	archiveOwnedAlbum,
	BASE_URL,
	runMarker,
	seedAccount,
	signedInApi,
	TAKE_FIXTURE
} from './seed';
import { words } from '../src/lib/words/en';

test.use({ storageState: { cookies: [], origins: [] } });

test('A reference uploaded from the recipe is chosen, saved with the version and named after a reload', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await seedAccount(`e2e-reference-picker-${testInfo.project.name}-${runMarker()}`);
	await context.addCookies(account.cookies);
	const api = await signedInApi(account);
	const filename = `picker-${runMarker()}.mp3`;
	const title = `Reference picker ${runMarker()}`;
	let albumId: string | undefined;
	try {
		const headers = { origin: BASE_URL };
		const album = await api.post('/api/albums', {
			headers,
			data: { title: `E2E reference picker ${runMarker()}`, artist: 'E2E' }
		});
		expect(album.ok(), await album.text()).toBeTruthy();
		albumId = ((await album.json()) as { id: string }).id;
		const song = await api.post('/api/songs', { headers, data: { title, album_id: albumId } });
		expect(song.ok(), await song.text()).toBeTruthy();

		await page.goto(`/album/${albumId}`);
		await workspace(page)
			.getByRole('button', { name: words['songRow.openInEditor']({ title: title }) })
			.click();
		await expect(page.getByRole('heading', { name: title })).toBeVisible();
		await page.locator('.recipe-line').click();
		const recipe = page.getByRole('region', { name: words['recipe.panel'], exact: true });
		await recipe
			.getByRole('button', { name: new RegExp(`^${words['referencePicker.label']}:`) })
			.click();

		await recipe.locator('input[type="file"]').setInputFiles({
			name: filename,
			mimeType: 'audio/mpeg',
			buffer: readFileSync(TAKE_FIXTURE)
		});
		await expect(recipe.getByLabel(filename, { exact: true })).toBeChecked();

		await page.getByRole('button', { name: words['songMenu.label'], exact: true }).click();
		const saved = page.waitForResponse(
			(response) =>
				response.url().includes('/api/songs/') &&
				response.request().method() === 'PUT' &&
				response.ok()
		);
		await page.getByRole('button', { name: words['songMenu.save'], exact: true }).click();
		await saved;

		await page.reload();
		await page.locator('.recipe-line').click();
		await expect(
			page
				.getByRole('region', { name: words['recipe.panel'], exact: true })
				.getByRole('button', { name: words['referencePicker.chosen']({ name: filename }) })
		).toBeVisible();
		guard.assertClean();
	} finally {
		try {
			if (albumId) await archiveOwnedAlbum(api, albumId);
		} finally {
			await api.dispose();
		}
	}
});
