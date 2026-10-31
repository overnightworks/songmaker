// The light-or-dark choice belongs to the person (#2107): the server keeps it,
// each browser keeps a copy that paints before the server answers. Every flow
// uses an account of its own, because the choice is stored on the account.

import { expect, test, type Browser, type Page, type Response } from '@playwright/test';

import { THEME_SWITCH_TO_DARK_LABEL, THEME_SWITCH_TO_LIGHT_LABEL } from '../src/lib/constants';
import {
	accountCircle,
	accountMenu,
	HOME_PATH,
	LIBRARY_PATH,
	shellOf,
	waitForServiceWorkerControl
} from './helpers';
import { seedAccount, signedInApi, runMarker, type SeededAccount } from './seed';

const COPY_KEY = 'songmaker.theme';
const THEME_PATH = '/api/settings/theme';
const SHARE_PATH = '/share/song/no-such-share';

test.use({ storageState: { cookies: [], origins: [] } });

let account: SeededAccount;

test.beforeEach(async ({ context }, testInfo) => {
	account = await seedAccount(`e2e-theme-${testInfo.project.name}-${runMarker()}`);
	await context.addCookies(account.cookies);
});

async function looks(page: Page) {
	return page.evaluate(() => ({
		chosen: document.documentElement.dataset.theme ?? null,
		copy: localStorage.getItem('songmaker.theme'),
		legacy: localStorage.getItem('theme')
	}));
}

async function openAccountMenu(page: Page, shell: 'mobile' | 'desktop') {
	await page.goto(shell === 'mobile' ? LIBRARY_PATH : '/settings/generation');
	await accountCircle(page).click();
	return accountMenu(page);
}

function themeAnswer(method: 'GET' | 'PUT') {
	return (response: Response) =>
		response.url().endsWith(THEME_PATH) && response.request().method() === method;
}

async function choose(theme: 'light' | 'dark' | 'system') {
	const api = await signedInApi(account);
	const response = await api.put(THEME_PATH, { data: { theme } });
	expect(response.ok()).toBe(true);
	await api.dispose();
}

async function secondBrowser(browser: Browser, colorScheme: 'light' | 'dark') {
	const context = await browser.newContext({ colorScheme });
	await context.addCookies(account.cookies);
	return { context, page: await context.newPage() };
}

test('1: dark chosen in browser A is shown by browser B of the same person at its next load', async ({
	browser,
	page
}, info) => {
	await page.emulateMedia({ colorScheme: 'light' });
	const menu = await openAccountMenu(page, shellOf(info));
	const saved = page.waitForResponse(themeAnswer('PUT'));
	await menu.getByRole('button', { name: THEME_SWITCH_TO_DARK_LABEL, exact: true }).click();
	expect((await saved).ok()).toBe(true);
	await expect.poll(() => looks(page)).toMatchObject({ chosen: 'dark', copy: 'dark' });

	const other = await secondBrowser(browser, 'light');
	await other.page.goto(HOME_PATH);
	await expect.poll(() => looks(other.page)).toMatchObject({ chosen: 'dark', copy: 'dark' });
	await other.context.close();
});

test('20: an open browser B does not change when A switches, and its next load does', async ({
	browser,
	page
}) => {
	await page.emulateMedia({ colorScheme: 'light' });
	await page.goto(HOME_PATH);
	const other = await secondBrowser(browser, 'light');
	const answered = other.page.waitForResponse(themeAnswer('GET'));
	await other.page.goto(HOME_PATH);
	await answered;
	await choose('dark');

	expect(await looks(other.page)).toMatchObject({ chosen: null });
	await other.page.reload();
	await expect.poll(() => looks(other.page)).toMatchObject({ chosen: 'dark' });
	await other.context.close();
});

for (const device of ['light', 'dark'] as const) {
	test(`9: a person who has not chosen follows a ${device} device`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: device });
		await page.goto(HOME_PATH);

		await expect.poll(() => looks(page)).toMatchObject({ chosen: null, copy: 'system' });
	});
}

