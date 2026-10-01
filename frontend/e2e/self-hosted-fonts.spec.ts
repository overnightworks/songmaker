// Songmaker serves its own fonts (issue #1214): no page, logged in or not,
// asks a Google font host for anything, and the two families still render in
// every weight the stylesheet names. Only a real browser shows both -- which
// hosts a page actually contacts, and which faces it actually loaded.

import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { readSeededLibrary } from './seed';

const GOOGLE_FONT_HOSTS: readonly string[] = ['fonts.googleapis.com', 'fonts.gstatic.com'];

const SERVED_FACES: readonly { family: string; weight: string }[] = [
	{ family: 'Oswald', weight: '400' },
	{ family: 'Oswald', weight: '700' },
	{ family: 'Open Sans', weight: '400' },
	{ family: 'Open Sans', weight: '600' }
];

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
	return page.evaluate(async (faces) => {
		await Promise.all(
			faces.map(({ family, weight }) => document.fonts.load(`${weight} 16px "${family}"`, 'Aa'))
		);
		return [...document.fonts]
			.filter((face) => face.status === 'loaded')
			.map((face) => `${face.family.replaceAll('"', '')} ${face.weight}`);
	}, SERVED_FACES);
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
