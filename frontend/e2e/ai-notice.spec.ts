// The ruled AI notices are always on (#1906, Art. 50 AI Act, E3 of #1714): the
// app's full player says "KI-generiert" and the co-writer says "Du schreibst
// mit einer KI". The mini-player bar carries none. Both shells walk the flow,
// so the notice is judged at 1440 and at 390: in view, never clipped.

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	collectionActionLabel,
	EDITOR_VIEW_COWRITER_LABEL,
	NOW_PLAYING_LABEL,
	openNowPlayingLabel,
	songEditorOpenLabel,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { FlowGuard, shellOf, workspace } from './helpers';
import { readSeededLibrary } from './seed';

const AI_GENERATED_WORDS = 'KI-generiert';
const WRITING_WITH_AI_WORDS = 'Du schreibst mit einer KI';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

async function expectWhollyInView(page: Page, notice: Locator): Promise<void> {
	await expect(notice).toBeInViewport({ ratio: 1 });
	const box = await notice.boundingBox();
	expect(box?.x).toBeGreaterThanOrEqual(0);
	expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);
}

test('1906_P5: the full player says KI-generiert and the mini-player bar does not', async ({
	page
}, testInfo) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', {
			name: collectionActionLabel(TRANSPORT_PLAY_LABEL, 'album'),
			exact: true
		})
		.click();
	const bar = page.getByRole('contentinfo');
	await expect(bar.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })).toBeVisible();
	await expect(bar.getByText(AI_GENERATED_WORDS)).toHaveCount(0);

	await bar
		.getByRole('button', {
			name:
				shellOf(testInfo) === 'mobile'
					? openNowPlayingLabel(library.pickedSongTitle)
					: NOW_PLAYING_LABEL
		})
		.first()
		.click();

	const player = page.getByRole('dialog');
	const notice = player.getByText(AI_GENERATED_WORDS, { exact: true });
	await expect(notice).toBeVisible();
	await expect(notice).toHaveAttribute('lang', 'de');
	await expectWhollyInView(page, notice);
	await page.screenshot({ path: testInfo.outputPath('full-player-notice.png') });
});

test('1906_E3: the co-writer says Du schreibst mit einer KI under its header', async ({
	page
}, testInfo) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(library.pickedSongTitle) })
		.click();
	await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await page
		.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true })
		.or(page.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }))
		.first()
		.click();

	const notice = page.locator('.cowriter').getByText(WRITING_WITH_AI_WORDS, { exact: true });
	await expect(notice).toBeVisible();
	await expect(notice).toHaveAttribute('lang', 'de');
	await expectWhollyInView(page, notice);
	await page.screenshot({ path: testInfo.outputPath('cowriter-notice.png') });
});