test('14: with the theme request held, the copy is already painted', async ({ page }) => {
	await choose('dark');
	await page.emulateMedia({ colorScheme: 'light' });
	await page.addInitScript((key) => {
		if (!localStorage.getItem(key)) localStorage.setItem(key, 'dark');
	}, COPY_KEY);
	await page.route(`**${THEME_PATH}`, () => {
		// Never answered: the first paint cannot have waited for it.
	});

	await page.goto(HOME_PATH, { waitUntil: 'domcontentloaded' });

	await expect.poll(() => looks(page)).toMatchObject({ chosen: 'dark' });
});

test("16: a fresh browser paints by the device, then switches once to the person's choice", async ({
	page
}) => {
	await choose('dark');
	await page.emulateMedia({ colorScheme: 'light' });
	const paints: Array<string | null> = [];
	await page.exposeFunction('recordPaint', (value: string | null) => paints.push(value));
	await page.addInitScript(() => {
		new MutationObserver(() =>
			(window as unknown as { recordPaint(v: string | null): void }).recordPaint(
				document.documentElement.dataset.theme ?? null
			)
		).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
	});

	await page.goto(HOME_PATH);

	await expect.poll(() => looks(page)).toMatchObject({ chosen: 'dark' });
	expect(paints).toEqual(['dark']);
});

test('21: the menu toggle from the device choice on a dark device sends light', async ({
	page
}, info) => {
	await page.emulateMedia({ colorScheme: 'dark' });
	const menu = await openAccountMenu(page, shellOf(info));
	const sent = page.waitForRequest(
		(request) => request.url().endsWith(THEME_PATH) && request.method() === 'PUT'
	);

	await menu.getByRole('button', { name: THEME_SWITCH_TO_LIGHT_LABEL, exact: true }).click();

	expect((await sent).postDataJSON()).toEqual({ theme: 'light' });
});

test("19: a share page viewed without an account paints from this browser's copy and requests no theme", async ({
	browser
}) => {
	const context = await browser.newContext({ colorScheme: 'light' });
	const page = await context.newPage();
	const requested: string[] = [];
	page.on('request', (request) => requested.push(new URL(request.url()).pathname));
	await page.addInitScript((key) => localStorage.setItem(key, 'dark'), COPY_KEY);

	await page.goto(SHARE_PATH, { waitUntil: 'networkidle' });

	expect(await looks(page)).toMatchObject({ chosen: 'dark' });
	expect(requested).not.toContain(THEME_PATH);
	await context.close();
});

test('23 and 24: a legacy theme key paints nothing, is removed, and is not taken over', async ({
	page
}) => {
	await page.emulateMedia({ colorScheme: 'light' });
	await page.addInitScript(() => {
		if (!localStorage.getItem('seeded-legacy')) {
			localStorage.setItem('theme', 'dark');
			localStorage.setItem('seeded-legacy', 'yes');
		}
	});

	await page.goto(HOME_PATH);

	await expect.poll(() => looks(page)).toMatchObject({ chosen: null, legacy: null });
	const api = await signedInApi(account);
	expect(await (await api.get(THEME_PATH)).json()).toEqual({ theme: 'system' });
	await api.dispose();
});

test.describe('offline', () => {
	test.use({ serviceWorkers: 'allow' });

	test('15: an offline reload paints the copy a real online boot wrote', async ({
		context,
		page
	}) => {
		await page.emulateMedia({ colorScheme: 'light' });
		await choose('dark');
		await page.goto(HOME_PATH);
		await expect.poll(() => looks(page)).toMatchObject({ chosen: 'dark', copy: 'dark' });
		await waitForServiceWorkerControl(page);
		await context.setOffline(true);

		await page.reload();

		expect(await looks(page)).toMatchObject({ chosen: 'dark' });
	});
});
