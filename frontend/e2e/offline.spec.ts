// Losing the network on the phone (#1039 O1, O3, O5; slice #1080): within
// about a second one calm strip, "You're offline — retrying", rests on the
// top edge of the mini player, Generate is disabled without a reason of its
// own and stays above the strip, and once the network is back the strip goes
// by itself. Mobile project only: the phone's Generate bar is compact-shell
// UI, and the unit suite pins the desktop placement (PlayerBar.test.ts).
//
// The network is cut for real (`loseNetwork`): `setOffline` alone leaves an
// already open event stream running, so the page's open loads are stopped
// the way a dropped network ends them, and every reopen of the library's live
// stream is refused until the network returns.

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
	EDITOR_GENERATE_MODE_LABELS,
	EDITOR_GPU_OFFLINE_TITLE,
	OFFLINE_STRIP_MESSAGE,
	RESOURCE_SYNC_ERROR
} from '../src/lib/constants';
import {
	boundingBoxes,
	FlowGuard,
	loseNetwork,
	OFFLINE_FLOW_API_REQUEST_BUDGET,
	nameStartingWith,
	regainNetwork,
	workspace
} from './helpers';
import { readSeededLibrary, runMarker, seedSongPhoneSong } from './seed';

const OFFLINE_SONG_TITLE = 'Offline Strip';
// The ruled "within about a second" of losing the network.
const OFFLINE_NOTICE_MS = 1_500;
// The ruling on #1032: back online, the page has caught up within 10 seconds.
const BACK_ONLINE_MS = 10_000;
const GENERATE_LABEL = EDITOR_GENERATE_MODE_LABELS.generate;
// CI's stack runs no ACE-Step worker, so online the Generate bar names that
// reason inside its own box (#1011).
const GENERATE_WITHOUT_GPU = `${GENERATE_LABEL} — ${EDITOR_GPU_OFFLINE_TITLE}`;

function generateButton(page: Page): Locator {
	return page.getByRole('tabpanel').getByRole('button', { name: nameStartingWith(GENERATE_LABEL) });
}

function offlineStrip(page: Page): Locator {
	return page.getByRole('status').filter({ hasText: OFFLINE_STRIP_MESSAGE });
}

test.describe('losing the network on the phone', () => {
	test('shows one calm strip on the mini player, disables Generate above it, and goes by itself once back online', async ({
		page,
		context,
		isMobile
	}) => {
		test.skip(!isMobile, 'Mobile-only compact-shell UI; see the file header.');
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		const library = readSeededLibrary();
		const songTitle = `${OFFLINE_SONG_TITLE} ${runMarker()}`;
		await seedSongPhoneSong(library.songPhoneAlbumId, songTitle, 1, 1);
		const generate = generateButton(page);
		const miniPlayer = page.getByRole('contentinfo');

		await page.goto(`/album/${library.songPhoneAlbumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(songTitle) })
			.click();
		await expect(page.getByRole('heading', { name: songTitle })).toBeVisible();
		await expect(generate).toHaveAccessibleName(GENERATE_WITHOUT_GPU);
		await expect(offlineStrip(page)).toHaveCount(0);

		await loseNetwork(page, context);

		await expect(offlineStrip(page)).toBeVisible({ timeout: OFFLINE_NOTICE_MS });
		await expect(offlineStrip(page).getByRole('button')).toHaveCount(0);
		await expect(generate).toBeDisabled();
		await expect(generate).toHaveAccessibleName(GENERATE_LABEL);
		await expect(generate).not.toContainText('ⓘ');
		await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);
		const [generateBox, stripBox, miniPlayerBox] = await boundingBoxes(
			generate,
			offlineStrip(page),
			miniPlayer
		);
		expect(generateBox.y + generateBox.height).toBeLessThanOrEqual(stripBox.y);
		expect(stripBox.y + stripBox.height).toBeCloseTo(miniPlayerBox.y, 0);

		await regainNetwork(page, context);

		await expect(offlineStrip(page)).toHaveCount(0, { timeout: BACK_ONLINE_MS });
		await expect(generate).toHaveAccessibleName(GENERATE_WITHOUT_GPU);
		await expect(page.getByText(RESOURCE_SYNC_ERROR)).toHaveCount(0);

		console.log(`Offline flow /api requests: ${guard.apiRequestCount}`);
		guard.assertClean();
		guard.assertWithinBudget(OFFLINE_FLOW_API_REQUEST_BUDGET);
	});
});
