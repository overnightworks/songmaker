// The auth chain B1-B5 driven the way a musician meets it (issue #872, bundle
// B6 of the library extraction #825): signing in, being locked out after
// repeated wrong passwords, signing out, coming back to a reloaded tab, being
// refused the admin page, and returning to a session that has outlived its
// absolute maximum age -- and, since #1215, a logged-out deep link that signs
// in onto the address it asked for. Since #1230 the phone also loses its
// session behind an open song page and is sent to the door from there, and
// since #1340 a Search result after the loss returns there to the tapped album.
// Since #1322 an admin with two sessions finds its own marked as this device,
// and a create refusal in the form clears on typing while an error on the page
// stays. Since #1397 a revoke that another tab beat drops the dead row and says
// the session had already ended, until a revoke works or the admin changes
// tab, and a create that works clears the Users tab's error. Since #1340 a
// sign-out while a take plays leaves by a fresh sign-in page, and one the
// server never received leaves the person signed in.
//
// This is here rather than in the unit suite because each of those
// sentences is about the browser and the server together: which page the
// address bar ends on, whether the cookie is still carried, what the person
// reads when a refusal arrives -- and, the one B5 made structural, whether the
// session behind a cookie still exists on the server at all. A jsdom test can
// only ask the store what it believes; it cannot re-offer a cookie the browser
// has thrown away and watch the server refuse it.
//
// No route interception except in the media-refusal flows (#925 M3): a session
// the server still holds is never refused a take, so those flows refuse the
// take's audio by route. Every other refusal is the CI stack's own answer.
// The admin flows' 404s and 409 are their point, so their guard forgives
// exactly those statuses on exactly the revoke, account-update and create
// paths.
// The two numbers the lockout flow depends on are set in
// `docker/docker-compose.ci.yml`, with the measurement written beside them --
// the short-window budget counts failed logins per *IP* and the whole run comes
// from one address, so production's five would refuse every later login in the
// suite, while the lockout counts per *account* and therefore stays on this
// spec's own throwaway user.
//
// Both shells drive all seven flows: the compact one at 375px, which is where
// bottom tabs replace the rail and Log out is reached through the account circle in
// the app bar (issue #1158). The session lost behind Search is the phone's
// own flow.

import { openSearchSheet, phoneSearchResult } from './phone-search';
import {
	expect,
	request,
	test,
	type BrowserContext,
	type Cookie,
	type Locator,
	type Page,
	type Response,
	type Request,
	type TestInfo
} from '@playwright/test';

