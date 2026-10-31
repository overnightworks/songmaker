// Shared guards, shell facts and name matchers for the browser flows.

import {
	expect,
	type BrowserContext,
	type Locator,
	type Page,
	type Request,
	type Response,
	type TestInfo
} from '@playwright/test';
import {
	ACCOUNT_MENU_LABEL,
	APP_NAME,
	COWRITER_TURN_PATH,
	OFFLINE_STRIP_MESSAGE,
	PLAYLISTS_PAGE_LABEL,
	LIBRARY_PAGE_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_NAV_LABEL,
	RAIL_SEARCH_LABEL,
	RAIL_SETTINGS_LABEL,
	RESOURCE_EVENT_STREAM_PATH,
	SETTINGS_NAV_LABEL,
	SEARCH_OPEN_LABEL
} from '../src/lib/constants';
import {
	HOME_ROUTE_PATH,
	LIBRARY_ROUTE_PATH,
	libraryRouteShape
} from '../src/lib/routes/addresses';
import { BASE_URL } from './seed';
import { PHONE_TABS_NAV_LABEL } from '../src/lib/constants/phone-tabs';
import { routerHistoryEntryOf } from '../src/lib/test-utils/router-history-layout';

/** The two shells the same flow drives — also the Playwright project names. */
export type Shell = 'desktop' | 'mobile';

/**
 * The tag that keeps a test, or every test of a describe, in one shell's
 * project: `playwright.config.ts` leaves it out of the other shell's project,
 * so the test needs no skip by shell.
 */
export const ONLY_IN_SHELL: Record<Shell, string> = {
	desktop: '@desktop-only',
	mobile: '@mobile-only'
};

/** Where the Library wall lives. */
export const LIBRARY_PATH: string = LIBRARY_ROUTE_PATH;

/**
 * The app's first page, for flows that need only a loaded app. Home and the
 * Library are separate addresses, so such flows must not be tied to the
 * Library's address.
 */
export const HOME_PATH: string = HOME_ROUTE_PATH;

/** The address of `path` on any origin, with or without a query: what `toHaveURL` waits for. */
function urlOfPath(path: string): RegExp {
	const escapedPath = path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	return new RegExp(`^[^:]+://[^/]+${escapedPath}(\\?|$)`);
}

/** The address the Library wall stands at. */
export const LIBRARY_URL = urlOfPath(LIBRARY_PATH);

/** The address a signed-in person lands on first. */
export const HOME_URL = urlOfPath(HOME_PATH);

// Above 1099px Now Playing keeps its three columns and docks beside the
// workspace rather than covering it, and above 768px the shell keeps its rail;
// the mobile viewport is a phone in portrait, and the narrow one is the
// smallest screen the album header still has to read on.
export const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
export const MOBILE_VIEWPORT = { width: 390, height: 844 };
export const NARROW_VIEWPORT = { width: 320, height: 844 };

/**
 * What the library flow costs the API per shell, measured on a green full-suite
 * run against `library.spec.ts`'s own first test: 42 requests on desktop and
 * 35 on mobile, budgeted at 42 and 40 respectively (27.09.2026). Home's
 * Listen list fetching fresh on the return to the wall brought desktop to 41
 * (05.09.2026). The flow's round trip to Settings stops the live stream, so
 * the snapshot on the return follows a gap and reads every album again
 * (#1102): one request per 50 albums, one more on each shell. Both projects
 * share one IP rate-limit window, so a flow that suddenly needs more round
 * trips is a regression — find the extra requests instead of raising this
 * number. Every other mention of this budget (the `e2e/README.md` table,
 * `docs/testing.md`) points back here rather than restating it, which is
 * exactly how those three numbers drifted apart before: #312 and #325 each
 * added a request per page load (`ensureAllAlbumsLoaded`,
 * `ensurePlaylistsLoaded`) without this constant, or its callers, ever being
 * re-measured.
 */
export const LIBRARY_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 42,
	mobile: 40
};

/**
 * 1354_65_A1: the desktop rail disclosure/pin flow's API ceiling. Its measured
 * 34 to 35 requests (with the theme read) set the 35 ceiling; this flow no
 * longer runs on mobile.
 * It shares the IP rate-limit window with the separate Library flow.
 */
