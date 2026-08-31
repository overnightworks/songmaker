// An album's address, driven the way the operator described it: paste it into
// a tab that knows nothing else and see the album (issue #269) -- and a
// song's own address one segment deeper, reached the same way (issue #275).
//
// These are the paths jsdom structurally cannot see. SvelteKit reconciles its
// mounted route tree only in a real browser, so only here does it show whether
// moving between the workspace's three addresses (`/`, `/album/<slug>` and
// `/album/<slug>/<song-slug>`) keeps the workspace standing or tears it down
// and builds it again -- since issue #276, it does not: the three sit inside
// one `(library)` route group whose own layout mounts LibraryWorkspace once,
// so a crossing swaps only the thin leaf page underneath. That the app writes
// these addresses when an album or a song opens is pinned in the unit suite
// (stores/navigation.test.ts), which costs the stack nothing.

import { expect, test, type Page } from '@playwright/test';
import { RESOURCE_SYNC_ERROR } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * What each test costs the API, measured on a green run: 22 for the cold
 * album open + one-step track click + Back/Forward (down from 24 before issue
 * #276 folded the workspace remount away), 16 for the standalone cold song
 * open, unchanged since it never crosses a route to begin with. One shared
 * ceiling, sized to the larger with the same headroom the library flow
 * carries — both flows share one 60-second IP rate-limit window, so a jump
 * here is a regression to find, not a number to raise.
 */
const ALBUM_ADDRESS_FLOW_API_REQUEST_BUDGET = 30;

const LIVE_STREAM_PATH = '/api/resource-events/stream';
const WORKSPACE_LOADING_TEXT = 'Loading...';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Album-address flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
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

test('an album address opens cold, a track click is one step to the song address, and both survive Back and Forward', async ({
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
	const songAddress = new RegExp(`${albumAddress}/[^/]+$`);
	const surface = workspace(page);
	const streamOpens = countLiveStreamOpens(page);

	// The album address, pasted into a tab that knows nothing else.
	await page.goto(albumAddress);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expectWorkspaceStanding(page);

	// A track click lands under the song's own address, its slug, in one
	// navigation step — `/album/<slug>/<song-slug>` rather than the address-less
	// `/?song=…` issue #269 left this on. Both are a route-file crossing (a
	// different +page.svelte owns each of the three addresses), but the
	// `(library)` route group's own layout keeps LibraryWorkspace standing
	// across it (issue #276), so the editor no longer remounts on the way
	// there — see the request-budget note on ALBUM_ADDRESS_FLOW_API_REQUEST_BUDGET.
	await surface.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) }).click();
	await expect(page).toHaveURL(songAddress);
	await expectWorkspaceStanding(page);

	await page.goBack();
	await expect(page).toHaveURL(new RegExp(`${albumAddress}$`));
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expectWorkspaceStanding(page);

	await page.goForward();
	await expect(page).toHaveURL(songAddress);
	await expectWorkspaceStanding(page);

	// One page load, one stream: nothing tore the shell down on the way,
	// across either route boundary. Back/Forward stay client-side (SvelteKit
	// intercepts `popstate`); a genuine second page load, which would abort
	// this stream, is a separate test below rather than a further step here.
	expect(streamOpens()).toBe(1);
});

// Python's slugify() (api_helpers.unique_song_slug) mirrored only for the
// plain-ASCII seeded titles: lowercase, spaces to hyphens. Not a general
// implementation -- the seed's SONG_TITLES never need one.
function expectedSongSlug(title: string): string {
	return title.toLowerCase().replace(/\s+/g, '-');
}

test('a song address opens cold, in a tab that knows nothing else', async ({ page, isMobile }) => {
	// Same reasoning as the album cold-open above: shell-independent router
	// behaviour, and the two shells already share a budget window.
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent');

	const library = readSeededLibrary();
	const songAddress = `/album/${library.albumId}/${expectedSongSlug(library.pickedSongTitle)}`;
	const surface = workspace(page);

	await page.goto(songAddress);

	await expect(surface.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await expectWorkspaceStanding(page);
});