import { AUTH_SESSION_EXPIRED_MESSAGE } from '../src/lib/constants/auth';
import {
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	SESSION_LOST_REDIRECT_PARAM,
	RAIL_SEARCH_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import {
	FlowGuard,
	SESSION_REFUSAL_STATUSES,
	type ExpectedRefusal,
	MOBILE_VIEWPORT,
	openLibraryWall,
	openRailNav,
	containing,
	coversPath,
	loseNetwork,
	nameStartingWith,
	ONLY_IN_SHELL,
	regainNetwork,
	shellOf,
	workspace,
	type Shell,
	HOME_PATH,
	HOME_URL,
	LIBRARY_PATH,
	LIBRARY_URL
} from './helpers';
import {
	BASE_URL,
	ageSessionPastAbsoluteLimit,
	seedAccount,
	seedOwnSongAddress,
	seedOwnTakeAddress
} from './seed';

/**
 * What each test costs the API, measured on a green run of both shells against
 * the CI recipe (desktop / 375px): 13/13 for the sign-in, 19/19 for the reload,
 * 14/14 for the sign-out and the refused return, 18/15 for the refused admin
 * page, 13/12 for the expired session, 23/26 for the deep-link sign-in, 28 at
 * 375px for the session loss behind a fresh Search query
 * (`1354_37a_A5_song`), and 24 at 390px for the album selected in Search
 * after expiry (`1354_37a_A5_album`; measured on #1605's branch CI).
 * The admin flows were measured at 1440 /
 * 390 instead: 27 to 28/25 to 26 for the own session, its two stale revokes,
 * the revoke that works and the create refusal (#1397), 11/9 for the Users
 * tab error a create refusal leaves standing and a create that works clears
 * (#1397), and 8 at 390px for the row-action hitboxes (the admin page plus
 * opening a tab), which runs on the phone only.
 * The lockout was measured at 1440 / 375 once it polled for the lock to lift
 * (#1403): 16 to 17/15, up to eight of them its tries with the right password -- the
 * one the lock refuses, then one every ten seconds until it lifts.
 * The #1340 sign-outs were measured at 1440 / 390: 29 and
 * 32 to 35 for the sign-out while a take plays -- the song page, its take, and
 * on the phone the former drawer walk to the album (pre-tabs baseline; re-measure in CI) -- and 23/23 for the
 * sign-out the lost network keeps from the server. The #925 M3 media-refusal
 * flow was measured over ten runs at 1440 / 390: 46 to 47/45 to 48 for
 * the take's audio refused. One ceiling for the
 * file, the same way `admin-models.spec.ts` carries one for its four; only the
 * sign-out while a take plays carries its own, since it opens a song and plays
 * before the sign-out it is about (14.10.2026), and the media-refusal flow
 * another, since it signs in onto a song page and then loads the song
 * afresh behind a valid session, a whole cold page open on top of the
 * first. The budget is a ceiling, not a knob: a flow that suddenly needs several more round trips is a regression,
 * so find the extra requests instead of raising this number -- see
 * `LIBRARY_FLOW_API_REQUEST_BUDGET` in `helpers.ts` for the full reasoning.
 */
const AUTH_FLOW_API_REQUEST_BUDGET = 30;
// The sign-out while a take plays: 29 at 1440, 32 to 35 at 390.
const PLAYS_A_TAKE_TAG = '@plays-a-take';
const TAKE_SIGN_OUT_FLOW_API_REQUEST_BUDGET = 40;
// The flows whose take the route refuses: a session the server still holds is
// never refused a take, so the 401s on its audio are the sentence under proof.
const TAKE_AUDIO_REFUSED_TAG = '@take-audio-refused';
const TAKE_AUDIO_PATH = '/audio/';
const TAKE_AUDIO_REFUSED_FLOW_API_REQUEST_BUDGET = 55;

const AUTH_LOGIN_PATH = '/api/auth/login';
const AUTH_ME_PATH = '/api/auth/me';
const ADMIN_API_PREFIX = '/api/admin/';
const REFUSED_PATHS = [AUTH_LOGIN_PATH, AUTH_ME_PATH];
// Only the standing-song scenario expects a refused search query.
const SEARCH_REFUSED_TAG = '@session-search-refused';
const LIBRARY_SEARCH_PATH = '/api/library/search';
// Album selection may race the overlay's Back with any of these opening reads (#1340).
const ALBUM_OPENING_REFUSED_TAG = '@album-opening-refused';
const ALBUM_OPENING_PATHS = [
	'/api/songs',
	'/api/albums/',
	'/api/settings/models',
	'/api/resource-events/stream'
];
// The sign-out whose request never reaches the server: only that flow forgives
// the requests the lost network fails.
const LOSES_NETWORK_TAG = '@loses-network';
// The non-admin visit of the admin page: the server's 403 on its reads is the
// sentence under proof.
const ADMIN_REFUSED_TAG = '@admin-refused';
const TAKE_AUDIO_REFUSAL: ExpectedRefusal = { path: TAKE_AUDIO_PATH, statuses: [401] };
const ADMIN_PAGE_PATH = '/settings/users';
const VOICES_PAGE_PATH = '/settings/voices';
const VOICES_HEADING = 'My Voices';
const SESSION_COOKIE = 'session_id';
const APP_HISTORY_STEPS_KEY = 'e2e:app-history-steps';
// Set on the signed-in document only: a page that still carries it was not
// loaded afresh.
const SIGNED_IN_DOCUMENT_MARK = 'e2eSignedInDocument';

// The song the deep-link flows ask for: the account's own, so the sign-in
// that follows may open it.
const DEEP_LINK_SONG_TITLE = 'Glass River';

// The narrowest phone the shell is drawn for -- the mobile project's own
// viewport is 390, and #872 rules this chain at 375.
const PHONE_VIEWPORT = { width: 375, height: 844 };

const LOGIN_PAGE_URL = /\/login(\?|$)/;

// What the account this spec creates signs in with, and what it never signs in
// with. Both satisfy the login form's own `minlength`, so the browser submits
// them rather than refusing them itself.
const ACCOUNT_PASSWORD = 'E2eFlows!2026';
const WRONG_PASSWORD = 'E2eFlows!2025';

// The words the person reads, from `stores/auth.ts` and the pages themselves.
const INVALID_CREDENTIALS_MESSAGE = 'Invalid username or password.';
const REFUSED_LOGIN_MESSAGE = 'Too many attempts. Try again later.';
// The store collapses both of the server's 429 details into this one line, so
// the screen cannot say which refusal arrived. The lockout flow is about the
// per-account one (`ACCOUNT_LOCKED_DETAIL`, `webauth.login`) and reads that
// off the response body -- otherwise a stack whose per-IP budget trips first
// (`TOO_MANY_LOGIN_ATTEMPTS_DETAIL`; production's 5 is below the lockout's 15)
// would answer 429 too and the flow would pass having proved the other
// sentence.
const ACCOUNT_LOCKED_DETAIL =
	'Account temporarily locked due to repeated failed attempts. Try again later.';
const ADMIN_REFUSED_MESSAGE = 'Admin access required.';
const LOGOUT_LABEL = 'Logout';
const SUBMIT_LABEL = 'Enter';
const USERNAME_LABEL = 'Username';
const PASSWORD_LABEL = 'Password';

// The lockout has to arrive on its own, from wrong passwords alone, so the
// spec never encodes the stack's threshold -- it only refuses to type forever.
const MAX_WRONG_PASSWORDS = 10;
// A `Retry-After` a run can honour: the CI stack states 60 seconds, and being
// admitted again within what the server said is what proves the lock is
// temporary rather than terminal. A production-like stack states an hour, and
// the flow says so and stops instead of hanging the suite.
const MAX_HONOURED_RETRY_AFTER_SECONDS = 90;
const LOCKOUT_TEST_TIMEOUT_MS = 180_000;
// The lock lifts by itself within the `Retry-After` it states, so the flow
// tries the right password again this often until it gets in, instead of
// sleeping the statement out. A refused try records no failure, so trying
// cannot stretch the lock, and each one costs a single request.
const LOCK_LIFT_POLL_INTERVAL_MS = 10_000;

interface Account {
	id: string;
	username: string;
	password: string;
}

let account: Account;
let guard: FlowGuard;

// Every flow starts at the door: the run's admin storage state would answer
// half of these questions before they are asked. It has to be an explicitly
// empty state -- `undefined` reads as "not overridden" here and leaves the
// project's own signed-in state in place.
test.use({ storageState: { cookies: [], origins: [] } });

test.beforeAll(async () => {
	// One account per project, so the shell that locks it out cannot lock the
	// other shell's flows out with it.
	const username = `e2e-b6-${test.info().project.name}-${Date.now().toString(36)}`;
	const seeded = await seedAccount(username, 'user', ACCOUNT_PASSWORD);
	account = { id: seeded.id, username, password: ACCOUNT_PASSWORD };
});

test.beforeEach(async ({ page, isMobile }, testInfo) => {
	if (isMobile) await page.setViewportSize(PHONE_VIEWPORT);
	guard = new FlowGuard(page, {
		refusalsExpectedOn: refusalsExpectedIn(testInfo),
		losesNetworkOnPurpose: testInfo.tags.includes(LOSES_NETWORK_TAG)
	});
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Auth flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(apiRequestBudgetOf(testInfo));
});

/** Types one set of credentials and waits for the server's own answer. */
async function submitLogin(page: Page, username: string, password: string): Promise<Response> {
	await page.getByLabel(USERNAME_LABEL).fill(username);
	await page.getByLabel(PASSWORD_LABEL).fill(password);
	const [response] = await Promise.all([
		page.waitForResponse((candidate) => new URL(candidate.url()).pathname === AUTH_LOGIN_PATH),
		page.getByRole('button', { name: SUBMIT_LABEL }).click()
	]);
	return response;
}

/**
 * The sign-in page a page without a session sends to: asked to bring the
 * person back to that page, or plainly the door from Home, where every
 * sign-in lands.
 */
function isSignInFor(url: URL, address: string): boolean {
	const returnTo = url.searchParams.get(SESSION_LOST_REDIRECT_PARAM) ?? HOME_PATH;
	return url.pathname === '/login' && returnTo === address;
}

/** Signs in from the login page and waits until the workspace is standing. */
async function signIn(page: Page): Promise<void> {
	await page.goto('/login');
	const response = await submitLogin(page, account.username, account.password);
	expect(response.status()).toBe(200);
	await expect(page).toHaveURL(HOME_URL);
	await expect(workspace(page)).toBeVisible();
}

/** The account's own name, where the shell shows who is signed in. */
async function expectSignedInAs(page: Page, testInfo: TestInfo): Promise<void> {
	if (shellOf(testInfo) === 'mobile') {
		await expect(
			page.getByRole('button', { name: `${ACCOUNT_MENU_LABEL} · ${account.username}` })
		).toBeVisible();
		return;
	}
	const rail = await openRailNav(page, 'desktop');
	await expect(rail.getByRole('link', { name: account.username })).toBeVisible();
}

async function signOut(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') {
		const accountMenu = `${ACCOUNT_MENU_LABEL} · ${account.username}`;
		await page.getByRole('button', { name: accountMenu }).click();
		await page
			.getByRole('dialog', { name: accountMenu })
			.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL })
			.click();
		return;
	}
	const rail = await openRailNav(page, shell);
	await rail.getByRole('button', { name: LOGOUT_LABEL }).click();
}