export const RAIL_FLOW_API_REQUEST_BUDGET = 35;

/**
 * What `song-phone.spec.ts` costs the API: a cold open of the song's own
 * address, the Takes tab, playing a take, a second cold open of the same song
 * for the seeded running job, then its Takes-tab and Write-tab views once that
 * job is failed live over its own open SSE stream. The running-job and
 * failed-job seeding never touch this budget, since both run directly against
 * the database (`seedRunningGenerationJob`, `failGenerationJob` in `seed.ts`),
 * the same way the rail's filler albums and the seeded takes do.
 * Mobile-only, matching the spec's own project restriction.
 *
 * The count grows with the seeded album, not with this flow: playing a take
 * queues the album, and gathering that queue fetches every sibling song's
 * takes (`GET /api/songs/{id}` once each, `collectAlbumEntries` in
 * `stores/player.ts`). Other specs seed their songs into the same album
 * first, so in the full CI run that is 19 extra requests. Measured 02.10.2026
 * on one build with 19 sibling songs: 64 for this cold address open and 64,
 * request for request, for the former album-page-then-song-row open; alone
 * against a fresh album, 45 for both. Repeated green runs measured 64 to 66
 * (CI: 63 and 64), the spread being the cold open's race with the live
 * stream's own bootstrap. The ceiling of 70 holds that spread while a
 * refetch loop still breaks it.
 */
export const SONG_PHONE_FLOW_API_REQUEST_BUDGET = 70;

/**
 * What `take-arrives.spec.ts` costs the API, measured on a green run against a
 * clean stack: opening the album, selecting the song with its seeded running
 * job, the Takes tab, then the job's terminal song refresh once the job ends
 * over its own open SSE stream — measured 23 requests. The job seeding and its
 * completion run directly against the database, the same way
 * `SONG_PHONE_FLOW_API_REQUEST_BUDGET`'s do. Mobile-only.
 */
export const TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET = 30;

/**
 * What `take-arrives.spec.ts`'s offline flow costs the API: the same open,
 * song and Takes tab as `TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET` (23 measured),
 * plus one job-stream attempt per backoff step while the stream is cut off
 * (at most five in the flow's cut-off window) and the stream that reopens when
 * the network returns.
 */
export const TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET = 36;

/**
 * What `offline.spec.ts` costs the API: opening a seeded song on the phone,
 * then losing the network and getting it back, with the live stream that
 * reopens on the return — measured 23. Mobile-only.
 */
export const OFFLINE_FLOW_API_REQUEST_BUDGET = 30;

/**
 * What `offline.spec.ts`'s running-take flow costs the API: the same open,
 * song, Takes tab and seeded running job as `TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET`,
 * with the job stream's backoff attempts while the network is gone and the
 * streams and song refresh that reopen on its return. Measured 26 on the
 * local CI stack (27.09.2026), with the same headroom as the offline flow's.
 */
export const OFFLINE_RUNNING_TAKE_FLOW_API_REQUEST_BUDGET = 34;

const API_PATH_PREFIX = '/api';
// How Chromium fails a request while `loseNetwork` holds the network away.
const NETWORK_LOST_ERROR = 'net::ERR_INTERNET_DISCONNECTED';
const ISSUER_UNRESOLVED_ERROR = 'net::ERR_NAME_NOT_RESOLVED';
// How it reports a load `loseNetwork` found still in flight and ended.
const LOAD_STOPPED_ERROR = 'net::ERR_ABORTED';
const pagesWithoutNetwork = new WeakSet<Page>();
const JOB_STREAM_PATH = /^\/api\/jobs\/[^/]+\/stream$/;

// Streams the client closes on purpose: leaving the library route (Settings,
// sign-out) stops the live resource-event stream
// (`ResourceSyncController.stop()`), a co-writer turn's reader stops on the
// last event it needs, including a named failure, and a job's stream closes
// on the job's terminal status (`completeTrackedJob` in `stores/jobs.ts`) —
// racing the server's own end-of-stream right behind it, which a loaded
// machine loses often enough to fail a flow (#1020). Matched on the path
// alone: a resumed resource stream carries a `last_event_id` query.
function isClosedOnPurpose(url: string): boolean {
	const path = new URL(url).pathname;
	return (
		path === RESOURCE_EVENT_STREAM_PATH || path === COWRITER_TURN_PATH || JOB_STREAM_PATH.test(path)
	);
}

