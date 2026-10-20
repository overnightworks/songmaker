import { randomUUID } from 'node:crypto';
import { expect, request, test, type Page } from '@playwright/test';
import { EDITOR_OPEN_WORKER_POOL_LABEL, EDITOR_TAB_EDIT_LABEL } from '../src/lib/constants';
import { csrfHeaders, nameStartingWith, ONLY_IN_SHELL } from './helpers';
import {
	archiveOwnedAlbum,
	BASE_URL,
	createAccount,
	deleteAccount,
	runMarker,
	seedOwnSongAddress,
	seedSongPhoneSong,
	STORAGE_STATE_FILE
} from './seed';

const UNAVAILABLE = "Generating isn't available right now.";
const WIDTHS = [390, 1440] as const;
type Role = 'user' | 'admin';

// The admin case is the run's own session on a song it owns.
async function openAdminSong(page: Page): Promise<() => Promise<void>> {
	const response = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title: `E2E Generate Without Worker ${runMarker()}` }
	});
	expect(response.ok()).toBe(true);
	const album: { id: string } = await response.json();
	const title = `QA no worker ${runMarker()}`;
	await seedSongPhoneSong(album.id, title, 1, 1);
	await page.goto(`/album/${album.id}/${title.toLowerCase().replace(/\s+/g, '-')}`);
	return () => archiveOwnedAlbum(page.request, album.id);
}

// The user case is a real non-admin account, signed in, on a song it owns.
async function openUserSong(page: Page): Promise<() => Promise<void>> {
	const admin = await request.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE_FILE });
	const credentials = { username: `e2e-nowork-${randomUUID()}`, password: randomUUID() };
	const userId = await createAccount(admin, credentials.username, credentials.password);
	const account = await request.newContext({ baseURL: BASE_URL });
	const address = await seedOwnSongAddress(account, credentials, `QA no worker ${runMarker()}`);
	await page.context().clearCookies();
	await page.context().addCookies((await account.storageState()).cookies);
	await page.goto(address);
	return async () => {
		try {
			await deleteAccount(admin, userId);
		} finally {
			await account.dispose();
			await admin.dispose();
		}
	};
}

// CI's stack runs no ACE-Step worker and `/health` is not stubbed: the press
// reaches the real server, which refuses it and stores the failed job.
for (const width of WIDTHS) {
	for (const role of ['user', 'admin'] as const) {
		test(
			`a ${role} presses Generate without a worker at ${width}px and keeps the line after a reload`,
			{ tag: ONLY_IN_SHELL.desktop },
			async ({ page }) => {
				await page.setViewportSize({ width, height: 900 });
				const cleanup = await (role === 'admin' ? openAdminSong(page) : openUserSong(page));
				try {
					await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
					if (width === 390) {
						await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true }).click();
					}

					const action = page.locator('.generate-action:visible');
					const generate = action.getByRole('button', { name: nameStartingWith('Generate') });
					await expect(generate).toBeEnabled();
					await expect(action.locator('.reason')).toHaveCount(0);
					await generate.click();

					await expectLine(page, role);
					await expect(page.locator('.toast')).toHaveCount(0);

					await page.reload();
					await expectLine(page, role);
					await expect(page.locator('.toast')).toHaveCount(0);
				} finally {
					await cleanup();
				}
			}
		);
	}
}

async function expectLine(page: Page, role: Role): Promise<void> {
	const failure = page.locator('.generate-action:visible .failure');
	await expect(failure).toContainText(UNAVAILABLE);
	await expect(failure.getByRole('link', { name: EDITOR_OPEN_WORKER_POOL_LABEL })).toHaveCount(
		role === 'admin' ? 1 : 0
	);
}