/** Shows the open song's takes: the phone keeps them behind a tab. */
async function showTheTakes(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') await page.getByRole('tab', { name: /Takes/ }).click();
}

/** The play button of the open song's one take. */
function takeRowPlay(page: Page): Locator {
	return workspace(page)
		.locator('.take-row')
		.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) });
}

function footerPause(page: Page): Locator {
	return page
		.getByRole('contentinfo')
		.getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true });
}

/** Plays the open song's one take and waits until it sounds. */
async function playTheTake(page: Page, shell: Shell): Promise<void> {
	await showTheTakes(page, shell);
	await takeRowPlay(page).click();
	await expect(footerPause(page)).toHaveAttribute('aria-busy', 'false');
}

function transportControls(page: Page): Locator {
	return page.getByRole('button', {
		name: nameStartingWith(TRANSPORT_PLAY_LABEL, TRANSPORT_PAUSE_LABEL)
	});
}

async function markSignedInDocument(page: Page): Promise<void> {
	await page.evaluate((mark) => Object.assign(window, { [mark]: true }), SIGNED_IN_DOCUMENT_MARK);
}

async function isSignedInDocument(page: Page): Promise<boolean> {
	return page.evaluate((mark) => mark in window, SIGNED_IN_DOCUMENT_MARK);
}

async function sessionCookie(context: BrowserContext): Promise<Cookie | undefined> {
	const cookies = await context.cookies();
	return cookies.find((cookie) => cookie.name === SESSION_COOKIE);
}

