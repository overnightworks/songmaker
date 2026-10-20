import { expect, test as base, type Page } from '@playwright/test';
import { EDITOR_OPEN_WORKER_POOL_LABEL, EDITOR_TAB_EDIT_LABEL } from '../src/lib/constants';
import { csrfHeaders, nameStartingWith, ONLY_IN_SHELL } from './helpers';
import { archiveOwnedAlbum, runMarker, seedSongPhoneSong } from './seed';

const UNAVAILABLE = "Generating isn't available right now.";
const WIDTHS = [390, 1440] as const;
const ROLES = ['user', 'admin'] as const;

const test = base.extend<{ albumId: string }>({
	albumId: async ({ page }, use) => {
		const response = await page.request.post('/api/albums', {
			headers: await csrfHeaders(page),
			data: { title: `E2E Generate Without Worker ${runMarker()}` }
		});
		expect(response.ok()).toBe(true);
		const album: { id: string } = await response.json();
		try {
			await use(album.id);
		} finally {
			await archiveOwnedAlbum(page.request, album.id);
		}
	}
});

// CI's stack runs no ACE-Step worker and `/health` is not stubbed: the press
// reaches the real server, which refuses it and stores the failed job.
for (const width of WIDTHS) {
	for (const role of ROLES) {
		test(
			`a ${role} presses Generate without a worker at ${width}px and keeps the line after a reload`,
			{ tag: ONLY_IN_SHELL.desktop },
			async ({ page, albumId }) => {
				await page.setViewportSize({ width, height: 900 });
				await page.route('**/api/auth/me', async (route) => {
					const response = await route.fetch();
					const user = await response.json();
					await route.fulfill({ response, json: { ...user, role } });
				});
				const title = `QA no worker ${runMarker()}`;
				await seedSongPhoneSong(albumId, title, 1, 1);
				await page.goto(`/album/${albumId}/${title.toLowerCase().replace(/\s+/g, '-')}`);
				await expect(page.getByRole('heading', { name: title })).toBeVisible();
				if (width === 390) {
					await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true }).click();
				}

				const generate = page
					.locator('.generate-action:visible')
					.getByRole('button', { name: nameStartingWith('Generate') });
				await expect(generate).toBeEnabled();
				await generate.click();

				await expectLine(page, role);
				await expect(page.locator('.toast')).toHaveCount(0);

				await page.reload();
				await expectLine(page, role);
				await expect(page.locator('.toast')).toHaveCount(0);
			}
		);
	}
}

async function expectLine(page: Page, role: (typeof ROLES)[number]): Promise<void> {
	const failure = page.locator('.generate-action:visible .failure');
	await expect(failure).toContainText(UNAVAILABLE);
	await expect(failure.getByRole('link', { name: EDITOR_OPEN_WORKER_POOL_LABEL })).toHaveCount(
		role === 'admin' ? 1 : 0
	);
}
