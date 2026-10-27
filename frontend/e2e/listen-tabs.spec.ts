// The desktop song page's right column is the tablist Takes · Co-writer (S9
// of #1804): Takes first, the co-writer keeps its draft across a visit to
// Takes, the tab writes no history entry and survives a reload.

import { expect, test, type Page } from '@playwright/test';
import {
	COWRITER_COMPOSER_PLACEHOLDER,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_VIEW_COWRITER_LABEL,
	EDITOR_VIEW_RECIPE_LABEL,
	songEditorOpenLabel
} from '../src/lib/constants';
import { FlowGuard, ONLY_IN_SHELL, workspace } from './helpers';
import { readSeededLibrary } from './seed';

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

	test('both tabs are at least 44px high and a click just below one selects it (S9, #1927 acceptance 10)', async ({
		page
	}) => {
		await openPickedSong(page);
		const box = await cowriterTab(page).boundingBox();
		if (!box) throw new Error('Expected the Co-writer tab to be laid out');
		expect(box.height).toBeGreaterThanOrEqual(44);
		await page.mouse.click(box.x + box.width / 2, box.y + box.height - 2);
		await expect(cowriterTab(page)).toHaveAttribute('aria-selected', 'true');
	});

	test('with the Recipe open the full panel is on the left and the composer is on screen (S9, #1927 acceptance 8 and 9)', async ({
		page
	}) => {
		await openPickedSong(page);
		await cowriterTab(page).click();
		await workspace(page)
			.getByRole('button', { name: EDITOR_VIEW_RECIPE_LABEL, exact: true })
			.click();
		const viewport = page.viewportSize();
		const composerBox = await composer(page).boundingBox();
		const panelBox = await workspace(page).locator('.recipe-panel').boundingBox();
		if (!viewport || !composerBox || !panelBox) throw new Error('Expected both laid out');
		expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(viewport.height);
		expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(composerBox.x);
	});
});