/** The signed cookie is `<session id>.<hmac>` (`webauth.cookies`). */
function sessionIdOf(cookie: Cookie): string {
	return cookie.value.slice(0, cookie.value.lastIndexOf('.'));
}

/**
 * Records every Back or jump the app issues itself -- the browser's own Back
 * goes around it -- in session storage, which survives a document load.
 */
function recordAppHistorySteps(storageKey: string): void {
	const record = (step: string): void => {
		const steps = JSON.parse(sessionStorage.getItem(storageKey) ?? '[]') as string[];
		sessionStorage.setItem(storageKey, JSON.stringify([...steps, `${step}@${location.pathname}`]));
	};
	const back = history.back.bind(history);
	const go = history.go.bind(history);
	history.back = () => {
		record('back()');
		back();
	};
	history.go = (delta?: number) => {
		record(`go(${delta})`);
		go(delta);
	};
}

function appHistorySteps(page: Page): Promise<string[]> {
	return page.evaluate(
		(storageKey) => JSON.parse(sessionStorage.getItem(storageKey) ?? '[]') as string[],
		APP_HISTORY_STEPS_KEY
	);
}

function forgetAppHistorySteps(page: Page): Promise<void> {
	return page.evaluate(
		(storageKey) => sessionStorage.removeItem(storageKey),
		APP_HISTORY_STEPS_KEY
	);
}

/** What a page was asked for and answered with, in the order it happened. */
interface DocumentWatch {
	timeline: string[];
	freshDocuments: string[];
	movesWithinTheDocument: string[];
}

function refusalSource(response: Response): string {
	const { pathname } = new URL(response.url());
	if (pathname.startsWith(TAKE_AUDIO_PATH)) {
		return `${response.request().method()} take audio ${response.status()}`;
	}
	return pathname.startsWith('/api/') ? `API read ${response.status()}` : pathname;
}

/**
 * Watches the page's main frame: which fresh documents it asks for (a reload,
 * an assign and a replace each send a navigation request; a router push sends
 * none), which addresses it moves to within the document until then, and every
 * refusal it receives, in the order the page sees them.
 */
function watchTheDocument(page: Page): DocumentWatch {
	const watch: DocumentWatch = { timeline: [], freshDocuments: [], movesWithinTheDocument: [] };
	let standingOn = new URL(page.url()).pathname;
	page.on('request', (request) => {
		if (!request.isNavigationRequest() || request.frame() !== page.mainFrame()) return;
		const { pathname } = new URL(request.url());
		watch.freshDocuments.push(pathname);
		watch.timeline.push(`document ${pathname}`);
	});
	page.on('framenavigated', (frame) => {
		if (frame !== page.mainFrame() || watch.freshDocuments.length > 0) return;
		const { pathname } = new URL(frame.url());
		if (pathname === standingOn) return;
		standingOn = pathname;
		watch.movesWithinTheDocument.push(pathname);
	});
	page.on('response', (response) => {
		if (response.status() >= 400) watch.timeline.push(refusalSource(response));
	});
	return watch;
}

/** Every refusal the page saw before it asked for its first fresh document, in order. */
function refusalsBeforeTheLoad(watch: DocumentWatch): string[] {
	const firstDocument = watch.timeline.findIndex((entry) => entry.startsWith('document '));
	return watch.timeline.slice(0, firstDocument === -1 ? undefined : firstDocument);
}

const isTakeAudio = (url: URL): boolean => url.pathname.startsWith(TAKE_AUDIO_PATH);
const isTakeProbe = (response: Response): boolean =>
	response.request().method() === 'HEAD' && isTakeAudio(new URL(response.url()));
/**
 * Answers the take's audio as a lost session is answered, until the page asks
 * for a fresh document, which meets the real, still valid session.
 */
async function refuseTheTakeAudio(page: Page, watch: DocumentWatch): Promise<void> {
	await page.route(isTakeAudio, async (route) => {
		if (watch.freshDocuments.length > 0) return route.fallback();
		return route.fulfill({ status: 401 });
	});
}

/** The refusal the lockout flow is about, named by the server itself. */
async function expectAccountLocked(refusal: Response): Promise<void> {
	expect(refusal.status()).toBe(429);
	expect((await refusal.json()).detail).toBe(ACCOUNT_LOCKED_DETAIL);
}

/** The account's own song, seeded through a session of its own outside the browser. */
async function seedOwnSong(seedAddress = seedOwnSongAddress): Promise<string> {
	const api = await request.newContext({ baseURL: BASE_URL });
	try {
		return await seedAddress(api, account, DEEP_LINK_SONG_TITLE);
	} finally {
		await api.dispose();
	}
}

/** The album page a song address sits under: `/album/<album>/<song>`. */
function albumAddressOf(songAddress: string): string {
	return songAddress.slice(0, songAddress.lastIndexOf('/'));
}

/**
 * The run marker the seeded album's title and address share
 * (`seedOwnSongAddress`), which identifies its Search result.
 */
function albumMarkerOf(albumAddress: string): string {
	return albumAddress.slice(albumAddress.lastIndexOf('-') + 1);
}

