// Settings › References lists a person's uploaded recordings and plays each one: filename,
// length and upload day, a play button, and an empty state before the first upload. Every flow
// uses an account of its own so the list starts empty and holds only what the flow uploads.

import { readFileSync } from 'node:fs';
import {
	expect,
	test,
	type APIRequestContext,
	type BrowserContext,
	type Page
} from './coverage-test';

import { FlowGuard, LIBRARY_PATH, openSettingsSection, shellOf, workspace } from './helpers';
import {
	archiveOwnedAlbum,
	BASE_URL,
	runMarker,
	seedAccount,
	signedInApi,
	TAKE_FIXTURE,
	type SeededAccount
} from './seed';

const REFERENCES_PATH = '/api/references';
const EMPTY_SENTENCE = "No references yet — upload a recording to guide a song's sound.";
const LENGTH_AND_DAY = /^\d+:\d{2} · \d{1,2} [A-Z][a-z]{2}( \d{4})?( ⏳ \d+d)?$/;
const COUNTDOWN = /^⏳ \d+d$/;

test.use({ storageState: { cookies: [], origins: [] } });

/** Archives the test's album and always disposes `api`; an archive failure surfaces only when the test itself passed, so it never masks the test's own error. */
async function cleanUp(
	api: APIRequestContext,
	albumId: string | undefined,
	testPassed: boolean
): Promise<void> {
	try {
		if (albumId) await archiveOwnedAlbum(api, albumId);
	} catch (archiveError) {
		if (testPassed) throw archiveError;
	} finally {
		await api.dispose();
	}
}

