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

import { expect, test } from '@playwright/test';

import { ACCOUNT_MENU_LOGOUT_LABEL } from '../src/lib/constants';
import {
	NO_ACCESS_BACK_LABEL,
	NO_ACCESS_HEADING,
	SIGN_IN_ACTION_LABEL,
	SIGN_IN_FAILED_HEADING,
	SIGN_IN_RETRY_LABEL,
	SIGNED_OUT_HEADING
} from '../src/lib/constants/auth';
import { FlowGuard, leftTheApp, nextSignInStart, stubIdentityProvider } from './helpers';
import { BASE_URL } from './seed';

test.use({ storageState: { cookies: [], origins: [] } });

const SESSION_REFUSED = [{ path: '/api/auth/me', statuses: [401] }];
const FAILED_SIGN_IN_REFUSED = [{ path: '/auth/callback', statuses: [403] }];
const AUTHORIZATION_ENDPOINT_SUFFIX = '/protocol/openid-connect/auth';

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
	guard.assertClean();
});

test('a protected address asks the server to sign in and to come back to it', async ({ page }) => {
	const guard = new FlowGuard(page, { refusalsExpectedOn: SESSION_REFUSED });

	const [start] = await Promise.all([nextSignInStart(page), page.goto('/library')]);

	expect(start.status).toBe(303);
	expect(start.requested.search).toBe('?next=%2Flibrary');
	expect(start.location.pathname.endsWith(AUTHORIZATION_ENDPOINT_SUFFIX)).toBe(true);
	await expect.poll(() => leftTheApp(page)).toBe(true);
	guard.assertClean();
});

test('an API request without a session is refused with 401 and nothing redirects it', async ({
	request
}) => {
	const response = await request.get('/api/auth/me', { maxRedirects: 0 });

	expect(response.status()).toBe(401);
});

for (const address of ['/legal', '/impressum', '/datenschutz', '/share/song/no-such-share']) {
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

test('no access offers Log out and Back, and Back leads to the signed-out page', async ({
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

test('Log out on no access asks the server for the issuer logout address and leaves for it', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	await page.goto('/no-access');

	const [logout] = await Promise.all([
		page.waitForResponse(
			(response) =>
				new URL(response.url()).pathname === '/auth/logout' &&
				response.request().method() === 'POST'
		),
		page.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL }).click()
	]);

	expect(logout.status()).toBe(200);
	expect(logout.headers()['cache-control']).toContain('no-store');
	const { logout_url: logoutUrl } = (await logout.json()) as { logout_url: string };
	expect(new URL(logoutUrl).origin).not.toBe(new URL(BASE_URL).origin);
	const cleared = (await logout.headersArray())
		.filter(({ name }) => name.toLowerCase() === 'set-cookie')
		.map(({ value }) => value);
	for (const cookie of ['session_id', 'csrf_token']) {
		expect(
			cleared.some((line) => line.includes(`${cookie}=`)),
			`${cookie} is cleared`
		).toBe(true);
	}
	await expect.poll(() => page.url()).toBe(new URL(logoutUrl).href);
	guard.assertClean();
});

test('a logout from another origin is refused, a same-origin one needs no token', async ({
	request
}) => {
	const foreign = await request.post('/auth/logout', {
		headers: { origin: 'https://evil.example' }
	});
	const own = await request.post('/auth/logout', { headers: { origin: BASE_URL } });

	expect(foreign.status()).toBe(403);
	expect(own.status()).toBe(200);
	expect(typeof (await own.json()).logout_url).toBe('string');
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
		guard.assertClean();
	});
}