const isResourceEventStream = (url: URL): boolean => url.pathname === RESOURCE_EVENT_STREAM_PATH;

// SvelteKit's shallow routing keeps, beside the entry it writes, the address
// of the page it leaves mounted, and a navigation writes its entry without it.

/** The path history stands on, and the path of the page the router has mounted. */
interface RouterStanding {
	address: string;
	mountedPage: string;
}

async function routerStanding(page: Page): Promise<RouterStanding> {
	const { address, state } = await page.evaluate(() => ({
		address: location.pathname,
		state: history.state as unknown
	}));
	const mountedPage = routerHistoryEntryOf(state)?.pageUrl;
	return {
		address,
		mountedPage: mountedPage === undefined ? address : new URL(mountedPage).pathname
	};
}

export async function standsOnLayerEntry(page: Page): Promise<boolean> {
	const state = await page.evaluate(() => history.state as unknown);
	const entry = routerHistoryEntryOf(state)?.pageState?.entry as App.PageState['entry'];
	return entry?.layer !== undefined;
}

/**
 * Waits until the router has mounted the route of the address the page
 * stands on. Opening a song writes the song's address first and loads its
 * route module after (`writeLibraryHistoryNow` in stores/libraryContext.ts),
 * so the album's route stays mounted under the song's address until that
 * module is in.
 */
async function routeOfAddressMounted(page: Page): Promise<void> {
	await expect
		.poll(
			async () => {
				const { address, mountedPage } = await routerStanding(page);
				return libraryRouteShape(mountedPage) === libraryRouteShape(address);
			},
			{ message: 'the route of the address the page stands on has mounted' }
		)
		.toBe(true);
}

/**
 * Takes the page's network away the way a phone loses it, once the route of the address the page
 * stands on has mounted: a route module the cut catches loading fails the whole app into
 * SvelteKit's error page, a product gap #1160 owns, while these flows lose the network on a page
 * that is open. `setOffline` alone leaves a live event stream the page already holds running (see
 * docs/testing.md), so the page's open loads are stopped the way a dropped network ends them, and
 * every reopen of the library's resource stream is refused until `regainNetwork`. `keepOpenStreams`
 * leaves the streams already open running and refuses only new requests: the moment a stream's last
 * event is already on its way when the network goes.
 */
export async function loseNetwork(
	page: Page,
	context: BrowserContext,
	{ keepOpenStreams = false }: { keepOpenStreams?: boolean } = {}
): Promise<void> {
	await routeOfAddressMounted(page);
	pagesWithoutNetwork.add(page);
	await page.route(isResourceEventStream, (route) => route.abort('internetdisconnected'));
	await context.setOffline(true);
	if (!keepOpenStreams) await page.evaluate(() => window.stop());
}

/**
 * Waits until the service worker has installed and controls the page, so that what it precached
 * (the route code of every address) answers once the network is cut. A cut inside the install
 * window, the first seconds after a first-ever load, is owned by #1160.
 */
export async function waitForServiceWorkerControl(page: Page): Promise<void> {
	await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
	await expect
		.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null))
		.toBe(true);
}

/** Gives the page its network back: the browser reports online and the stream may reopen. */
export async function regainNetwork(page: Page, context: BrowserContext): Promise<void> {
	await page.unroute(isResourceEventStream);
	await context.setOffline(false);
	pagesWithoutNetwork.delete(page);
}

// Whether a load in flight when the network went, or started while it is
// away, failed only because `loseNetwork` took it: which loads are still in
// flight at that moment is a race the flow does not choose.
function failedWithTheNetwork(page: Page, errorText: string): boolean {
	if (errorText === NETWORK_LOST_ERROR) return true;
	return errorText === LOAD_STOPPED_ERROR && pagesWithoutNetwork.has(page);
}

/** Which shell a test drives: the mobile project is the emulated phone. */
export function shellOf(testInfo: TestInfo): Shell {
	return testInfo.project.use.isMobile ? 'mobile' : 'desktop';
}