/** Settle playlist reads started by mounting Search before aging the session. */
async function settleSearchOpeningReads(
	page: Page,
	open: () => Promise<Locator>
): Promise<Locator> {
	const reads: Promise<Response | null>[] = [];
	const record = (request: Request) => {
		if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/playlists') {
			reads.push(request.response());
		}
	};
	page.on('request', record);
	try {
		const result = await open();
		for (const read of reads) {
			const response = await read;
			expect(response?.ok()).toBe(true);
			await response?.finished();
		}
		return result;
	} finally {
		page.off('request', record);
	}
}

function isSearchResponse(response: Response, query: string): boolean {
	const url = new URL(response.url());
	return (
		response.request().method() === 'GET' &&
		url.pathname === LIBRARY_SEARCH_PATH &&
		url.searchParams.get('q') === query
	);
}

/**
 * Opens the account's own song the way a logged-out tab does: through the
 * door, which says nothing about a session the tab never had.
 */
async function signInOnto(page: Page, songAddress: string): Promise<void> {
	await page.goto(songAddress);
	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	await expect(page.getByLabel(USERNAME_LABEL)).toBeVisible();
	await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeHidden();
	const response = await submitLogin(page, account.username, account.password);
	expect(response.status()).toBe(200);
	await expect(page).toHaveURL(new RegExp(`${songAddress}$`));
	await expect(page.getByRole('heading', { name: DEEP_LINK_SONG_TITLE })).toBeVisible();
}

/**
 * Every refusal this file drives is one of its sentences: the login it locks
 * out, the `/api/auth/me` a dead session answers, the admin calls a non-admin
 * makes, and for the tagged flows the search query a lost session refuses,
 * the admin's stale revoke and taken username, and the take's audio the media
 * flows refuse. A refusal anywhere else, and any 5xx at all, still fails the
 * flow.
 */
function refusalsExpectedIn(testInfo: TestInfo): ExpectedRefusal[] {
	const refusedPaths = [
		...REFUSED_PATHS,
		...(testInfo.tags.includes(SEARCH_REFUSED_TAG) ? [LIBRARY_SEARCH_PATH] : []),
		...(testInfo.tags.includes(ALBUM_OPENING_REFUSED_TAG) ? ALBUM_OPENING_PATHS : [])
	];
	const sessionRefusals = refusedPaths.map((path) => ({
		path,
		statuses: SESSION_REFUSAL_STATUSES
	}));
	return [
		...sessionRefusals,
		...(testInfo.tags.includes(ADMIN_REFUSED_TAG)
			? [{ path: ADMIN_API_PREFIX, statuses: [403] }]
			: []),
		...(testInfo.tags.includes(TAKE_AUDIO_REFUSED_TAG) ? [TAKE_AUDIO_REFUSAL] : [])
	];
}

function apiRequestBudgetOf(testInfo: TestInfo): number {
	if (testInfo.tags.includes(TAKE_AUDIO_REFUSED_TAG)) {
		return TAKE_AUDIO_REFUSED_FLOW_API_REQUEST_BUDGET;
	}
	return testInfo.tags.includes(PLAYS_A_TAKE_TAG)
		? TAKE_SIGN_OUT_FLOW_API_REQUEST_BUDGET
		: AUTH_FLOW_API_REQUEST_BUDGET;
}

async function attachShot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
	const path = testInfo.outputPath(`${name}.png`);
	await page.screenshot({ path, fullPage: true });
	await testInfo.attach(name, { path, contentType: 'image/png' });
}

test('a musician signs in and the shell shows whose session it is', async ({ page }, testInfo) => {
	// A tab that knows nothing is sent to the door rather than shown a wall,
	// and is not told about a session it never had.
	await page.goto(HOME_PATH);
	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	await expect(page.getByLabel(USERNAME_LABEL)).toBeVisible();
	await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeHidden();

	const response = await submitLogin(page, account.username, account.password);
	expect(response.status()).toBe(200);

	await expect(page).toHaveURL(HOME_URL);
	await expectSignedInAs(page, testInfo);
	expect(await sessionCookie(page.context())).toBeDefined();
	await attachShot(page, testInfo, 'auth-signed-in');
});

test('the session survives a reload of the tab', async ({ page }, testInfo) => {
	await signIn(page);
	const before = await sessionCookie(page.context());

	await page.reload();

	await expect(page).toHaveURL(HOME_URL);
	await expect(workspace(page)).toBeVisible();
	await expectSignedInAs(page, testInfo);
	// The same session, not a new one: a reload re-proves the cookie it already
	// had rather than issuing anything.
	expect((await sessionCookie(page.context()))?.value).toBe(before?.value);
});

test('signing out ends the session on the server, not only in the browser', async ({
	page
}, testInfo) => {
	await signIn(page);
	const signedIn = await sessionCookie(page.context());
	expect(signedIn).toBeDefined();

	await signOut(page, shellOf(testInfo));

	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	expect(await sessionCookie(page.context())).toBeUndefined();

	// The cookie the browser gave up is offered again: if logging out had only
	// cleared it, this would walk straight back in. B5's `verified_session_id`
	// is what makes the stored session go with it.
	await page.context().addCookies([signedIn as Cookie]);
	await page.goto(HOME_PATH);

	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeVisible();
	await attachShot(page, testInfo, 'auth-signed-out-cookie-refused');
});

