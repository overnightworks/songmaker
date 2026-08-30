// An album's address, driven the way the operator described it: paste it into
// a tab that knows nothing else and see the album (issue #269).
//
// These are the paths jsdom structurally cannot see. SvelteKit reconciles its
// mounted route tree only in a real browser, so only here does it show whether
// moving between the workspace's two addresses (`/` and `/album/<slug>`) keeps
// the workspace standing or tears it down and builds it again. That the app
// writes this address when an album opens is pinned in the unit suite
// (stores/navigation.test.ts), which costs the stack nothing.

import { expect, test, type Page } from '@playwright/test';
import { RESOURCE_SYNC_ERROR } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * What this flow costs the API: 24 measured on a green run, budgeted with the
 * headroom the library flow carries. Both flows share one 60-second IP
 * rate-limit window, so a jump here is a regression to find, not a number to
 * raise.
 */
const ALBUM_ADDRESS_FLOW_API_REQUEST_BUDGET = 30;

const LIVE_STREAM_PATH = '/api/resource-events/stream';
const WORKSPACE_LOADING_TEXT = 'Loading...';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
	guard.assertWithinBudget(ALBUM_ADDRESS_FLOW_API_REQUEST_BUDGET);
});

/**
 * How often the page opened the live library stream. The shell opens it once
 * per page load; a second open means it was torn down and rebuilt, which is
 * exactly what an address that changes the route must not cause.
 */
function countLiveStreamOpens(page: Page): () => number {
	let opens = 0;
	page.on('request', (request) => {
		if (new URL(request.url()).pathname === LIVE_STREAM_PATH) opens += 1;
	});
	return () => opens;
}

/** The workspace is up: no bootstrap gate left standing, no bootstrap failure. */
async function expectWorkspaceStanding(page: Page): Promise<void> {
	await expect(page.getByText(WORKSPACE_LOADING_TEXT, { exact: true })).toHaveCount(0);
	await expect(page.getByText(RESOURCE_SYNC_ERROR, { exact: true })).toHaveCount(0);
}

test('an album address opens cold and survives Back and Forward across the route', async ({
	page,
	isMobile
}) => {
	// One shell only. What this pins is the router's behaviour across an
	// address that changes the route — the same code on both shells — and the
	// two projects share one IP rate-limit window with the library flow, which
	// walks the compact shell's own differences already.
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent');

	const library = readSeededLibrary();
	const albumAddress = `/album/${library.albumId}`;
	const surface = workspace(page);
	const streamOpens = countLiveStreamOpens(page);

	// The address, pasted into a tab that knows nothing else.
	await page.goto(albumAddress);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expectWorkspaceStanding(page);

	// A track opens under the song address, and the workspace stands through
	// it and through the way back and forward over that route boundary.
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(/\/\?song=/);
	await expectWorkspaceStanding(page);

	await page.goBack();
	await expect(page).toHaveURL(new RegExp(`${albumAddress}$`));
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expectWorkspaceStanding(page);

	await page.goForward();
	await expect(page).toHaveURL(/\/\?song=/);
	await expectWorkspaceStanding(page);

	// One page load, one stream: nothing tore the shell down on the way.
	expect(streamOpens()).toBe(1);
});
