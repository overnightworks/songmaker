import { expect, test, type Page } from '@playwright/test';
import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, shellOf, workspace } from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

/**
 * Measured on a green local run (01.10.2026): 42 requests on desktop and 40 on
 * mobile, for opening the album and the song, playing the take, and the
 * reload with its restore (one song fetch). The song and its take are seeded
 * against the database and cost nothing here.
 */
const PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET = 50;

/** Mid-take in the 3 s fixture take (`e2e/fixtures/take.mp3`). */
const MID_TAKE_SECONDS = 1.5;

interface DeckWindow {
	audioDecks: Set<HTMLMediaElement>;
}

// The player's two decks are detached Audio objects no locator reaches, so the
// page collects them as they load. Headless Chromium does not advance them far
// enough to emit `playing`; the real play() call raises it, as the other
// playback flows do.
async function followTheAudioDecks(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const decks = new Set<HTMLMediaElement>();
		(window as unknown as DeckWindow).audioDecks = decks;
		const nativeLoad = HTMLMediaElement.prototype.load;
		HTMLMediaElement.prototype.load = function () {
			decks.add(this);
			nativeLoad.call(this);
		};
		const nativePlay = HTMLMediaElement.prototype.play;
		HTMLMediaElement.prototype.play = function () {
			const result = nativePlay.call(this);
			queueMicrotask(() => this.dispatchEvent(new Event('playing')));
			return result;
		};
	});
}

async function seekThePlayingDeck(page: Page, seconds: number): Promise<void> {
	await page.evaluate((to) => {
		const decks = [...(window as unknown as DeckWindow).audioDecks];
		const playing = decks.find((deck) => !deck.paused);
		if (!playing) throw new Error('No deck is playing');
		playing.currentTime = to;
	}, seconds);
}

// After a reload only the restored take has a source: nothing preloads after
// it until its queue continues.
async function loadedDeckPositions(page: Page): Promise<number[]> {
	return page.evaluate(() =>
		[...(window as unknown as DeckWindow).audioDecks]
			.filter((deck) => deck.currentSrc !== '')
			.map((deck) => deck.currentTime)
	);
}

test('reload mid-take shows the same take at the same position, paused', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	const songTitle = `Playback Restore ${shell} ${runMarker()}`;
	await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
	await followTheAudioDecks(page);
	const transport = page.getByRole('contentinfo');
	const transportPlay = transport.getByRole('button', { name: TRANSPORT_PLAY_LABEL, exact: true });
	const transportPause = transport.getByRole('button', {
		name: TRANSPORT_PAUSE_LABEL,
		exact: true
	});

	await page.goto(`/album/${library.songPhoneAlbumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(songTitle) })
		.click();
	if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
	const take = workspace(page).locator('.take-row');
	await expect(take).toHaveCount(1);
	await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();
	await expect(transportPause).toBeVisible();
	await seekThePlayingDeck(page, MID_TAKE_SECONDS);
	await transportPause.click();
	await expect(transportPlay).toBeVisible();

	await page.reload();

	await expect(transport).toContainText(songTitle);
	await expect(transportPlay).toBeVisible();
	await expect.poll(() => loadedDeckPositions(page)).toEqual([expect.closeTo(MID_TAKE_SECONDS, 0)]);
	if (shell === 'desktop') {
		await expect
			.poll(async () =>
				Number(await transport.getByRole('slider', { name: 'Seek playback' }).inputValue())
			)
			.toBeCloseTo(MID_TAKE_SECONDS, 0);
	}

	await transportPlay.click();
	await expect(transportPause).toBeVisible();

	console.log(`Playback restore flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYBACK_RESTORE_FLOW_API_REQUEST_BUDGET);
});