// The phone's account circle lives on Home, where every sign-in lands, and on
// the Library (#1354 rule 25), so the phone signs out from either. The account
// menu belongs to the phone shell.
test(
	'signing out from the open account menu on Home, Back returns to Home, which asks for sign-in again',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }, testInfo) => {
		await page.addInitScript(recordAppHistorySteps, APP_HISTORY_STEPS_KEY);
		await signIn(page);

		await signOut(page, 'mobile');
		await expect(page).toHaveURL(LOGIN_PAGE_URL);
		await forgetAppHistorySteps(page);
		await page.goBack();

		// Not an empty Home, and not the account menu's entry stepped through:
		// the door, which brings the person back to Home.
		await expect(page).toHaveURL((url) => isSignInFor(url, HOME_PATH));
		await expect(page.getByLabel(USERNAME_LABEL)).toBeVisible();
		expect(await appHistorySteps(page)).toEqual([]);
		await attachShot(page, testInfo, 'auth-signed-out-back');
	}
);

// The wide window signs out from its rail beside the song; the phone's account
// circle lives on Home and the Library (#1354 rule 25), so the phone walks on to
// the Library through Search, the take still playing, and signs out there.
// The door then brings it back to `/library`, which it names in `redirect`;
// Home, where every sign-in lands, needs no parameter.
test(
	'signing out while a take plays leaves on a fresh sign-in page without the player, and Back asks for sign-in again',
	{ tag: PLAYS_A_TAKE_TAG },
	async ({ page, isMobile }, testInfo) => {
		const shell = shellOf(testInfo);
		if (isMobile) await page.setViewportSize(MOBILE_VIEWPORT);
		const songAddress = await seedOwnSong(seedOwnTakeAddress);
		await signInOnto(page, songAddress);
		await playTheTake(page, shell);
		let leftFrom = songAddress;
		if (shell === 'mobile') {
			leftFrom = LIBRARY_PATH;
			await openLibraryWall(page, shell);
			await expect(page).toHaveURL(LIBRARY_URL);
		}
		await markSignedInDocument(page);

		await signOut(page, shell);

		await expect(page).toHaveURL(LOGIN_PAGE_URL);
		await expect(page.getByLabel(USERNAME_LABEL)).toBeVisible();
		expect(await isSignedInDocument(page)).toBe(false);
		await expect(transportControls(page)).toHaveCount(0);

		await page.goBack();

		await expect(page).toHaveURL((url) => isSignInFor(url, leftFrom));
		if (shell === 'mobile') {
			expect(new URL(page.url()).search).toBe(`?${SESSION_LOST_REDIRECT_PARAM}=%2Flibrary`);
		}
		await expect(page.getByLabel(USERNAME_LABEL)).toBeVisible();
		await expect(transportControls(page)).toHaveCount(0);
		await attachShot(page, testInfo, 'auth-signed-out-while-playing');
	}
);

test(
	'a sign-out the server never receives leaves the person signed in, and says so',
	{ tag: LOSES_NETWORK_TAG },
	async ({ page, context, isMobile }, testInfo) => {
		const shell = shellOf(testInfo);
		if (isMobile) await page.setViewportSize(MOBILE_VIEWPORT);
		await signIn(page);
		const signedIn = await sessionCookie(context);

		await loseNetwork(page, context);
		await signOut(page, shell);

		await expect(
			page
				.getByRole('alert')
				.filter({ hasText: "Couldn't sign out. Check your connection and try again." })
		).toBeVisible();
		await expect(page).toHaveURL(HOME_URL);
		await attachShot(page, testInfo, 'auth-sign-out-offline');
		await regainNetwork(page, context);
		expect((await sessionCookie(context))?.value).toBe(signedIn?.value);

		await page.reload();

		await expect(workspace(page)).toBeVisible();
		await expectSignedInAs(page, testInfo);
	}
);

test(
	'the admin page is refused for a non-admin, with nothing of it rendered',
	{ tag: ADMIN_REFUSED_TAG },
	async ({ page }, testInfo) => {
		await signIn(page);

		const isAdminRead = (response: Response): boolean =>
			new URL(response.url()).pathname.startsWith(ADMIN_API_PREFIX);
		const adminAnswers: number[] = [];
		page.on('response', (response) => {
			if (isAdminRead(response)) adminAnswers.push(response.status());
		});
		// The refusal renders from the session the page already holds, before the
		// reads the page starts on mount have been answered.
		const firstAdminAnswer = page.waitForResponse(isAdminRead);

		await page.goto(ADMIN_PAGE_PATH);

		await expect(page.getByText(ADMIN_REFUSED_MESSAGE)).toBeVisible();
		// Not one control of the page behind it: no tabs to switch.
		await expect(page.getByRole('button', { name: 'Models', exact: true })).toBeHidden();

		// And the server refused it too -- the page is not merely hiding what it was
		// handed.
		await firstAdminAnswer;
		expect(adminAnswers.filter((status) => status !== 403)).toEqual([]);
		await attachShot(page, testInfo, 'auth-admin-refused');
	}
);