function escapeForRegExp(literal: string): string {
	return literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Matches an accessible name that starts with one of the given labels. */
export function nameStartingWith(...labels: string[]): RegExp {
	return new RegExp(`^(${labels.map(escapeForRegExp).join('|')})`);
}

/**
 * The open surface — wall, album, song editor or playlist. Scoping to it keeps
 * the flows off the rail, which mirrors the same titles in its context list.
 */
export function workspace(page: Page): Locator {
	return page.getByRole('main');
}

/** 1354_65_A3: the same offline status in the network and shell geometry proofs. */
export function offlineStrip(page: Page): Locator {
	return page.getByRole('status').filter({ hasText: OFFLINE_STRIP_MESSAGE });
}

/** Home's Listen list (`HomeListen.svelte`): the places last played. */
export function listenRegion(page: Page): Locator {
	return workspace(page).getByRole('region', { name: 'Listen', exact: true });
}

/**
 * The phone app bar landmark (`PhoneAppBar.svelte`, mounted by
 * `+layout.svelte` outside `<main>`). On the song route at compact widths it
 * carries the song title, share, and menu; `workspace()` no longer sees them
 * there, so a mobile flow asserting on the song heading reads this landmark
 * instead.
 */
export function appBar(page: Page): Locator {
	return page.getByRole('banner');
}

// The wall's head names its count once every album has loaded. The full list
// lands as one change that sets the wall back to the scroll the app last
// heard of, so a scroll made before it can be undone by it.
export async function expectLibraryWallLoaded(page: Page): Promise<void> {
	await expect(
		workspace(page).getByRole('heading', { name: new RegExp(`^${LIBRARY_PAGE_LABEL} · \\d+$`) })
	).toBeVisible();
}

export function wallBody(page: Page): Locator {
	return workspace(page).locator('.library-wall .wall-body');
}

/** Back to the wall through the word LIBRARY, in the same SPA document. */
export async function openLibraryWall(page: Page, shell: Shell): Promise<void> {
	await openPlace(page, shell, LIBRARY_PAGE_LABEL);
	await expect(page).toHaveURL(LIBRARY_URL);
}

/** An album through its row in the rail's Library list. */
export async function openAlbumFromRail(
	page: Page,
	shell: Shell,
	albumTitle: string
): Promise<void> {
	const rail = await openRailNav(page, shell);
	const libraryGroup = rail.getByRole('button', { name: nameStartingWith(LIBRARY_PAGE_LABEL) });
	if ((await libraryGroup.getAttribute('aria-expanded')) === 'false') await libraryGroup.click();
	await rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('listitem')
		.filter({ hasText: albumTitle })
		.getByRole('button', { name: containing(albumTitle) })
		.click();
}

/** Home through the brand or the phone's guarded return to its tabs. */
export async function openHome(page: Page, shell: Shell): Promise<void> {
	const brand = { name: APP_NAME, exact: true };
	if (shell === 'desktop') {
		await (await openRailNav(page, shell)).getByRole('button', brand).click();
	} else {
		const barBrand = appBar(page).getByRole('button', brand);
		const home = page
			.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL })
			.getByRole('button', { name: 'Home', exact: true });
		if (await barBrand.isVisible()) await barBrand.click();
		else {
			if (!(await home.isVisible()))
				await appBar(page)
					.getByRole('button', { name: /^Back to / })
					.click();
			await home.click();
		}
	}
	await expect(page).toHaveURL(HOME_URL);
}

async function openPlace(page: Page, shell: Shell, label: string): Promise<void> {
	if (shell === 'desktop') {
		await (
			await openRailNav(page, shell)
		)
			.getByRole('link', { name: nameStartingWith(label) })
			.click();
		return;
	}
	const tab = page
		.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL })
		.getByRole('button', { name: label, exact: true });
	if (await tab.isVisible()) await tab.click();
	else {
		await appBar(page).getByRole('button', { name: SEARCH_OPEN_LABEL, exact: true }).click();
		const sheet = page.getByRole('dialog', { name: 'Search', exact: true });
		await sheet.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).fill(label);
		await sheet
			.getByRole('group', { name: 'Pages', exact: true })
			.getByRole('option', { name: nameStartingWith(label) })
			.click();
		await expect(sheet).toBeHidden();
	}
}

/** The Playlists page through the shell's navigation. */
export async function openPlaylistsPage(page: Page, shell: Shell): Promise<void> {
	await openPlace(page, shell, PLAYLISTS_PAGE_LABEL);
	await expect(page).toHaveURL(/\/playlists$/);
}

