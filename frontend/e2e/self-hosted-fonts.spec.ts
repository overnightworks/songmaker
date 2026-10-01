// Songmaker serves its own fonts (issue #1214): no page, logged in or not,
// asks a Google font host for anything, and the two families still render in
// every weight the stylesheet names. Only a real browser shows both -- which
// hosts a page actually contacts, and which faces it actually loaded.
// Only the latin and latin-ext subsets ship, in woff2 alone (issue #1224).

import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { readSeededLibrary } from './seed';

const GOOGLE_FONT_HOSTS: readonly string[] = ['fonts.googleapis.com', 'fonts.gstatic.com'];

const SERVED_FACES: readonly { family: string; weight: string }[] = [
	{ family: 'Oswald', weight: '400' },
	{ family: 'Oswald', weight: '700' },
	{ family: 'Open Sans', weight: '400' },
	{ family: 'Open Sans', weight: '600' }
];

const SHIPPED_SUBSETS: readonly string[] = ['latin', 'latin-ext'];

const SHIPPED_FONT_FILE_COUNT = SERVED_FACES.length * SHIPPED_SUBSETS.length;

const SHIPPED_FONT_FILE = new RegExp(
	`^(oswald|open-sans)-(${SHIPPED_SUBSETS.join('|')})-\\d{3}-normal\\.[\\w-]+\\.woff2$`
);

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

async function precachedFontPaths(page: Page): Promise<string[]> {
	const response = await page.request.get('/service-worker.js');
	expect(response.ok()).toBe(true);
	return [...(await response.text()).matchAll(/\/_app\/immutable\/[^"'`,\s]+\.woff2?/g)].map(
		([path]) => path
	);
}

async function expectSelfHostedFonts(page: Page): Promise<void> {
	await expect(page.locator('body')).toHaveCSS('font-family', /^"Open Sans"/);
	const faces = await loadedFaces(page);
	for (const { family, weight } of SERVED_FACES) {
		expect(faces, `${family} ${weight} did not load`).toContain(`${family} ${weight}`);
	}
}

// The font stack is the same stylesheet in both shells; one shell proves it.
test.skip(({ isMobile }) => Boolean(isMobile), 'Fonts are shell-independent');

test('the login page renders its fonts without asking a Google host', async ({ browser }) => {
	const context = await browser.newContext({ storageState: ANONYMOUS });
	const googleRequests = recordGoogleFontRequests(context);
	const page = await context.newPage();

	await page.goto('/login');
	await expectSelfHostedFonts(page);

	expect(googleRequests).toEqual([]);
	await context.close();
});

test('a song renders its fonts without asking a Google host', async ({ page, context }) => {
	const library = readSeededLibrary();
	const googleRequests = recordGoogleFontRequests(context);
	const songSlug = library.pickedSongTitle.toLowerCase().replace(/\s+/g, '-');

	await page.goto(`/album/${library.albumId}/${songSlug}`);
	await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await expectSelfHostedFonts(page);

	expect(googleRequests).toEqual([]);
});

test('a share page renders its fonts without asking a Google host', async ({ browser }) => {
	const library = readSeededLibrary();
	const context = await browser.newContext({ storageState: ANONYMOUS });
	const googleRequests = recordGoogleFontRequests(context);
	const page = await context.newPage();

	await page.goto(library.albumShareUrl);
	await expect(page.getByText(library.albumTitle).first()).toBeVisible();
	await expectSelfHostedFonts(page);

	expect(googleRequests).toEqual([]);
	await context.close();
});

test('only latin and latin-ext woff2 fonts are precached and served as woff2', async ({ page }) => {
	const fontPaths = await precachedFontPaths(page);

	expect(fontPaths).toHaveLength(SHIPPED_FONT_FILE_COUNT);
	for (const path of fontPaths) {
		expect(path.split('/').pop()).toMatch(SHIPPED_FONT_FILE);
	}

	const font = await page.request.get(fontPaths[0]);
	expect(font.ok()).toBe(true);
	expect(font.headers()['content-type']).toBe('font/woff2');
});
