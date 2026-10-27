// The desktop song page's right column is the tablist Takes · Co-writer (S9
// of #1804): Takes first, the co-writer keeps its draft across a visit to
// Takes, the tab writes no history entry and survives a reload.

import { expect, test as base, type Page } from '@playwright/test';
import {
	COWRITER_COMPOSER_PLACEHOLDER,
	NEW_PLACE_CREATE_LABEL,
	NEW_SONG_ROW_LABEL,
	NEW_SONG_TITLE_LABEL,
	newSongCardLabel,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	RECIPE_PANEL_LABEL,
	LIBRARY_SHARES_COPY_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import { csrfHeaders, FlowGuard, HOME_PATH, ONLY_IN_SHELL, workspace } from './helpers';
import { archiveOwnedAlbum, readSeededLibrary, runMarker } from './seed';

interface OwnedAlbum {
	id: string;
	title: string;
}

const test = base.extend<{ ownedAlbum: OwnedAlbum }>({
	ownedAlbum: async ({ page }, use) => {
		await page.goto(HOME_PATH);
		const title = `E2E Recipe ${runMarker()}`;
		const response = await page.request.post('/api/albums', {
			headers: await csrfHeaders(page),
			data: { title, artist: '' }
		});
		expect(response.ok()).toBe(true);
		const album = (await response.json()) as { id: string };
		try {
			await use({ id: album.id, title });
		} finally {
			await archiveOwnedAlbum(page.request, album.id);
		}
	}
});

const DRAFT = 'mach den Chorus härter';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

test.describe('the song page listen tabs', { tag: ONLY_IN_SHELL.desktop }, () => {
	async function openPickedSong(page: Page) {
		const library = readSeededLibrary();
		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle) })
			.click();
		await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
		return library;
	}

	const takesTab = (page: Page) =>
		workspace(page).getByRole('tab', { name: new RegExp(`^${EDITOR_TAB_TAKES_LABEL}`) });
	const cowriterTab = (page: Page) =>
		workspace(page).getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true });
	const composer = (page: Page) => workspace(page).getByPlaceholder(COWRITER_COMPOSER_PLACEHOLDER);

	test('Takes is the default tab and the header holds no Co-writer button (S9, #1927 acceptance 1)', async ({
		page
	}) => {
		await openPickedSong(page);
		await expect(takesTab(page)).toHaveAttribute('aria-selected', 'true');
		await expect(
			workspace(page).getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true })
		).toHaveCount(0);
	});

	test('a draft typed in the Co-writer survives a visit to Takes (S9, #1927 acceptance 3)', async ({
		page
	}) => {
		await openPickedSong(page);
		await cowriterTab(page).click();
		await composer(page).fill(DRAFT);
		await expect(composer(page)).toBeInViewport();
		await takesTab(page).click();
		await expect(composer(page)).toBeHidden();
		await cowriterTab(page).click();
		await expect(composer(page)).toHaveValue(DRAFT);
	});

	test('switching tabs adds no history entry and one Back leaves the song (S9, #1927 acceptance 6)', async ({
		page
	}) => {
		const library = await openPickedSong(page);
		const entries = await page.evaluate(() => window.history.length);
		await cowriterTab(page).click();
		await takesTab(page).click();
		await cowriterTab(page).click();
		expect(await page.evaluate(() => window.history.length)).toBe(entries);
		await page.goBack();
		await expect(page).toHaveURL(new RegExp(`/album/${library.albumId}$`));
	});

	test('a reload keeps the Co-writer tab (S9, #1927 acceptance 5)', async ({ page }) => {
		await openPickedSong(page);
		await cowriterTab(page).click();
		await expect(cowriterTab(page)).toHaveAttribute('aria-selected', 'true');
		await page.reload();
		await expect(cowriterTab(page)).toHaveAttribute('aria-selected', 'true');
	});

	test('both tabs are at least 44px high and a click near the bottom edge of the Co-writer tab selects it (S9, #1927 acceptance 10)', async ({
		page
	}) => {
		await openPickedSong(page);
		for (const tab of await page
			.getByRole('tablist', { name: 'Editor tabs' })
			.getByRole('tab')
			.all()) {
			const tabBox = await tab.boundingBox();
			expect(tabBox?.height ?? 0).toBeGreaterThanOrEqual(44);
		}
		const box = await cowriterTab(page).boundingBox();
		if (!box) throw new Error('Expected the Co-writer tab to be laid out');
		await page.mouse.click(box.x + box.width / 2, box.y + box.height - 2);
		await expect(cowriterTab(page)).toHaveAttribute('aria-selected', 'true');
	});

	for (const height of [900, 600]) {
		test(`with the Recipe open at 1440x${height} the card is on the left and the composer is on screen (C6, #1935 acceptance 8)`, async ({
			page
		}) => {
			await page.setViewportSize({ width: 1440, height });
			await openPickedSong(page);
			await cowriterTab(page).click();
			await workspace(page).locator('.recipe-line').click();
			const composerBox = await composer(page).boundingBox();
			const panelBox = await workspace(page)
				.getByRole('region', { name: RECIPE_PANEL_LABEL, exact: true })
				.boundingBox();
			if (!composerBox || !panelBox) throw new Error('Expected both laid out');
			await expect(composer(page)).toBeInViewport({ ratio: 1 });
			expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(composerBox.x);
		});
	}

	test('the composer is on screen at 1440x600 with the Recipe closed (C6, #1935 acceptance 8)', async ({
		page
	}) => {
		await page.setViewportSize({ width: 1440, height: 600 });
		await openPickedSong(page);
		await cowriterTab(page).click();
		await expect(composer(page)).toBeInViewport({ ratio: 1 });
	});

	async function createSongInUi(page: Page, album: OwnedAlbum): Promise<string> {
		await page.goto(`/album/${album.id}`);
		const surface = workspace(page);
		await surface.getByRole('button', { name: NEW_SONG_ROW_LABEL, exact: true }).click();
		const card = surface.getByRole('form', { name: newSongCardLabel(album.title) });
		await card.getByLabel(NEW_SONG_TITLE_LABEL).fill('Fresh recipe song');
		const created = page.waitForResponse(
			(response) => response.url().endsWith('/api/songs') && response.request().method() === 'POST'
		);
		await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();
		const song = (await (await created).json()) as { id: string };
		await expect(surface.getByRole('heading', { name: 'Fresh recipe song' })).toBeVisible();
		return song.id;
	}

	test('a song made in the UI shows the closed Recipe line without a dot (C1, #1935 acceptance 2)', async ({
		page,
		ownedAlbum
	}) => {
		await createSongInUi(page, ownedAlbum);
		// The line's name gains ", changed" when its dot shows.
		await expect(
			workspace(page).getByRole('button', { name: RECIPE_PANEL_LABEL, exact: true })
		).toBeVisible();
	});

	test('the composer stays on screen beside a shared-link line at 900, 700 and 600 high (C6, #1935 acceptance 8)', async ({
		page,
		ownedAlbum
	}) => {
		const songId = await createSongInUi(page, ownedAlbum);
		const shared = await page.request.post(`/api/songs/${songId}/share`, {
			headers: await csrfHeaders(page),
			data: {}
		});
		expect(shared.ok()).toBe(true);
		await page.reload();
		await expect(
			workspace(page).getByRole('button', { name: LIBRARY_SHARES_COPY_LABEL })
		).toBeVisible();
		for (const height of [900, 700, 600]) {
			await page.setViewportSize({ width: 1440, height });
			await cowriterTab(page).click();
			await expect(composer(page)).toBeInViewport({ ratio: 1 });
		}
	});
});