/** Headers a browser session's own out-of-page API write needs past the origin check. */
export async function sameOriginHeaders(_page: Page): Promise<Record<string, string>> {
	return { origin: BASE_URL };
}

/** The desktop rail; phone callers use tabs or Search. */
export async function openRailNav(page: Page, shell: Shell): Promise<Locator> {
	if (shell === 'mobile') throw new Error('The phone has tabs, not a rail');
	return page.getByRole('navigation', { name: RAIL_NAV_LABEL });
}

const ACCOUNT_MENU_NAME = new RegExp(`^${ACCOUNT_MENU_LABEL} · `);

/** The phone's account circle and, once it is tapped, its menu (#1158). */
export function accountCircle(page: Page): Locator {
	return page.getByRole('button', { name: ACCOUNT_MENU_NAME });
}

export function accountMenu(page: Page): Locator {
	return page.getByRole('dialog', { name: ACCOUNT_MENU_NAME });
}

/** Settings from the phone's account menu: the Settings list on the phone. */
export async function openSettingsFromAccountMenu(page: Page): Promise<void> {
	await accountCircle(page).click();
	await accountMenu(page).getByRole('button', { name: RAIL_SETTINGS_LABEL, exact: true }).click();
}

/** A Settings section from the phone bar's Search sheet (defect:#1583). */
export async function openSettingsSectionFromSearch(page: Page, section: string): Promise<void> {
	const sheet = page.getByRole('dialog', { name: 'Search', exact: true });
	if (!(await sheet.isVisible())) {
		await appBar(page).getByRole('button', { name: SEARCH_OPEN_LABEL, exact: true }).click();
	}
	await sheet.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).fill(section);
	await sheet
		.getByRole('group', { name: 'Pages' })
		.getByRole('option', { name: nameStartingWith(section) })
		.click();
}

/** A Settings section through the desktop rail or the phone's account menu. */
export async function openSettingsSection(
	page: Page,
	shell: Shell,
	section: string
): Promise<void> {
	if (shell === 'mobile') {
		await openSettingsFromAccountMenu(page);
		await page
			.getByRole('navigation', { name: SETTINGS_NAV_LABEL })
			.getByRole('link', { name: nameStartingWith(section) })
			.click();
		return;
	}
	const rail = await openRailNav(page, shell);
	await rail.getByRole('button', { name: RAIL_SETTINGS_LABEL, exact: true }).click();
	await rail.getByRole('link', { name: section, exact: true }).click();
}

/**
 * The open playlist's entries, in screen order — the rows themselves, since a
 * row now carries two controls (▶ plays, the row body plays and judges) and
 * neither of them alone is the entry.
 */
export function playlistEntryRows(page: Page): Locator {
	return workspace(page).getByRole('listitem');
}

export function containing(title: string): RegExp {
	return new RegExp(escapeForRegExp(title));
}

const PLAYING_AUDIO_KEY = 'playingAudio';

export interface PlayingAudioState {
	time: number;
	paused: boolean;
	src: string;
}

/**
 * Makes the media element the app last started readable by
 * `playingAudioState`, without changing how it plays. Call it before the page
 * loads: the player owns a detached element no locator can reach.
 */
export async function observePlayingAudio(page: Page): Promise<void> {
	await page.addInitScript((key) => {
		const play = HTMLMediaElement.prototype.play;
		HTMLMediaElement.prototype.play = function () {
			Reflect.set(window, key, this);
			return play.call(this);
		};
	}, PLAYING_AUDIO_KEY);
}

export function playingAudioState(page: Page): Promise<PlayingAudioState> {
	return page.evaluate((key) => {
		const audio = Reflect.get(window, key) as HTMLMediaElement | undefined;
		return { time: audio?.currentTime ?? 0, paused: audio?.paused ?? true, src: audio?.src ?? '' };
	}, PLAYING_AUDIO_KEY);
}

