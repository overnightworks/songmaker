// Signing in through Keycloak, as far as it runs without Keycloak (#1765): the
// CI stack has no identity provider, so these flows drive everything up to the
// redirect and everything after the return that the server answers by itself.
// What happens at the issuer -- the real login, the callback that opens a
// session -- is a named gap of #1620, proven live, not here.
//
// Each sentence is about the browser and the server together: which request
// the page makes, what the server answers, which page the address bar ends
// on. Whatever leaves the app's origin ends on a stub (`stubIdentityProvider`).
// Both shells drive every flow.

import { expect, test, type Locator, type Page } from '@playwright/test';

import { ACCOUNT_MENU_LOGOUT_LABEL, SETTINGS_NAV_LABEL } from '../src/lib/constants';
import {
	NO_ACCESS_BACK_LABEL,
	NO_ACCESS_HEADING,
	SIGN_IN_ACTION_LABEL,
	SIGN_IN_FAILED_HEADING,
	SIGN_IN_RETRY_LABEL,
	SIGNED_OUT_HEADING
} from '../src/lib/constants/auth';
import {
	FlowGuard,
	leftTheApp,
	nameStartingWith,
	nextSignInStart,
	shellOf,
	stubIdentityProvider
} from './helpers';
import { BASE_URL, runMarker, seedAccount, signedInApi, type SeededAccount } from './seed';

// The service worker answers a navigation on the page's behalf, and Playwright
// then reports the server's redirect only until the worker has taken the page
// over; these flows watch that redirect, and none of them is about offline use.
test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block' });

const SESSION_REFUSED = [{ path: '/api/auth/me', statuses: [401] }];
const FAILED_SIGN_IN_REFUSED = [{ path: '/auth/callback', statuses: [403] }];
const AUTHORIZATION_ENDPOINT_SUFFIX = '/protocol/openid-connect/auth';
const LOGOUT_ENDPOINT_SUFFIX = '/protocol/openid-connect/logout';

test.beforeEach(async ({ context }) => {
	await stubIdentityProvider(context);
});

test('the sign-in start sends the browser to the issuer with a pending login that only a return can finish', async ({
	request
}) => {
	const response = await request.get('/login/oidc?next=%2Flibrary', { maxRedirects: 0 });

	expect(response.status()).toBe(303);
	const location = new URL(response.headers()['location']);
	expect(location.origin).not.toBe(new URL(BASE_URL).origin);
	expect(location.pathname.endsWith(AUTHORIZATION_ENDPOINT_SUFFIX)).toBe(true);
	expect(location.searchParams.get('response_type')).toBe('code');
	expect(location.searchParams.get('code_challenge_method')).toBe('S256');
	expect(location.searchParams.get('scope')?.split(' ')).toContain('openid');
	expect(location.searchParams.get('redirect_uri')).toMatch(/\/auth\/callback$/);
	expect(location.searchParams.get('state')).toBeTruthy();
	expect(response.headers()['cache-control']).toContain('no-store');
	const pendingLogin = response
		.headersArray()
		.filter(({ name }) => name.toLowerCase() === 'set-cookie')
		.find(({ value }) => /oidc_pending/.test(value));
	expect(pendingLogin?.value, 'the start leaves a pending-login cookie').toMatch(/samesite=lax/i);
});

test('the signed-out page says so and starts the sign-in only when Log in is pressed', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	const started: string[] = [];
	page.on('request', (request) => {
		if (new URL(request.url()).pathname === '/login/oidc') started.push(request.url());
	});

	await page.goto('/login');

	await expect(page.getByRole('heading', { name: SIGNED_OUT_HEADING })).toBeVisible();
	const logIn = page.getByRole('link', { name: SIGN_IN_ACTION_LABEL, exact: true });
	await expect(logIn).toHaveAttribute('href', '/login/oidc');
	await page.waitForLoadState('networkidle');
	expect(started, 'the page redirects by itself').toEqual([]);
	expect(new URL(page.url()).pathname).toBe('/login');

	const [start] = await Promise.all([nextSignInStart(page), logIn.click()]);

	expect(start.status).toBe(303);
	expect(start.location.pathname.endsWith(AUTHORIZATION_ENDPOINT_SUFFIX)).toBe(true);
	await expect.poll(() => leftTheApp(page)).toBe(true);
	await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
	guard.assertClean();
});

