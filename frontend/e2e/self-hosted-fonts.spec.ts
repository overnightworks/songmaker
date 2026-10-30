// Songmaker serves its own fonts (issue #1214): no page, logged in or not,
// asks a Google font host for anything, and the two families still render in
// every weight the stylesheet names. Only a real browser shows both -- which
// hosts a page actually contacts, and which faces it actually loaded.
// The shipped fonts are woff2 alone (issue #1224).

import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { ONLY_IN_SHELL } from './helpers';
import { readSeededLibrary } from './seed';

const GOOGLE_FONT_HOSTS: readonly string[] = ['fonts.googleapis.com', 'fonts.gstatic.com'];

const SERVED_FACES: readonly { family: string; weight: string }[] = [
	{ family: 'Oswald', weight: '400' },
	{ family: 'Oswald', weight: '700' },
	{ family: 'Open Sans', weight: '400' },
	{ family: 'Open Sans', weight: '600' }
];

const GERMAN_SAMPLE = 'Aa äöüß';

const ANONYMOUS = { cookies: [], origins: [] };

function recordGoogleFontRequests(context: BrowserContext): string[] {
	const requested: string[] = [];
	context.on('request', (request) => {
		if (GOOGLE_FONT_HOSTS.includes(new URL(request.url()).hostname)) {
			requested.push(request.url());
		}
	});
	return requested;
}

async function loadedFaces(page: Page): Promise<string[]> {
	return page.evaluate(
		async ({ faces, sample }) => {
			await Promise.all(
				faces.map(({ family, weight }) => document.fonts.load(`${weight} 16px "${family}"`, sample))
			);
			return [...document.fonts]
				.filter((face) => face.status === 'loaded')
				.map((face) => `${face.family.replaceAll('"', '')} ${face.weight}`);
		},
		{ faces: SERVED_FACES, sample: GERMAN_SAMPLE }
	);
}

// The font files the installed worker filled its cache with: the worker is
// ready once it has installed, which is when it precaches the build.
async function precachedFontPaths(page: Page): Promise<string[]> {
	await page.goto('/login');
	return page.evaluate(async () => {
		await navigator.serviceWorker.ready;
		const paths: string[] = [];
		for (const name of await caches.keys()) {
			const cache = await caches.open(name);
			for (const request of await cache.keys()) {
				const { pathname } = new URL(request.url);
				if (/\.woff2?$/.test(pathname)) paths.push(pathname);
			}
		}
		return paths;
	});
}

async function expectSelfHostedFonts(page: Page): Promise<void> {
	await expect(page.locator('body')).toHaveCSS('font-family', /^"Open Sans"/);
	const faces = await loadedFaces(page);
	for (const { family, weight } of SERVED_FACES) {
		expect(faces, `${family} ${weight} did not load`).toContain(`${family} ${weight}`);
	}
}

// The font stack is the same stylesheet in both shells, so the desktop alone
// proves it.
test(
	'the login page renders its fonts without asking a Google host',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ browser }) => {
		const context = await browser.newContext({ storageState: ANONYMOUS });
		const googleRequests = recordGoogleFontRequests(context);
		const page = await context.newPage();

		await page.goto('/login');
		await expectSelfHostedFonts(page);

		expect(googleRequests).toEqual([]);
		await context.close();
	}
);

test(
	'a song renders its fonts without asking a Google host',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const library = readSeededLibrary();
		const googleRequests = recordGoogleFontRequests(context);
		const songSlug = library.pickedSongTitle.toLowerCase().replace(/\s+/g, '-');

		await page.goto(`/album/${library.albumId}/${songSlug}`);
		await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
		await expectSelfHostedFonts(page);

		expect(googleRequests).toEqual([]);
	}
);

test(
	'a share page renders its fonts without asking a Google host',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ browser }) => {
		const library = readSeededLibrary();
		const context = await browser.newContext({ storageState: ANONYMOUS });
		const googleRequests = recordGoogleFontRequests(context);
		const page = await context.newPage();

		await page.goto(library.albumShareUrl);
		await expect(page.getByText(library.albumTitle).first()).toBeVisible();
		await expectSelfHostedFonts(page);

		expect(googleRequests).toEqual([]);
		await context.close();
	}
);

test('precached fonts are served as woff2', { tag: ONLY_IN_SHELL.desktop }, async ({ browser }) => {
	// The config blocks the worker; this test is about what it cached, and no stub is set.
	const context = await browser.newContext({ storageState: ANONYMOUS, serviceWorkers: 'allow' });
	const page = await context.newPage();
	const fontPaths = await precachedFontPaths(page);

	expect(fontPaths.length).toBeGreaterThan(0);
	for (const path of fontPaths) expect(path).toMatch(/\.woff2$/);
	const font = await page.request.get(fontPaths[0]);
	expect(font.ok()).toBe(true);
	expect(font.headers()['content-type']).toBe('font/woff2');
	await context.close();
});