// How far the tapped take must play on before the tap counts as played.
const PLAYBACK_PROGRESS_SECONDS = 0.3;
// How long a cancelled successor take has to arrive in full after all; a take
// that crawls in over a throttled link is not a failure, a take that never
// comes is.
const SUCCESSOR_REFETCH_TIMEOUT_MS = 30_000;
// The total budget of a test that taps through takes: each tap can wait out a
// full SUCCESSOR_REFETCH_TIMEOUT_MS, so the budget has to outlast several waits.
export const SUCCESSOR_TAKES_TEST_TIMEOUT_MS = 120_000;

/**
 * Passes once the media element the app last started has played on from where it stands when this
 * is called, so call it right after the tap's playing mark shows. A paused element has not played
 * on: a take the app only marked as playing, or the one it just left, does not pass. Position alone
 * proves nothing, because on the continuous deck `currentTime` is the position in the whole stream
 * and a tap on a take the deck already holds is a seek that moves it without a frame played. It
 * does not fit a load with a start position (`pendingRecoverySeek` in `audioPlayer.svelte.ts`):
 * that load seeks, so its first frames are a jump rather than a play-on from where it stood.
 */
async function expectPlaybackAdvances(page: Page): Promise<void> {
	const { time: startedAt } = await playingAudioState(page);
	await expect
		.poll(async () => {
			const { paused, time } = await playingAudioState(page);
			return paused ? 0 : time - startedAt;
		})
		.toBeGreaterThan(PLAYBACK_PROGRESS_SECONDS);
}

export interface RenderedBox {
	x: number;
	y: number;
	width: number;
	height: number;
}

/** Rendered boxes, in the order given — how a flow measures a layout promise. */
export async function boundingBoxes(...locators: Locator[]): Promise<RenderedBox[]> {
	return Promise.all(
		locators.map(async (locator) => {
			const box = await locator.boundingBox();
			if (!box) throw new Error('Expected a rendered box to measure');
			return box;
		})
	);
}

/**
 * A refusal that is the behaviour a flow is there to prove rather than a
 * guard-rail failure. `auth-flows.spec.ts` drives real ones — a locked account,
 * a session the server no longer honours, an admin page a non-admin asks for,
 * a revoke of a session already gone — and Chromium reports every refused
 * fetch as a console error of its own, on top of the response itself. Both are
 * forgiven for exactly these statuses on exactly this path and nowhere else; a
 * 5xx never is. A `path` ending in `/` covers every path beneath it, for a
 * refusal whose address carries an id.
 */
export interface ExpectedRefusal {
	path: string;
	statuses: readonly number[];
}

/**
 * What the app's sign-in start answers: a 303 to the identity provider's
 * authorization endpoint, whose host is the stack's issuer.
 */
export interface SignInStart {
	requested: URL;
	status: number;
	location: URL;
}

const contextsWithStubbedIdentityProvider = new WeakSet<BrowserContext>();

/**
 * The CI stack runs no identity provider, so what the page opens outside the
 * app's origin -- the issuer's logout address -- ends on an empty stub instead
 * of on the network. Playwright routes only the first request of a redirect
 * chain, so the server's redirect to the issuer is not stubbed: the browser
 * fails to resolve the issuer and stays on its error page. A `FlowGuard` on a
 * page of a stubbed context forgives only that navigation: the main frame's
 * navigation to the `Location` of the last sign-in start the page received,
 * once per start, and lists it in `forgivenIssuerNavigations`.
 */
export async function stubIdentityProvider(context: BrowserContext): Promise<void> {
	const appOrigin = new URL(BASE_URL).origin;
	contextsWithStubbedIdentityProvider.add(context);
	await context.route(
		(url) => url.origin !== appOrigin,
		(route) =>
			route.fulfill({ status: 200, contentType: 'text/html', body: '<title>issuer</title>' })
	);
}

/** Whether the page stands outside the app's origin, as it does at the issuer. */
export function leftTheApp(page: Page): boolean {
	return new URL(page.url()).origin !== new URL(BASE_URL).origin;
}

const SIGN_IN_START_PATHNAME = '/login/oidc';

/** Resolves with the answer of the next request to the server's sign-in start. */
export function nextSignInStart(page: Page): Promise<SignInStart> {
	return page
		.waitForResponse((response) => new URL(response.url()).pathname === SIGN_IN_START_PATHNAME)
		.then((response) => ({
			requested: new URL(response.url()),
			status: response.status(),
			location: new URL(response.headers()['location'] ?? '', BASE_URL)
		}));
}

