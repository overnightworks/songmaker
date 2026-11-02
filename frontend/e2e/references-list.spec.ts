// Settings › References lists a person's uploaded recordings and plays each one (picture
// docs/design/references.html): filename, length and upload day, a play button, and an empty
// state before the first upload. Every flow uses an account of its own
// so the list starts empty and holds only what the flow uploads.

import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type BrowserContext } from '@playwright/test';

import { FlowGuard, LIBRARY_PATH, openSettingsSection, shellOf, workspace } from './helpers';
import {
	BASE_URL,
	runMarker,
	seedAccount,
	signedInApi,
	TAKE_FIXTURE,
	type SeededAccount
} from './seed';

const REFERENCES_PATH = '/api/references';
const EMPTY_SENTENCE = "No references yet — upload a recording to guide a song's sound.";
const LENGTH_AND_DAY = /^\d+:\d{2} · \d{1,2} [A-Z][a-z]{2}( \d{4})?$/;

test.use({ storageState: { cookies: [], origins: [] } });

async function postReferenceAudio(api: APIRequestContext, filename: string): Promise<void> {
	const response = await api.post(REFERENCES_PATH, {
		headers: { origin: BASE_URL },
		multipart: {
			file: { name: filename, mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		}
	});
	expect(response.ok(), `Reference upload failed: ${await response.text()}`).toBeTruthy();
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
		guard.assertClean();
	} finally {
		await api.dispose();
	}
});