async function postReferenceAudio(api: APIRequestContext, filename: string): Promise<string> {
	const response = await api.post(REFERENCES_PATH, {
		headers: { origin: BASE_URL },
		multipart: {
			file: { name: filename, mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(response.ok(), `Reference upload failed: ${await response.text()}`).toBeTruthy();
	return ((await response.json()) as { id: string }).id;
}

async function postJson<T>(api: APIRequestContext, path: string, data: object): Promise<T> {
	const response = await api.post(path, { headers: { origin: BASE_URL }, data });
	expect(response.ok(), `${path} failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as T;
}

async function linkReferenceToSong(
	api: APIRequestContext,
	referenceId: string
): Promise<{ albumId: string; songId: string }> {
	const album = await postJson<{ id: string }>(api, '/api/albums', {
		title: `E2E reference album ${runMarker()}`,
		artist: 'E2E'
	});
	const song = await postJson<{ id: string }>(api, '/api/songs', {
		title: 'E2E reference song',
		album_id: album.id,
		reference_recording_id: referenceId
	});
	return { albumId: album.id, songId: song.id };
}

async function trackCreatedAudio(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const Original = window.Audio;
		window.Audio = function (...args: ConstructorParameters<typeof Audio>) {
			const element = new Original(...args);
			(window as unknown as { createdAudio: HTMLAudioElement[] }).createdAudio = [
				...((window as unknown as { createdAudio?: HTMLAudioElement[] }).createdAudio ?? []),
				element
			];
			return element;
		} as unknown as typeof Audio;
	});
}

async function previewIsAdvancing(page: Page): Promise<boolean> {
	return page.evaluate(() => {
		const previews = (window as unknown as { createdAudio: HTMLAudioElement[] }).createdAudio;
		const preview = previews[previews.length - 1];
		return preview.currentTime > 0 && (!preview.paused || preview.ended) && !preview.error;
	});
}

async function signInFreshAccount(
	context: BrowserContext,
	name: string,
	projectName: string
): Promise<SeededAccount> {
	const account = await seedAccount(`e2e-${name}-${projectName}-${runMarker()}`);
	await context.addCookies(account.cookies);
	return account;
}

test('Settings › References shows an uploaded recording with its filename, length and day', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-list', testInfo.project.name);
	const api = await signedInApi(account);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');

		await page.goto(LIBRARY_PATH);
		await openSettingsSection(page, shellOf(testInfo), 'References');

		await expect(page).toHaveURL(/\/settings\/references$/);
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });
		await expect(row).toBeVisible();
		await expect(row.locator('.reference-meta')).toHaveText(LENGTH_AND_DAY);
		await expect(row.locator('.reference-meta .exp')).toHaveText(COUNTDOWN);
		const rowBox = await row.boundingBox();
		const viewport = page.viewportSize();
		expect(rowBox?.width ?? Infinity).toBeLessThanOrEqual(viewport?.width ?? 0);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References says what references are for before the first upload', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	await signInFreshAccount(context, 'references-empty', testInfo.project.name);

	await page.goto('/settings/references');

	await expect(workspace(page).getByText(EMPTY_SENTENCE)).toBeVisible();
	await expect(workspace(page).getByRole('listitem')).toHaveCount(0);
	guard.assertClean();
});

test('Settings › References plays a recording from its button and pauses it again', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-play', testInfo.project.name);
	const api = await signedInApi(account);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });
		const served = page.waitForResponse(
			(response) => /\/api\/references\/[^/]+\/audio$/.test(response.url()) && response.ok()
		);

		await row.getByRole('button', { name: 'Play storytime-drums.mp3' }).click();

		await served;
		await expect(row.getByRole('button', { name: 'Pause storytime-drums.mp3' })).toBeVisible();
		await expect(row).toHaveClass(/playing/);

		await row.getByRole('button', { name: 'Pause storytime-drums.mp3' }).click();

		await expect(row.getByRole('button', { name: 'Play storytime-drums.mp3' })).toBeVisible();
		await expect(row).not.toHaveClass(/playing/);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References plays a recording again after its first audio answer failed', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page, {
		refusalsExpectedOn: [{ path: `${REFERENCES_PATH}/`, statuses: [429] }]
	});
	const account = await signInFreshAccount(context, 'references-retry', testInfo.project.name);
	const api = await signedInApi(account);
	const audioRoute = /\/api\/references\/[^/]+\/audio$/;
	await trackCreatedAudio(page);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });
		await page.route(audioRoute, (route) => route.fulfill({ status: 429 }), { times: 1 });

		await row.getByRole('button', { name: 'Play storytime-drums.mp3' }).click();

		await expect(row.getByRole('alert')).toHaveText("Can't play this recording");
		const served = page.waitForResponse(
			(response) => audioRoute.test(response.url()) && response.ok()
		);

		await row.getByRole('button', { name: 'Play storytime-drums.mp3' }).click();

		await served;
		await expect(row.getByRole('button', { name: 'Pause storytime-drums.mp3' })).toBeVisible();
		await expect(row.getByRole('alert')).toHaveCount(0);
		await expect.poll(() => previewIsAdvancing(page)).toBe(true);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References uploads a recording through the file chooser, lists it first and plays it', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-upload', testInfo.project.name);
	const api = await signedInApi(account);
	await trackCreatedAudio(page);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		await expect(workspace(page).getByRole('listitem')).toHaveCount(1);

		const chooser = page.waitForEvent('filechooser');
		await workspace(page).getByRole('button', { name: 'Upload' }).click();
		await (
			await chooser
		).setFiles({
			name: 'synth-hook.mp3',
			mimeType: 'audio/mpeg',
			buffer: readFileSync(TAKE_FIXTURE)
		});

		const row = workspace(page).getByRole('listitem').filter({ hasText: 'synth-hook.mp3' });
		await expect(row).toBeVisible();
		await expect(workspace(page).getByRole('listitem').first()).toContainText('synth-hook.mp3');
		await expect(row.locator('.reference-meta')).toHaveText(LENGTH_AND_DAY);
		await expect(workspace(page).getByRole('button', { name: 'Upload' })).toBeEnabled();
		const served = page.waitForResponse(
			(response) => /\/api\/references\/[^/]+\/audio$/.test(response.url()) && response.ok()
		);

		await row.getByRole('button', { name: 'Play synth-hook.mp3' }).click();

		await served;
		await expect(row).toHaveClass(/playing/);
		await expect.poll(() => previewIsAdvancing(page)).toBe(true);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References deletes an unused recording from its menu after a confirmation', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-delete', testInfo.project.name);
	const api = await signedInApi(account);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });

		await row.getByRole('button', { name: 'Reference menu' }).click();
		await page
			.getByRole('dialog', { name: 'Reference menu' })
			.getByRole('button', { name: 'Delete' })
			.click();
		const confirm = page.getByRole('dialog', { name: 'Delete reference?' });
		await expect(confirm).toContainText('its audio file');
		await confirm.getByRole('button', { name: 'Delete' }).click();

		await expect(workspace(page).getByText(EMPTY_SENTENCE)).toBeVisible();
		await expect(workspace(page).getByRole('listitem')).toHaveCount(0);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References keeps and unkeeps a recording with its heart, without starting the preview', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-keep', testInfo.project.name);
	const api = await signedInApi(account);
	await trackCreatedAudio(page);
	try {
		await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });
		const keep = row.getByRole('button', { name: 'Keep storytime-drums.mp3' });
		await expect(keep).toHaveAttribute('aria-pressed', 'false');

		await keep.click();

		const unkeep = row.getByRole('button', { name: 'Unkeep storytime-drums.mp3' });
		await expect(unkeep).toHaveAttribute('aria-pressed', 'true');
		expect(
			await page.evaluate(() => (window as unknown as { createdAudio?: unknown[] }).createdAudio)
		).toBeUndefined();
		const rowBox = await row.boundingBox();
		expect(rowBox?.width ?? Infinity).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);

		await page.reload();
		await expect(row.getByRole('button', { name: 'Unkeep storytime-drums.mp3' })).toHaveAttribute(
			'aria-pressed',
			'true'
		);

		await row.getByRole('button', { name: 'Unkeep storytime-drums.mp3' }).click();

		await expect(row.getByRole('button', { name: 'Keep storytime-drums.mp3' })).toHaveAttribute(
			'aria-pressed',
			'false'
		);
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});

test('Settings › References greys Delete for a recording a song uses', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-in-use', testInfo.project.name);
	const api = await signedInApi(account);
	let albumId: string | undefined;
	let testPassed = false;
	try {
		({ albumId } = await linkReferenceToSong(
			api,
			await postReferenceAudio(api, 'storytime-drums.mp3')
		));
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });

		await row.getByRole('button', { name: 'Reference menu' }).click();

		const choice = page.getByRole('dialog', { name: 'Reference menu' }).getByRole('button', {
			name: /Delete\s*In use/
		});
		await expect(choice).toBeDisabled();
		guard.assertClean();
		testPassed = true;
	} finally {
		await cleanUp(api, albumId, testPassed);
	}
});

test('Settings › References shows the in-use notice on the row when a song took the recording after the page loaded', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page, {
		refusalsExpectedOn: [{ path: `${REFERENCES_PATH}/`, statuses: [409] }]
	});
	const account = await signInFreshAccount(context, 'references-conflict', testInfo.project.name);
	const api = await signedInApi(account);
	let albumId: string | undefined;
	let testPassed = false;
	try {
		const referenceId = await postReferenceAudio(api, 'storytime-drums.mp3');
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });
		await expect(row).toBeVisible();
		({ albumId } = await linkReferenceToSong(api, referenceId));

		await row.getByRole('button', { name: 'Reference menu' }).click();
		await page
			.getByRole('dialog', { name: 'Reference menu' })
			.getByRole('button', { name: 'Delete' })
			.click();
		await page
			.getByRole('dialog', { name: 'Delete reference?' })
			.getByRole('button', { name: 'Delete' })
			.click();

		await expect(row.getByRole('alert')).toHaveText('In use — not deleted.');
		await row.getByRole('button', { name: 'Reference menu' }).click();
		await expect(
			page.getByRole('dialog', { name: 'Reference menu' }).getByRole('button', { name: /Delete/ })
		).toBeDisabled();
		guard.assertClean();
		testPassed = true;
	} finally {
		await cleanUp(api, albumId, testPassed);
	}
});

test('Settings › References shows where a recording is used and links to the song', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-uses', testInfo.project.name);
	const api = await signedInApi(account);
	let albumId: string | undefined;
	let testPassed = false;
	try {
		({ albumId } = await linkReferenceToSong(
			api,
			await postReferenceAudio(api, 'storytime-drums.mp3')
		));
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });

		await row.getByRole('button', { name: 'Used in 1 version' }).click();
		await page.evaluate(() => {
			(window as unknown as { __clientSideMarker: boolean }).__clientSideMarker = true;
		});
		await row.getByRole('link', { name: /Version v1/ }).click();

		await expect(page).toHaveURL(new RegExp(`/album/${albumId}/`));
		expect(
			await page.evaluate(
				() => (window as unknown as { __clientSideMarker?: boolean }).__clientSideMarker
			),
			'The link must navigate client-side, not reload the document'
		).toBe(true);
		guard.assertClean();
		testPassed = true;
	} finally {
		await cleanUp(api, albumId, testPassed);
	}
});

test('Settings › References tags a deleted song without a link', async ({
	context,
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const account = await signInFreshAccount(context, 'references-deleted', testInfo.project.name);
	const api = await signedInApi(account);
	let albumId: string | undefined;
	let testPassed = false;
	try {
		const linked = await linkReferenceToSong(
			api,
			await postReferenceAudio(api, 'storytime-drums.mp3')
		);
		albumId = linked.albumId;
		const deletion = await api.delete(`/api/songs/${linked.songId}`, {
			headers: { origin: BASE_URL }
		});
		expect(deletion.ok(), `Song delete failed: ${await deletion.text()}`).toBeTruthy();
		await page.goto('/settings/references');
		const row = workspace(page).getByRole('listitem').filter({ hasText: 'storytime-drums.mp3' });

		await row.getByRole('button', { name: 'Used in 1 version' }).click();

		await expect(row.getByText('Deleted')).toBeVisible();
		await expect(row.getByText('Version v1')).toBeVisible();
		await expect(row.getByRole('link')).toHaveCount(0);
		guard.assertClean();
		testPassed = true;
	} finally {
		await cleanUp(api, albumId, testPassed);
	}
});