test('defect:#1590: a session past its absolute maximum age lands on the login page', async ({
	page
}, testInfo) => {
	await signIn(page);
	const signedIn = await sessionCookie(page.context());
	expect(signedIn).toBeDefined();

	await ageSessionPastAbsoluteLimit(sessionIdOf(signedIn as Cookie));

	await page.reload();

	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeVisible();
	// The browser still carries the cookie; it is the session behind it that the
	// server no longer honours.
	expect((await sessionCookie(page.context()))?.value).toBe(signedIn?.value);
	await attachShot(page, testInfo, 'auth-session-expired');
});

test('a logged-out deep link signs in onto the song it asked for', async ({ page }, testInfo) => {
	await signInOnto(page, await seedOwnSong());

	await attachShot(page, testInfo, 'auth-deep-link-returned');
});

// Search opens over the standing song without changing its address.
test(
	'1354_37a_A5_song: a fresh Search query after expiry returns sign-in to the standing song',
	{ tag: [SEARCH_REFUSED_TAG, ONLY_IN_SHELL.mobile] },
	async ({ page }, testInfo) => {
		const songAddress = await seedOwnSong();
		await signInOnto(page, songAddress);
		const signedIn = await sessionCookie(page.context());
		expect(signedIn).toBeDefined();

		const sheet = await settleSearchOpeningReads(page, () => openSearchSheet(page));
		await expect(page).toHaveURL(new RegExp(`${songAddress}$`));
		const search = sheet.getByRole('combobox', { name: RAIL_SEARCH_LABEL });
		await search.fill('');
		await ageSessionPastAbsoluteLimit(sessionIdOf(signedIn as Cookie));
		const query = albumMarkerOf(albumAddressOf(songAddress));
		const refusedSearch = page.waitForResponse((response) => isSearchResponse(response, query));
		await search.fill(query);
		expect(SESSION_REFUSAL_STATUSES).toContain((await refusedSearch).status());

		// Not a dark page on the song's own address: the door, asked to bring the
		// person back to that song, saying why they are there.
		await expect(page).toHaveURL(
			(url) =>
				url.pathname === '/login' &&
				url.searchParams.get(SESSION_LOST_REDIRECT_PARAM) === songAddress
		);
		await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeVisible();
		await attachShot(page, testInfo, 'auth-phone-session-lost');
	}
);

// Issue #1340, head ruling: a navigation the person already started counts as
// where they meant to be. Which of the tap's requests the server refuses first
// varies from run to run, and the address sign-in returns to must not. The
// Search sheet is a phone layer.
test(
	'1354_37a_A5_album: an album selected in Search after expiry survives overlay Back at sign-in (#1340)',
	{ tag: [ALBUM_OPENING_REFUSED_TAG, ONLY_IN_SHELL.mobile] },
	async ({ page }, testInfo) => {
		await page.setViewportSize(MOBILE_VIEWPORT);
		const albumAddress = albumAddressOf(await seedOwnSong());
		await signIn(page);
		await page.goto(VOICES_PAGE_PATH);
		await expect(page.getByRole('heading', { name: VOICES_HEADING })).toBeVisible();
		const query = albumMarkerOf(albumAddress);
		const found = page.waitForResponse((response) => isSearchResponse(response, query));
		const album = await settleSearchOpeningReads(page, () =>
			phoneSearchResult(page, 'Albums', query, containing(query))
		);
		expect((await found).ok()).toBe(true);

		await ageSessionPastAbsoluteLimit(sessionIdOf((await sessionCookie(page.context())) as Cookie));
		const albumRefusals: ExpectedRefusal[] = ALBUM_OPENING_PATHS.map((path) => ({
			path,
			statuses: SESSION_REFUSAL_STATUSES
		}));
		const refusedAlbum = page.waitForResponse((response) => {
			const pathname = new URL(response.url()).pathname;
			return (
				response.request().method() === 'GET' &&
				albumRefusals.some(
					(refusal) => coversPath(refusal, pathname) && refusal.statuses.includes(response.status())
				)
			);
		});
		await album.click();
		await refusedAlbum;

		await expect(page).toHaveURL(
			(url) =>
				url.pathname === '/login' &&
				url.searchParams.get(SESSION_LOST_REDIRECT_PARAM) === albumAddress
		);
		await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeVisible();
		await attachShot(page, testInfo, 'auth-phone-session-lost-album-tap');
	}
);