test('a protected address asks the server to sign in and to come back to it', async ({ page }) => {
	const guard = new FlowGuard(page, { refusalsExpectedOn: SESSION_REFUSED });

	const [start] = await Promise.all([nextSignInStart(page), page.goto('/library')]);

	expect(start.status).toBe(303);
	expect(start.requested.search).toBe('?next=%2Flibrary');
	expect(start.location.pathname.endsWith(AUTHORIZATION_ENDPOINT_SUFFIX)).toBe(true);
	await expect.poll(() => leftTheApp(page)).toBe(true);
	await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
	guard.assertClean();
});

test('an API request without a session is refused with 401 and nothing redirects it', async ({
	request
}) => {
	const response = await request.get('/api/auth/me', { maxRedirects: 0 });

	expect(response.status()).toBe(401);
});

for (const address of ['/share/song/no-such-share']) {
	test(`${address} opens without a session and never asks to sign in`, async ({ page }) => {
		const started: string[] = [];
		page.on('request', (request) => {
			if (new URL(request.url()).pathname === '/login/oidc') started.push(request.url());
		});

		await page.goto(address);
		await page.waitForLoadState('networkidle');

		expect(started).toEqual([]);
		expect(new URL(page.url()).pathname).toBe(address);
	});
}

test('no access offers Sign out and Back, and Back leads to the signed-out page', async ({
	page
}) => {
	const guard = new FlowGuard(page);

	await page.goto('/no-access');

	await expect(page.getByRole('heading', { name: NO_ACCESS_HEADING })).toBeVisible();
	await expect(page.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL })).toBeVisible();
	await page.getByRole('link', { name: NO_ACCESS_BACK_LABEL, exact: true }).click();

	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByRole('heading', { name: SIGNED_OUT_HEADING })).toBeVisible();
	guard.assertClean();
});

test('Sign out on no access posts to the server and the answer sends the browser on to the issuer', async ({
	page
}) => {
	// The sign-out first reads the session; this browser has none, and a 401 passes that check.
	const guard = new FlowGuard(page, { refusalsExpectedOn: SESSION_REFUSED });
	await page.goto('/no-access');

	const [answer, issuerLogout] = await Promise.all([
		page.waitForResponse((response) => new URL(response.url()).pathname === '/auth/logout'),
		page.waitForRequest((request) => {
			const address = new URL(request.url());
			return (
				address.origin !== new URL(BASE_URL).origin &&
				address.pathname.endsWith(LOGOUT_ENDPOINT_SUFFIX)
			);
		}),
		page.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL }).click()
	]);

	expect(answer.request().method()).toBe('POST');
	expect(answer.status()).toBe(200);
	expect(answer.headers()['cache-control']).toContain('no-store');
	expect(answer.headers()['content-type']).toContain('text/html');
	expect(
		(await answer.headersArray())
			.filter(({ name }) => name.toLowerCase() === 'set-cookie')
			.some(({ value }) => value.includes('session_id=')),
		'the session cookie is cleared'
	).toBe(true);
	expect(issuerLogout.method()).toBe('POST');
	expect(issuerLogout.url(), 'the address carries no field').not.toContain('?');
	await expect.poll(() => page.url()).toBe(issuerLogout.url());
	guard.assertClean();
});

test('a logout from another origin is refused, a same-origin one answers the logout page', async ({
	request
}) => {
	const foreign = await request.post('/auth/logout', {
		headers: { origin: 'https://evil.example' }
	});
	const own = await request.post('/auth/logout', { headers: { origin: BASE_URL } });

	expect(foreign.status()).toBe(403);
	expect(own.status()).toBe(200);
	expect(own.headers()['content-type']).toContain('text/html');
});

