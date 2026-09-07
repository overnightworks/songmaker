// The auth chain B1-B5 driven the way a musician meets it (issue #872, bundle
// B6 of the library extraction #825): signing in, being locked out after
// repeated wrong passwords, signing out, coming back to a reloaded tab, being
// refused the admin page, and returning to a session that has outlived its
// absolute maximum age.
//
// This is here rather than in the unit suite because each of those six
// sentences is about the browser and the server together: which page the
// address bar ends on, whether the cookie is still carried, what the person
// reads when a refusal arrives -- and, the one B5 made structural, whether the
// session behind a cookie still exists on the server at all. A jsdom test can
// only ask the store what it believes; it cannot re-offer a cookie the browser
// has thrown away and watch the server refuse it.
//
// No route interception anywhere: every refusal is the CI stack's own answer.
// The two numbers the lockout flow depends on are set in
// `docker/docker-compose.ci.yml`, with the measurement written beside them --
// the short-window budget counts failed logins per *IP* and the whole run comes
// from one address, so production's five would refuse every later login in the
// suite, while the lockout counts per *account* and therefore stays on this
// spec's own throwaway user.
//
// Both shells drive all six flows: the compact one at 375px, which is where the
// rail is a drawer and Logout is reached through it.

import {
	expect,
	request,
	test,
	type APIRequestContext,
	type BrowserContext,
	type Cookie,
	type Page,
	type Response,
	type TestInfo
} from '@playwright/test';

import { AUTH_SESSION_EXPIRED_MESSAGE } from '../src/lib/constants/auth';
import { FlowGuard, openRailNav, shellOf, workspace } from './helpers';
import {
	BASE_URL,
	STORAGE_STATE_FILE,
	ageSessionPastAbsoluteLimit,
	createAccount,
	deleteAccount
} from './seed';

/**
 * What each test costs the API, measured on a green run of both shells against
 * the CI recipe (desktop / 375px): 13/13 for the sign-in, 19/19 for the reload,
 * 14/14 for the sign-out and the refused return, 18/15 for the refused admin
 * page, 13/12 for the expired session, 11/11 for the lockout. One ceiling for
 * the file, the same way `admin-models.spec.ts` carries one for its four. The
 * budget is a ceiling, not a knob: a flow that suddenly needs several more
 * round trips is a regression, so find the extra requests instead of raising
 * this number -- see `LIBRARY_FLOW_API_REQUEST_BUDGET` in `helpers.ts` for the
 * full reasoning.
 */
const AUTH_FLOW_API_REQUEST_BUDGET = 30;

const AUTH_LOGIN_PATH = '/api/auth/login';
const AUTH_ME_PATH = '/api/auth/me';
const ADMIN_API_PREFIX = '/api/admin/';
const ADMIN_USERS_PATH = '/api/admin/users';
const ADMIN_SESSIONS_PATH = '/api/admin/sessions';
const ADMIN_LOGIN_ATTEMPTS_PATH = '/api/admin/login-attempts';
const REFUSED_PATHS = [
	AUTH_LOGIN_PATH,
	AUTH_ME_PATH,
	ADMIN_USERS_PATH,
	ADMIN_SESSIONS_PATH,
	ADMIN_LOGIN_ATTEMPTS_PATH
];
const ADMIN_PAGE_PATH = '/settings/users';
const SESSION_COOKIE = 'session_id';

// The narrowest phone the shell is drawn for -- the mobile project's own
// viewport is 390, and #872 rules this chain at 375.
const PHONE_VIEWPORT = { width: 375, height: 844 };

const LOGIN_PAGE_URL = /\/login(\?|$)/;
const WALL_URL = /\/(\?|$)/;

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
// A `Retry-After` a run can honour: the CI stack states 60 seconds, and waiting
// exactly what the server said is what proves the lock is temporary rather than
// terminal. A production-like stack states an hour, and the flow says so and
// stops instead of hanging the suite.
const MAX_HONOURED_RETRY_AFTER_SECONDS = 90;
const LOCKOUT_TEST_TIMEOUT_MS = 180_000;

interface Account {
	id: string;
	username: string;
	password: string;
}

let adminApi: APIRequestContext;
let account: Account;
let guard: FlowGuard;

// Every flow starts at the door: the run's admin storage state would answer
// half of these questions before they are asked. It has to be an explicitly
// empty state -- `undefined` reads as "not overridden" here and leaves the
// project's own signed-in state in place.
test.use({ storageState: { cookies: [], origins: [] } });

test.beforeAll(async () => {
	adminApi = await request.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE_FILE });
	// One account per project, so the shell that locks it out cannot lock the
	// other shell's flows out with it.
	const username = `e2e-b6-${test.info().project.name}-${Date.now().toString(36)}`;
	account = {
		id: await createAccount(adminApi, username, ACCOUNT_PASSWORD),
		username,
		password: ACCOUNT_PASSWORD
	};
});

test.afterAll(async () => {
	await deleteAccount(adminApi, account.id);
	await adminApi.dispose();
});