// A session the server still holds is never refused a take, so the refusal is
// made here, by route, on the take's audio. The page cannot tell it from a
// lost session, and must leave by one fresh document at the song. The take
// plays on the classic audio element, without MediaSource, as on an iPhone;
// the deck's own refusal reaches the same element (`audioPlayer.test.ts`).
test(
	"925_M3_B-A4: the take's audio refusals are the only refusals, the HEAD last; one fresh document, at the song; no move within the document; nothing plays afterwards",
	{ tag: [TAKE_AUDIO_REFUSED_TAG] },
	async ({ page, isMobile }, testInfo) => {
		const shell = shellOf(testInfo);
		await page.addInitScript(() => Reflect.deleteProperty(window, 'MediaSource'));
		if (isMobile) await page.setViewportSize(MOBILE_VIEWPORT);
		const songAddress = await seedOwnSong(seedOwnTakeAddress);
		await signInOnto(page, songAddress);
		await showTheTakes(page, shell);
		await markSignedInDocument(page);

		const watch = watchTheDocument(page);
		await refuseTheTakeAudio(page, watch);
		const probeAnswered = page.waitForResponse(isTakeProbe);
		const freshDocumentLoaded = page.waitForEvent('load');

		await takeRowPlay(page).click();
		await probeAnswered;
		await freshDocumentLoaded;

		await expect(page).toHaveURL(songAddress);
		await expect(page.getByRole('heading', { name: DEEP_LINK_SONG_TITLE })).toBeVisible();
		const refusedBeforeTheLoad = refusalsBeforeTheLoad(watch);
		expect({
			refusedBeforeTheLoad: [...new Set(refusedBeforeTheLoad)].sort(),
			lastRefusalBeforeTheLoad: refusedBeforeTheLoad.at(-1),
			freshDocuments: watch.freshDocuments,
			movesWithinTheDocument: watch.movesWithinTheDocument,
			signedInDocument: await isSignedInDocument(page),
			offersPause: (await footerPause(page).count()) > 0
		}).toEqual({
			refusedBeforeTheLoad: ['GET take audio 401', 'HEAD take audio 401'],
			lastRefusalBeforeTheLoad: 'HEAD take audio 401',
			freshDocuments: [songAddress],
			movesWithinTheDocument: [],
			signedInDocument: false,
			offersPause: false
		});
		await attachShot(page, testInfo, 'auth-media-refused-925_M3_B-A4');
	}
);

test('wrong passwords lock the account, in words and for as long as it says', async ({
	page
}, testInfo) => {
	// The flow waits out the lockout the server states, so it needs longer than
	// a default test.
	test.setTimeout(LOCKOUT_TEST_TIMEOUT_MS);
	await page.goto('/login');

	let refusal: Response | undefined;
	let refusedAt = 0;
	for (let attempt = 1; attempt <= MAX_WRONG_PASSWORDS && !refusal; attempt += 1) {
		const response = await submitLogin(page, account.username, WRONG_PASSWORD);
		if (response.status() === 429) {
			refusal = response;
			refusedAt = Date.now();
			break;
		}
		expect(response.status()).toBe(401);
		await expect(page.getByText(INVALID_CREDENTIALS_MESSAGE)).toBeVisible();
	}

	expect(refusal, `no lockout after ${MAX_WRONG_PASSWORDS} wrong passwords`).toBeDefined();
	await expect(page.getByText(REFUSED_LOGIN_MESSAGE)).toBeVisible();
	await attachShot(page, testInfo, 'auth-locked-out');

	// Which refusal this is, from the server's own words rather than from the
	// one line the store shows for either.
	await expectAccountLocked(refusal as Response);

	// It names how long it stands, and the right password does not get past it
	// either -- the lock is on the account, not on the typing.
	const retryAfter = Number((refusal as Response).headers()['retry-after']);
	expect(Number.isInteger(retryAfter)).toBe(true);
	expect(retryAfter).toBeGreaterThan(0);
	await expectAccountLocked(await submitLogin(page, account.username, account.password));

	if (retryAfter > MAX_HONOURED_RETRY_AFTER_SECONDS) {
		// Locally a stack may state an hour, and a run does not sit that out. In
		// CI it means the stack is not configured as this flow needs, and a
		// half-driven flow that still reports green is worse than a red one.
		if (process.env.CI) {
			throw new Error(
				`the stack states a ${retryAfter}s lockout, more than a run honours — check the LOGIN_LOCKOUT_* overrides in docker/docker-compose.ci.yml`
			);
		}
		testInfo.annotations.push({
			type: 'not driven',
			description: `the stack states ${retryAfter}s; a run honours a wait, it does not sit one out`
		});
		return;
	}
	// Honouring what the server said, rather than guessing a sleep: within
	// that long the same account is admitted again, so the lock the person
	// read about really is temporary. A poll never starts a wait that would end
	// past its deadline, and its last refused try may come just before the lock
	// lifts, so the deadline runs two intervals past the statement. That slack
	// only bounds the run: the proof is that no try started once the stated
	// time was up was still refused. The server's window opened at the first
	// wrong password, before the refusal, so an honest lock cannot fail this.
	const statedLiftAt = refusedAt + retryAfter * 1000;
	let lastRefusedTryStartedAt = refusedAt;
	await expect
		.poll(
			async () => {
				const tryStartedAt = Date.now();
				const status = (await submitLogin(page, account.username, account.password)).status();
				if (status !== 200) lastRefusedTryStartedAt = tryStartedAt;
				return status;
			},
			{
				intervals: [LOCK_LIFT_POLL_INTERVAL_MS],
				timeout: retryAfter * 1000 + 2 * LOCK_LIFT_POLL_INTERVAL_MS
			}
		)
		.toBe(200);
	expect(
		lastRefusedTryStartedAt,
		`a try ${lastRefusedTryStartedAt - statedLiftAt}ms after the stated ${retryAfter}s was still refused`
	).toBeLessThan(statedLiftAt);
	await expect(page).toHaveURL(HOME_URL);
});