/** The refusals a session or rate limit answers with. */
export const SESSION_REFUSAL_STATUSES: readonly number[] = [401, 403, 429];

export interface FlowGuardOptions {
	refusalsExpectedOn?: readonly ExpectedRefusal[];
	// A flow that calls `loseNetwork` drives that loss on purpose, so neither
	// the failed request nor the console line Chromium adds for it is a guard
	// failure there — and stays one in every other flow.
	losesNetworkOnPurpose?: boolean;
}

const REFUSED_RESOURCE_CONSOLE_MESSAGE =
	/^Failed to load resource: the server responded with a status of (\d{3})\b/;

export function coversPath(refusal: ExpectedRefusal, pathname: string): boolean {
	return refusal.path.endsWith('/') ? pathname.startsWith(refusal.path) : pathname === refusal.path;
}

const BYTE_RANGE_SERVED = /^bytes (\d+)-(\d+)\/(\d+)$/;
const BYTE_RANGE_TO_THE_END = /^bytes=\d+-$/;

// The deck resumes a cancelled take with a range request from where the cancel
// cut it (`continuousDeck.ts`), and the browser reads a playing element with
// open-ended ranges too. Only a GET that asked for the take to its end and was
// answered with the whole take, or with the part from the cut to its last byte,
// completes it: the player's HEAD probe of the take, the one-byte reads seen
// beside it, and an answer that names no known end deliver nothing.
function completesTheTake(response: Response): boolean {
	const request = response.request();
	if (request.method() !== 'GET') return false;
	const asked = request.headers()['range'];
	if (asked !== undefined && !BYTE_RANGE_TO_THE_END.test(asked)) return false;
	if (response.status() === 200) return true;
	if (response.status() !== 206) return false;
	const served = BYTE_RANGE_SERVED.exec(response.headers()['content-range'] ?? '');
	return served !== null && Number(served[2]) + 1 === Number(served[3]);
}

/**
 * Fails the flow on a rate-limited or failed response, on a browser console
 * error, and on an uncaught page exception — and counts what the flow costs
 * the API.
 */
export class FlowGuard {
	private readonly failures: string[] = [];
	private readonly takesBeingAbandoned = new Set<string>();
	private readonly completingResponses = new WeakSet<Request>();
	private readonly refusedAsExpected = new WeakSet<Request>();
	private pendingIssuerNavigation: string | undefined;
	private successorPath: string | undefined;
	private abortedSuccessorUrls: string[] = [];
	private apiRequests = 0;
	readonly forgivenIssuerNavigations: string[] = [];

	constructor(
		private readonly page: Page,
		options: FlowGuardOptions = {}
	) {
		const refusalsExpectedOn = options.refusalsExpectedOn ?? [];
		const losesNetworkOnPurpose = options.losesNetworkOnPurpose ?? false;
		const refusalIsExpected = (url: string, status: number): boolean => {
			const pathname = new URL(url).pathname;
			return (
				status < 500 &&
				refusalsExpectedOn.some(
					(refusal) => refusal.statuses.includes(status) && coversPath(refusal, pathname)
				)
			);
		};
		page.on('request', (request) => {
			if (new URL(request.url()).pathname.startsWith(API_PATH_PREFIX)) this.apiRequests += 1;
		});
		page.on('requestfailed', (request) => {
			const errorText = request.failure()?.errorText ?? 'unknown';
			// Chromium reports a stream the client cancelled in flight and a take the running step
			// abandons as a failed request with exactly this error,
			// indistinguishable from any other intentional client-side abort. Every other reason still fails
			// the flow, including a 429 or 5xx on the same path (handled below).
			// A request the page leaves behind after the server's expected refusal
			// of it is reported the same way, though its answer had arrived.
			const cutOffOnPurpose =
				isClosedOnPurpose(request.url()) ||
				this.forgivesAbandonedTake(request.url()) ||
				this.refusedAsExpected.has(request);
			if (errorText === 'net::ERR_ABORTED' && cutOffOnPurpose) {
				return;
			}
			if (losesNetworkOnPurpose && failedWithTheNetwork(page, errorText)) return;
			if (this.forgivesIssuerNavigation(request, errorText)) return;
			this.failures.push(`request failed: ${request.url()} (${errorText})`);
		});
		page.on('response', (response) => {
			const status = response.status();
			if (new URL(response.url()).pathname === SIGN_IN_START_PATHNAME && status === 303) {
				this.pendingIssuerNavigation = new URL(
					response.headers()['location'] ?? '',
					response.url()
				).href;
			}
			if (completesTheTake(response)) {
				this.completingResponses.add(response.request());
			}
			if (refusalIsExpected(response.url(), status)) {
				this.refusedAsExpected.add(response.request());
				return;
			}
			if (status === 429 || status >= 500) {
				this.failures.push(`${status} from ${response.url()}`);
			}
		});
		page.on('requestfinished', (request) => {
			const completedTake = this.completingResponses.has(request);
			if (completedTake && new URL(request.url()).pathname === this.successorPath) {
				this.abortedSuccessorUrls = [];
			}
		});
		page.on('console', (message) => {
			if (message.type() !== 'error') return;
			if (losesNetworkOnPurpose && message.text().includes(NETWORK_LOST_ERROR)) return;
			const refusedStatus = REFUSED_RESOURCE_CONSOLE_MESSAGE.exec(message.text())?.[1];
			const reportsAnExpectedRefusal =
				refusedStatus !== undefined &&
				refusalIsExpected(message.location().url, Number(refusedStatus));
			if (reportsAnExpectedRefusal) return;
			this.failures.push(`console error: ${message.text()}`);
		});
		page.on('pageerror', (error) => {
			this.failures.push(`uncaught page error: ${error.message}`);
		});
	}