test.beforeEach(async ({ page, isMobile }) => {
	if (isMobile) await page.setViewportSize(PHONE_VIEWPORT);
	// Every refusal this file drives is one of its six sentences: the login it
	// locks out, the `/api/auth/me` a dead session answers, the admin calls a
	// non-admin makes. A refusal anywhere else, and any 5xx at all, still fails
	// the flow.
	guard = new FlowGuard(page, { refusalsExpectedOn: REFUSED_PATHS });
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Auth flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(AUTH_FLOW_API_REQUEST_BUDGET);
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

/** Signs in from the login page and waits until the workspace is standing. */
async function signIn(page: Page): Promise<void> {
	await page.goto('/login');
	const response = await submitLogin(page, account.username, account.password);
	expect(response.status()).toBe(200);
	await expect(page).toHaveURL(WALL_URL);
	await expect(workspace(page)).toBeVisible();
}

/** The account's own name, where the shell shows who is signed in. */
async function expectSignedInAs(page: Page, testInfo: TestInfo): Promise<void> {
	const rail = await openRailNav(page, shellOf(testInfo));
	await expect(rail.getByRole('link', { name: account.username })).toBeVisible();
}

async function sessionCookie(context: BrowserContext): Promise<Cookie | undefined> {
	const cookies = await context.cookies();
	return cookies.find((cookie) => cookie.name === SESSION_COOKIE);
}

/** The signed cookie is `<session id>.<hmac>` (`webauth.cookies`). */
function sessionIdOf(cookie: Cookie): string {
	return cookie.value.slice(0, cookie.value.lastIndexOf('.'));
}

/** The refusal the lockout flow is about, named by the server itself. */
async function expectAccountLocked(refusal: Response): Promise<void> {
	expect(refusal.status()).toBe(429);
	expect((await refusal.json()).detail).toBe(ACCOUNT_LOCKED_DETAIL);
}

async function attachShot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
	const path = testInfo.outputPath(`${name}.png`);
	await page.screenshot({ path, fullPage: true });
	await testInfo.attach(name, { path, contentType: 'image/png' });
}

test('a musician signs in and the shell shows whose session it is', async ({ page }, testInfo) => {
	// A tab that knows nothing is sent to the door rather than shown a wall.
	await page.goto('/');
	await expect(page).toHaveURL(LOGIN_PAGE_URL);

	const response = await submitLogin(page, account.username, account.password);
	expect(response.status()).toBe(200);

	await expect(page).toHaveURL(WALL_URL);
	await expectSignedInAs(page, testInfo);
	expect(await sessionCookie(page.context())).toBeDefined();
	await attachShot(page, testInfo, 'auth-signed-in');
});

test('the session survives a reload of the tab', async ({ page }, testInfo) => {
	await signIn(page);
	const before = await sessionCookie(page.context());

	await page.reload();

	await expect(page).toHaveURL(WALL_URL);
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

	const rail = await openRailNav(page, shellOf(testInfo));
	await rail.getByRole('button', { name: LOGOUT_LABEL }).click();

	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	expect(await sessionCookie(page.context())).toBeUndefined();

	// The cookie the browser gave up is offered again: if logging out had only
	// cleared it, this would walk straight back in. B5's `verified_session_id`
	// is what makes the stored session go with it.
	await page.context().addCookies([signedIn as Cookie]);
	await page.goto('/');

	await expect(page).toHaveURL(LOGIN_PAGE_URL);
	await expect(page.getByText(AUTH_SESSION_EXPIRED_MESSAGE)).toBeVisible();
	await attachShot(page, testInfo, 'auth-signed-out-cookie-refused');
});

test('the admin page is refused for a non-admin, with nothing of it rendered', async ({
	page
}, testInfo) => {
	await signIn(page);

	const adminAnswers: number[] = [];
	page.on('response', (response) => {
		if (new URL(response.url()).pathname.startsWith(ADMIN_API_PREFIX)) {
			adminAnswers.push(response.status());
		}
	});

	await page.goto(ADMIN_PAGE_PATH);

	await expect(page.getByText(ADMIN_REFUSED_MESSAGE)).toBeVisible();
	// Not one control of the page behind it: no tabs to switch, no form to
	// create an account with, no table of accounts.
	await expect(page.getByRole('heading', { name: 'Create User' })).toBeHidden();
	await expect(page.getByRole('button', { name: 'Models', exact: true })).toBeHidden();
	await expect(page.getByPlaceholder('Username')).toBeHidden();

	// And the server refused it too -- the page is not merely hiding what it was
	// handed.
	expect(adminAnswers.length).toBeGreaterThan(0);
	expect(adminAnswers.filter((status) => status !== 403)).toEqual([]);
	await attachShot(page, testInfo, 'auth-admin-refused');
});

test('a session past its absolute maximum age lands on the login page', async ({
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
	expect(await sessionCookie(page.context())).toBeDefined();
	await attachShot(page, testInfo, 'auth-session-expired');
});

test('wrong passwords lock the account, in words and for as long as it says', async ({
	page
}, testInfo) => {
	// The flow waits out the lockout the server states, so it needs longer than
	// a default test.
	test.setTimeout(LOCKOUT_TEST_TIMEOUT_MS);
	await page.goto('/login');

	let refusal: Response | undefined;
	for (let attempt = 1; attempt <= MAX_WRONG_PASSWORDS && !refusal; attempt += 1) {
		const response = await submitLogin(page, account.username, WRONG_PASSWORD);
		if (response.status() === 429) {
			refusal = response;
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
	// Honouring what the server said, rather than guessing a sleep: after
	// exactly that long the same account is admitted again, so the lock the
	// person read about really is temporary.
	await page.waitForTimeout((retryAfter + 1) * 1000);
	expect((await submitLogin(page, account.username, account.password)).status()).toBe(200);
	await expect(page).toHaveURL(WALL_URL);
});
