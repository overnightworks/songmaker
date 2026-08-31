// An album's address, driven the way the operator described it: paste it into
// a tab that knows nothing else and see the album (issue #269) -- a song's own
// address one segment deeper, reached the same way (issue #275) -- and a
// selected take's address one segment deeper still (issue #281).
//
// These are the paths jsdom structurally cannot see. SvelteKit reconciles its
// mounted route tree only in a real browser, so only here does it show whether
// moving between the workspace's four addresses (`/`, `/album/<slug>`,
// `/album/<slug>/<song-slug>` and `/album/<slug>/<song-slug>/take/<n>`) keeps
// the workspace standing or tears it down and builds it again -- since issue
// #276, it does not: the four sit inside one `(library)` route group whose own
// layout mounts LibraryWorkspace once, so a crossing swaps only the thin leaf
// page underneath. That the app writes these addresses when an album, a song
// or a take opens is pinned in the unit suite (stores/navigation.test.ts),
// which costs the stack nothing. The fifth address this file drives, the
// legacy `/?song=<uuid>` a pre-#275 bookmark or link still carries, is not a
// fifth route -- (library)/+page.svelte redirects it onto the song address
// above (issue #284) -- so what only a real browser and router show is that
// the redirect actually lands there and that Back does not step back through
// the query form; the id -> slug lookup itself is pinned in the unit suite
// (resolveLegacySongQueryAddress in stores/libraryContext.test.ts).

import { expect, test, type Page } from '@playwright/test';
import { RESOURCE_SYNC_ERROR } from '../src/lib/constants';
import { FlowGuard, nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * What each test costs the API, measured on a green run: 22 for the cold
 * album open + one-step track click + Back/Forward (down from 24 before issue
 * #276 folded the workspace remount away), 16 for the standalone cold song
 * open and 16 for the standalone cold take open, both unchanged from each
 * other since neither crosses a route to begin with, and 15 for the legacy
 * `/?song=` bookmark redirect (issue #284) -- two full cold page loads (a
 * genuine earlier page, then the bookmark) yet still under the standalone
 * cold song open above, since the second load's own snapshot bootstrap can
 * lose its race against the redirect's own fetch the way a cold take open's
 * already does (see the note further down on that race) — it isn't a fixed
 * cost either way. One shared ceiling, sized to the largest with the same
 * headroom the library flow carries — all four flows share one 60-second IP
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

test('a take address opens cold, in a tab that knows nothing else', async ({ page, isMobile }) => {
	// Same reasoning as the two cold-opens above: shell-independent router
	// behaviour, and the three tests already share a budget window. Which take
	// is selected has no desktop-visible marker to assert on (the compact
	// shell's own Write/Takes tab split is walked by library.spec.ts) --
	// what only a real browser can show is the router-level contract: the
	// address resolves cold, under its song, without tearing the workspace
	// down. That the address seeds selectedGenerationId and the Takes tab is
	// pinned in the unit suite (route page.test.ts).
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent');

	const library = readSeededLibrary();
	// The seed imports exactly one take per song (issue #281's seed.ts note on
	// takeLabel), so the picked song's only take is always generation_number 1.
	const takeAddress = `/album/${library.albumId}/${expectedSongSlug(library.pickedSongTitle)}/take/1`;
	const surface = workspace(page);

	await page.goto(takeAddress);

	await expect(surface.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await expectWorkspaceStanding(page);
});

test('a legacy /?song= bookmark redirects onto the song address, and Back skips the old form', async ({
	page,
	isMobile
}) => {
	// Same reasoning as the three cold-opens above: shell-independent router
	// behaviour, and the four flows already share a budget window. The redirect
	// itself -- resolving the id, dropping an unknown ?gen=, and 404ing an
	// unknown song id -- is pinned cheaply in the unit suite
	// (resolveLegacySongQueryAddress in stores/libraryContext.test.ts); what
	// only a real browser and a real router show is that the address bar
	// actually lands on the canonical form and that Back does not step back
	// through the query one -- issue #284's own done-when.
	test.skip(Boolean(isMobile), 'Route behaviour is shell-independent');

	const library = readSeededLibrary();
	const songsResponse = await page.request.get(`/api/songs?album_id=${library.albumId}`);
	const songs = (await songsResponse.json()).items as { id: string; title: string }[];
	const pickedSong = songs.find((item) => item.title === library.pickedSongTitle);
	if (!pickedSong) {
		throw new Error(`Seeded song "${library.pickedSongTitle}" was not in the album listing`);
	}
	const songAddress = `/album/${library.albumId}/${expectedSongSlug(library.pickedSongTitle)}`;
	const surface = workspace(page);

	// A genuine earlier page first, so Back has somewhere honest to land --
	// the legacy address itself must not be that place.
	await page.goto('/');
	await expectWorkspaceStanding(page);

	await page.goto(`/?song=${pickedSong.id}`);
	await expect(page).toHaveURL(songAddress);
	await expect(surface.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await expectWorkspaceStanding(page);

	await page.goBack();
	await expect(page).toHaveURL('/');
});