	/**
	 * Runs the step that leaves these takes for `successorPath` — a tap or a Next
	 * that repicks the queue — and forgives, for exactly as long as it runs, the
	 * aborted downloads of those takes: the player cancels the download of every
	 * take it drops or asks for anew, which Chromium reports as an aborted request
	 * whether or not the whole take had arrived, and a look-ahead it had only just
	 * started can fall to the same tap. The abort of the successor itself is
	 * forgiven only once a later request for it has finished and reached the end
	 * of the take, because the deck keeps the audio of a cancelled download and
	 * playback can go on from it without the take ever arriving. The step ends
	 * with the proof that the successor plays, so an abort after it, or of any
	 * other take, still fails the flow.
	 */
	async abandoningTakes(
		abandonedPaths: readonly string[],
		successorPath: string,
		step: () => Promise<void>
	): Promise<void> {
		for (const audioPath of abandonedPaths) this.takesBeingAbandoned.add(audioPath);
		this.successorPath = successorPath;
		try {
			await step();
			await expectPlaybackAdvances(this.page);
			await expect
				.poll(() => this.abortedSuccessorUrls, {
					message: 'the successor take was cancelled and never fetched in full afterwards',
					timeout: SUCCESSOR_REFETCH_TIMEOUT_MS
				})
				.toEqual([]);
		} finally {
			for (const audioPath of abandonedPaths) this.takesBeingAbandoned.delete(audioPath);
			this.successorPath = undefined;
			this.abortedSuccessorUrls = [];
		}
	}

	private forgivesAbandonedTake(url: string): boolean {
		const pathname = new URL(url).pathname;
		if (!this.takesBeingAbandoned.has(pathname)) return false;
		if (pathname === this.successorPath) this.abortedSuccessorUrls.push(url);
		return true;
	}

	get apiRequestCount(): number {
		return this.apiRequests;
	}

	// The one navigation the stubbed identity provider cannot answer: the main
	// frame following the last sign-in start's redirect.
	private forgivesIssuerNavigation(request: Request, errorText: string): boolean {
		const forgiven =
			contextsWithStubbedIdentityProvider.has(this.page.context()) &&
			errorText === ISSUER_UNRESOLVED_ERROR &&
			request.isNavigationRequest() &&
			request.frame() === this.page.mainFrame() &&
			request.url() === this.pendingIssuerNavigation;
		if (forgiven) {
			this.forgivenIssuerNavigations.push(request.url());
			this.pendingIssuerNavigation = undefined;
		}
		return forgiven;
	}

	assertClean(): void {
		expect(this.failures).toEqual([]);
	}

	assertWithinBudget(budget: number): void {
		expect(this.apiRequestCount).toBeLessThanOrEqual(budget);
	}
}
