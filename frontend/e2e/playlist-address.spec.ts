// A playlist's own address, driven the way the operator described it: paste
// it into a tab that knows nothing else and see the playlist (issue #286),
// the last new address of #265's chain -- same shape as an album's own
// (album-address.spec.ts), but a playlist has no album to nest inside, so its
// address is a sibling of `/`, not a segment under it.
//
// This is a path jsdom structurally cannot see, same reasoning as
// album-address.spec.ts: SvelteKit reconciles its mounted route tree only in
// a real browser, so only here does it show whether opening `/playlist/<slug>`
// mounts LibraryWorkspace inside the `(library)` route group (issue #276)
// rather than a route file of its own. That the app writes this address when
// a playlist opens is pinned in the unit suite (stores/navigation.test.ts),
// which costs the stack nothing.

import { expect, test, type Page } from '@playwright/test';
import { RESOURCE_SYNC_ERROR } from '../src/lib/constants';
import { FlowGuard, workspace } from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';

/**
 * What this flow costs the API, measured on a green run against an isolated
 * stack: 11 for the cold playlist open (resolving the slug against the
 * playlist list, loading the playlist detail, plus the browse listing every
 * cold library-workspace load fetches alongside it) and 9 for the unknown-
 * slug open (no detail fetch — nothing to load once the list lookup misses).
 * Shared budget, headroom sized the same way album-address.spec.ts's is.
 */
const PLAYLIST_ADDRESS_FLOW_API_REQUEST_BUDGET = 15;

const WORKSPACE_LOADING_TEXT = 'Loading...';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Playlist-address flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(PLAYLIST_ADDRESS_FLOW_API_REQUEST_BUDGET);
});

/** The workspace is up: no bootstrap gate left standing, no bootstrap failure. */
async function expectWorkspaceStanding(page: Page): Promise<void> {
	await expect(page.getByText(WORKSPACE_LOADING_TEXT, { exact: true })).toHaveCount(0);
	await expect(page.getByText(RESOURCE_SYNC_ERROR, { exact: true })).toHaveCount(0);
}

test('a playlist address opens cold, in a tab that knows nothing else', async ({
	page,
	request,
	isMobile
}) => {
	// Same reasoning as the cold-opens in album-address.spec.ts: shell-
	// independent router behaviour, so desktop alone proves it.
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent'); // NOSONAR S1607: desktop alone proves shell-independent routing.

	const playlist = await seedPlaylist(request, readSeededLibrary());
	const playlistAddress = `/playlist/${playlist.slug}`;
	const surface = workspace(page);

	await page.goto(playlistAddress);

	await expect(surface.getByRole('heading', { name: playlist.title })).toBeVisible();
	await expect(surface.locator(':scope > .detail-panel > .collection-header')).toBeVisible();
	await expect(
		surface.getByRole('navigation', { name: 'Breadcrumb' }).locator('.crumb')
	).toHaveText(['Playlists', playlist.title]);
	await expect(surface.locator('.library-row-scrim')).toHaveCount(0);
	await expectWorkspaceStanding(page);
});

test('an unknown playlist slug states the address names nothing, without a redirect', async ({
	page,
	isMobile
}) => {
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent'); // NOSONAR S1607: desktop alone proves shell-independent routing.

	await page.goto('/playlist/no-such-playlist-here');

	await expect(page.getByRole('alert')).toContainText('No such playlist');
	await expect(page).toHaveURL(/\/playlist\/no-such-playlist-here$/);
});
