// Spec: REQ-PLAYER-04 -- phone Now Playing shows, on its first screen and without scrolling, the title row, the lyrics in a region that scrolls on its own, the judging card, the progress bar, the whole transport and the Queue row; the header names the surface, not the song.

import { expect, test, type Locator, type Page } from './coverage-test';
import { FlowGuard, MOBILE_VIEWPORT, ONLY_IN_SHELL, sameOriginHeaders } from './helpers';
import { openNowPlayingFromBar, playOpenAlbum } from './play-album';
import { archiveOwnedAlbum, seedTakeStripSong } from './seed';
import { words } from '../src/lib/words/en';

const SHORT_PHONE_VIEWPORT = { width: MOBILE_VIEWPORT.width, height: 664 };
// Long enough to wrap onto a second line beside the cover thumbnail.
const TWO_LINE_TITLE = 'A very long song title that needs two lines on a phone';

let guard: FlowGuard;

test.describe('phone Now Playing first screen', { tag: ONLY_IN_SHELL.mobile }, () => {
	test.beforeEach(({ page }) => {
		guard = new FlowGuard(page);
	});

	test.afterEach(() => {
		guard.assertClean();
	});

	/** Runs the flow in Now Playing of a song with a two-line title, in an album of its own. */
	async function onTwoLineSong(
		page: Page,
		viewport: { width: number; height: number },
		flow: (surface: Locator) => Promise<void>
	) {
		await page.setViewportSize(viewport);
		const album = await page.request.post('/api/albums', {
			headers: await sameOriginHeaders(page),
			data: { title: `E2E Phone layout ${Date.now()}`, artist: '' }
		});
		expect(album.ok()).toBe(true);
		const { id: albumId } = (await album.json()) as { id: string };
		try {
			// Two takes keep the take sheet shut behind the Queue row.
			await seedTakeStripSong(albumId, TWO_LINE_TITLE, 2);
			await page.goto(`/album/${albumId}`);
			await playOpenAlbum(page);
			await openNowPlayingFromBar(page, 'mobile', TWO_LINE_TITLE);
			await flow(page.getByRole('dialog').first());
		} finally {
			await archiveOwnedAlbum(page.request, albumId);
		}
	}

	async function expectInsideViewport(page: Page, control: Locator) {
		const box = await control.boundingBox();
		const viewport = page.viewportSize();
		if (!box || !viewport) throw new Error('Expected a laid out control');
		expect(box.y).toBeGreaterThanOrEqual(0);
		expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
	}

	for (const viewport of [MOBILE_VIEWPORT, SHORT_PHONE_VIEWPORT]) {
		test(`the transport and the Queue row lie inside a ${viewport.width}x${viewport.height} screen`, async ({
			page
		}) => {
			await onTwoLineSong(page, viewport, async (surface) => {
				const controls = [
					surface.getByRole('button', { name: words['transport.shuffleAlbum'] }),
					surface.getByRole('button', { name: words['nowPlaying.previousSong'] }),
					surface.getByRole('button', { name: words['transport.pause'] }),
					surface.getByRole('button', { name: words['nowPlaying.nextSong'] }),
					surface.getByRole('slider').first(),
					surface.getByRole('region', { name: words['nowPlayingJudging.label'] }),
					surface.locator('button[aria-haspopup="dialog"]')
				];

				for (const control of controls) {
					await expect(control).toBeVisible();
					await expectInsideViewport(page, control);
				}
			});
		});
	}

	test('the header names the surface and the title sits in the title row above the lyrics, the card and the transport', async ({
		page
	}) => {
		await onTwoLineSong(page, MOBILE_VIEWPORT, async (surface) => {
			await expect(surface.getByText(words['nowPlaying.kicker'], { exact: true })).toBeVisible();
			await expect(surface.getByText(TWO_LINE_TITLE, { exact: true })).toHaveCount(1);
			const below = [
				surface.getByRole('region', { name: words['nowPlayingJudging.label'] }),
				surface.getByRole('button', { name: words['transport.pause'] })
			];
			const title = await surface.getByText(TWO_LINE_TITLE, { exact: true }).boundingBox();
			const lyrics = await surface
				.getByText(words['nowPlaying.lyricsHeading'], { exact: true })
				.boundingBox();
			if (!title || !lyrics) throw new Error('Expected a laid out title and lyrics');
			const lines = await surface
				.getByText(TWO_LINE_TITLE, { exact: true })
				.evaluate(
					(heading) =>
						heading.getBoundingClientRect().height /
						Number.parseFloat(getComputedStyle(heading).fontSize)
				);
			expect(lines).toBeGreaterThanOrEqual(2);
			expect(title.y + title.height).toBeLessThanOrEqual(lyrics.y);
			for (const control of below) {
				const box = await control.boundingBox();
				expect(box?.y).toBeGreaterThanOrEqual(lyrics.y + lyrics.height);
			}
		});
	});
});
