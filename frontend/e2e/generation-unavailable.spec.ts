import { expect, test as base, type Locator, type Page } from '@playwright/test';
import type { JobItem } from '../src/lib/api/types';
import {
	ADMIN_TABS_LABEL,
	ADMIN_WORKER_POOL_HREF,
	DIALOG_CANCEL_LABEL,
	EDITOR_OPEN_WORKER_POOL_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_SAVE_LABEL,
	EDITOR_UNSAVED_TITLE,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { csrfHeaders, ONLY_IN_SHELL } from './helpers';
import {
	archiveOwnedAlbum,
	failGenerationJob,
	runMarker,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

const test = base.extend<{ albumId: string }>({
	albumId: async ({ page }, use) => {
		const response = await page.request.post('/api/albums', {
			headers: await csrfHeaders(page),
			data: { title: `E2E Generation Unavailable ${runMarker()}` }
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

const UNAVAILABLE = "Generating isn't available right now.";
const WIDTHS = [390, 1440] as const;
const ROLES = ['user', 'admin'] as const;
const SOURCES = ['live', 'reload'] as const;

// This slice consumes already classified jobs and identity. Arrange those API
// boundaries; song editing, history, playback and the destination use the real app.
async function arrangeAudience(page: Page, role: (typeof ROLES)[number]): Promise<void> {
	await page.context().route('**/api/auth/me', async (route) => {
		const response = await route.fetch();
		const user = await response.json();
		await route.fulfill({ response, json: { ...user, role } });
	});
}

async function expectWorkerPool(page: Page, width: number): Promise<void> {
	await expect(page).toHaveURL(/\/settings\/users\?tab=acestep$/);
	if (width === 390) {
		await expect(page.getByRole('combobox', { name: ADMIN_TABS_LABEL })).toHaveValue('acestep');
	} else {
		await expect(page.getByRole('button', { name: 'ACE-Step', exact: true })).toHaveClass(/active/);
	}
}

async function expectClearance(page: Page, failure: Locator): Promise<void> {
	const bounds = await failure.boundingBox();
	const player = await page.getByRole('contentinfo').boundingBox();
	if (!bounds || !player) throw new Error('Failure and mini-player must both be visible');
	expect(bounds.x).toBeGreaterThanOrEqual(0);
	expect(bounds.x + bounds.width).toBeLessThanOrEqual(await page.evaluate(() => innerWidth));
	expect(bounds.y + bounds.height).toBeLessThan(player.y);
	expect(await failure.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
		true
	);
}

for (const width of WIDTHS) {
	for (const role of ROLES) {
		for (const source of SOURCES) {
			test(
				`C1 C3 C4: ${role} ${source} at ${width}px`,
				{ tag: ONLY_IN_SHELL.desktop },
				async ({ page, albumId }, testInfo) => {
					await page.setViewportSize({ width, height: 900 });
					await arrangeAudience(page, role);
					const title = `QA unavailable ${runMarker()}`;
					const songId = await seedSongPhoneSong(albumId, title, 1, 1);
					const address = `/album/${albumId}/${title.toLowerCase().replace(/\s+/g, '-')}`;
					const jobId = await seedRunningGenerationJob(songId, {
						progress: 0.36,
						takeIndex: 1,
						takeCount: 1,
						phase: 'rendering'
					});
					const response = await page.request.get(`/api/jobs/${jobId}`);
					expect(response.ok()).toBe(true);
					const running: JobItem = await response.json();
					const failed: JobItem = {
						...running,
						status: 'failed',
						error: UNAVAILABLE,
						error_type: 'generation_unavailable'
					};
					let ended = false;
					let releaseFailure: () => void = () => {};
					const failureReady = new Promise<void>((resolve) => {
						releaseFailure = resolve;
					});
					await page.route(`**/api/songs/${songId}/active-generation`, (route) =>
						route.fulfill({ json: ended ? null : running })
					);
					await page.route(`**/api/songs/${songId}/last-failed-generation`, (route) =>
						route.fulfill({ json: { job: ended ? failed : null } })
					);
					await page.route(`**/api/jobs/${jobId}/stream`, async (route) => {
						await failureReady;
						await route.fulfill({
							contentType: 'text/event-stream',
							body: `data: ${JSON.stringify(failed)}\n\n`
						});
					});
					try {
						await page.goto(address);
						await expect(page.getByRole('heading', { name: title })).toBeVisible();
						if (width === 390) await page.getByRole('tab', { name: /Takes/ }).click();
						await page
							.getByRole('button', { name: new RegExp(`^${TRANSPORT_PLAY_LABEL} v`) })
							.first()
							.click();
						if (width === 390)
							await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true }).click();
						await expect(page.locator('.generate-action:visible [role="status"]')).toBeVisible();
						ended = true;
						releaseFailure();
						if (source === 'reload') await page.reload();
						const failure = page.locator('.generate-action:visible .failure');
						await expect(failure).toContainText(UNAVAILABLE);
						const link = failure.getByRole('link', { name: EDITOR_OPEN_WORKER_POOL_LABEL });
						await expect(link).toHaveCount(role === 'admin' ? 1 : 0);
						await expectClearance(page, failure);
						await testInfo.attach(`C4-${role}-${source}-${width}`, {
							body: await page.screenshot(),
							contentType: 'image/png'
						});
						if (role !== 'admin') return;

						// Keyboard navigation, then browser Back to the song.
						await link.focus();
						await page.keyboard.press('Enter');
						await expectWorkerPool(page, width);
						await page.goBack();
						await expect(failure).toContainText(UNAVAILABLE);

						for (const outcome of [
							DIALOG_CANCEL_LABEL,
							EDITOR_UNSAVED_SAVE_LABEL,
							EDITOR_UNSAVED_DISCARD_LABEL
						]) {
							const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
							const original = await lyrics.inputValue();
							const draft = `${original}\nQA worker pool ${outcome}`;
							await lyrics.fill(draft);
							await link.click();
							const dialog = page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE });
							await expect(dialog).toBeVisible();
							await dialog.getByRole('button', { name: outcome, exact: true }).click();
							if (outcome === DIALOG_CANCEL_LABEL) {
								await expect(dialog).toBeHidden();
								await expect(lyrics).toHaveValue(draft);
								await expect(page).toHaveURL(new RegExp(`${address}$`));
								await lyrics.fill(original);
							} else {
								await expectWorkerPool(page, width);
								await page.goBack();
								await expect(lyrics).toHaveValue(
									outcome === EDITOR_UNSAVED_SAVE_LABEL ? draft : original
								);
							}
						}

						// A modified click opens a new tab without asking to discard this draft.
						const lyrics = page.getByRole('textbox', { name: /^Lyrics/ });
						const draft = `${await lyrics.inputValue()}\nQA keep this draft`;
						await lyrics.fill(draft);
						// Hold the tab's document until Playwright has reported the tab, so the
						// commit cannot outrun its attach and leave it half-registered.
						const context = page.context();
						const popupReady = context.waitForEvent('page');
						const workerPoolDocument = `**${ADMIN_WORKER_POOL_HREF}`;
						await context.route(workerPoolDocument, async (route) => {
							await popupReady;
							await route.continue();
						});
						await link.click({ modifiers: ['ControlOrMeta'] });
						const popup = await popupReady;
						await context.unroute(workerPoolDocument);
						await popup.setViewportSize({ width, height: 900 });
						try {
							await expectWorkerPool(popup, width);
							await expect(page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE })).toBeHidden();
							await expect(lyrics).toHaveValue(draft);
						} finally {
							await popup.close();
						}
					} finally {
						releaseFailure();
						await failGenerationJob(jobId, 'QA unavailable browser proof finished');
					}
				}
			);
		}
	}
}