// Cell 26
test('with JavaScript off the logout page shows one button named like the account menu entry', async ({
	browser,
	request
}) => {
	const page = await (await browser.newContext({ javaScriptEnabled: false })).newPage();
	const logoutPage = await request.post('/auth/logout', { headers: { origin: BASE_URL } });

	await page.setContent(await logoutPage.text());

	await expect(page.getByRole('button')).toHaveCount(1);
	await expect(page.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL })).toBeVisible();
	await page.context().close();
});

for (const [refusal, query] of [
	['a return with no pending login', '?code=abc&state=forged'],
	['an issuer error', '?error=access_denied&state=forged']
] as const) {
	test(`${refusal} shows Login failed with the server's 403, and Try again starts a new sign-in`, async ({
		page
	}) => {
		const guard = new FlowGuard(page, { refusalsExpectedOn: FAILED_SIGN_IN_REFUSED });

		const response = await page.goto(`/auth/callback${query}`);

		expect(response?.status()).toBe(403);
		expect(response?.headers()['cache-control']).toContain('no-store');
		await expect(page.getByRole('heading', { name: SIGN_IN_FAILED_HEADING })).toBeVisible();
		await expect(page.getByRole('alert')).toBeVisible();
		const [start] = await Promise.all([
			nextSignInStart(page),
			page.getByRole('link', { name: SIGN_IN_RETRY_LABEL, exact: true }).click()
		]);
		expect(start.status).toBe(303);
		await expect.poll(() => leftTheApp(page)).toBe(true);
		await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
		guard.assertClean();
	});
}

function settingsSections(page: Page): Locator {
	return page.getByRole('navigation', { name: SETTINGS_NAV_LABEL });
}

async function signInAs(page: Page, account: SeededAccount): Promise<void> {
	await page.context().clearCookies();
	await page.context().addCookies(account.cookies);
}

test('an open page whose session ended on the server leaves for the sign-in start with its own address', async ({
	page
}, info) => {
	const shell = shellOf(info);
	const account = await seedAccount(`e2e-ended-${info.project.name}-${runMarker()}`);
	const guard = new FlowGuard(page, { refusalsExpectedOn: [{ path: '/api/', statuses: [401] }] });
	await signInAs(page, account);
	// Finish this empty account's initial requests before revoking the session they use.
	const initialPaths = ['/api/capabilities'];
	if (shell === 'desktop') {
		initialPaths.push(
			'/api/albums',
			'/api/playlists',
			'/api/settings/generation-builtins',
			'/api/settings/presets',
			'/api/settings/models',
			'/api/settings/default-config',
			'/api/settings/generation-defaults'
		);
	}
	const initialResponses = initialPaths.map((path) =>
		page.waitForResponse((response) => {
			const url = new URL(response.url());
			return (
				url.origin === new URL(BASE_URL).origin &&
				url.pathname === path &&
				response.request().method() === 'GET'
			);
		})
	);
	await page.goto('/settings');
	const voices = settingsSections(page).getByRole('link', { name: nameStartingWith('Voices') });
	await expect(voices).toBeVisible();
	// The desktop Settings index forwards to its first section; the rail's link is the same one after it.
	if (shell === 'desktop') await expect(page).toHaveURL(/\/settings\/generation$/);
	for (const response of await Promise.all(initialResponses)) {
		expect(response.status(), response.url()).toBe(200);
		expect(await response.finished(), response.url()).toBeNull();
	}

	const server = await signedInApi(account);
	try {
		expect((await server.post('/auth/logout', { headers: { origin: BASE_URL } })).status()).toBe(
			200
		);
	} finally {
		await server.dispose();
	}
	// The page still holds its cookies and its code; only the server forgot the session.
	const [start] = await Promise.all([nextSignInStart(page), voices.click()]);

	expect(start.status).toBe(303);
	expect(start.requested.search).toBe(`?next=${encodeURIComponent('/settings/voices')}`);
	await expect.poll(() => leftTheApp(page)).toBe(true);
	await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
	guard.assertClean();
});
