// The render pass of every further language (design's languages standard, LANG-7): each surface
// opens once per language a browser asks for, at the phone width and at a desktop width, and the
// page names that language, shows no catalog key and no unrendered value, and no text runs out of
// its box. Behaviour stays with the other specs, which run in the source language.

import { expect, test, type Page } from './coverage-test';
import { words, type Key } from '../src/lib/words/en';
import { languages, loadWords, sourceLanguage, type Language } from '../src/lib/words/index';
import { escapeForRegExp, shellOf, workspace } from './helpers';
import { readSeededLibrary, seedPlaylist, type SeededLibrary } from './seed';

/** A desktop width narrower than the desktop project's own, so a longer translation meets less room. */
const RENDER_PASS_DESKTOP_VIEWPORT = { width: 1280, height: 800 };

/** What a page shows while it loads, in the language's own words: the pass reads a page once it has loaded. */
async function stillLoading(language: Language): Promise<RegExp> {
	const loadingTexts = Object.entries(await loadWords(language))
		.filter(
			([key, text]) => /loading/i.test(key) && typeof text === 'string' && /(…|\.\.\.)$/.test(text)
		)
		.map(([, text]) => escapeForRegExp(text as string));
	return new RegExp(`^(${loadingTexts.join('|')})$`);
}

interface Surface {
	name: string;
	/** Opens the surface; the seeded library is read in the test, since listing the tests runs before any seed. */
	open: (page: Page, library: SeededLibrary, language: Language) => Promise<void>;
	/** Opened without a session: the page a person meets before signing in. */
	signedOut?: boolean;
	/** Keys of the framework's own English text the page must show in the language's words instead: the pass finds no English text by itself. */
	says?: Key[];
}

function address(path: (library: SeededLibrary) => string): Surface['open'] {
	return async (page, library) => void (await page.goto(path(library)));
}

async function openSong(page: Page, library: SeededLibrary, language: Language): Promise<void> {
	const text = await loadWords(language);
	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', { name: text['songRow.openInEditor']({ title: library.pickedSongTitle }) })
		.click();
	await expect(page).toHaveURL(new RegExp(`/album/${library.albumId}/[^/]+$`));
}

const surfaces: Surface[] = [
	...['/', '/library', '/playlists'].map((path) => ({ name: path, open: address(() => path) })),
	{ name: 'the album page', open: address((library) => `/album/${library.albumId}`) },
	{ name: 'the song page', open: openSong },
	...[
		'/settings/generation',
		'/settings/voices',
		'/settings/references',
		'/settings/users',
		'/settings/about'
	].map((path) => ({ name: path, open: address(() => path) })),
	{ name: '/settings', open: address(() => '/settings') },
	{
		name: 'the take page',
		open: async (page, library, language) => {
			await openSong(page, library, language);
			await page.goto(`${new URL(page.url()).pathname}/take/1`);
		}
	},
	{
		name: 'Now Playing',
		open: async (page, library, language) => {
			const text = await loadWords(language);
			await page.goto(`/album/${library.albumId}`);
			await page
				.getByRole('button', { name: text['collectionHeader.playAlbum'], exact: true })
				.click();
			const bar = page.getByRole('contentinfo');
			await expect(
				bar.getByRole('button', { name: text['transport.pause'], exact: true })
			).toBeVisible();
			const isPhone = (page.viewportSize()?.width ?? 0) <= 768;
			await bar
				.getByRole('button', {
					name: isPhone
						? text['player.openNowPlaying']({ title: library.albumTracks[0].songTitle })
						: text['transport.nowPlaying'],
					exact: true
				})
				.click();
			// The phone keeps the right panel shut behind a trigger named for the queue tab.
			await expect(
				isPhone
					? page.getByRole('dialog').getByRole('button', {
							name: new RegExp(`${escapeForRegExp(text['nowPlaying.queueTab'])}$`)
						})
					: page.getByRole('tab', { name: text['nowPlaying.takeTab'] })
			).toBeVisible();
		}
	},
	{
		name: 'the opened playlist',
		open: async (page, library) => {
			const playlist = await seedPlaylist(page.request, library);
			await page.goto(`/playlist/${playlist.slug}`);
		}
	},
	{
		name: 'an unknown address',
		open: address(() => '/no-such-page'),
		says: ['routeError.notFound']
	},
	{ name: 'the shared album', open: address((library) => library.albumShareUrl), signedOut: true },
	{ name: 'the shared song', open: address((library) => library.songShareUrl), signedOut: true },
	{ name: 'the shared take', open: address((library) => library.takeShareUrl), signedOut: true },
	{
		name: 'the shared playlist',
		open: address((library) => library.playlistShareUrl),
		signedOut: true
	},
	{ name: '/login', open: address(() => '/login'), signedOut: true },
	{ name: '/no-access', open: address(() => '/no-access'), signedOut: true },
	{
		name: 'the failed sign-in page',
		open: address(() => '/auth/callback?error=access_denied&state=forged'),
		signedOut: true
	}
];

interface RenderFaults {
	keys: string[];
	unrendered: string[];
	overflowing: string[];
}

/** Every catalog key shown as text or in a human-readable attribute, every unrendered value, and every text element wider than its box. */
function renderFaults(keys: string[]): RenderFaults {
	const readable = (element: Element) =>
		[
			...Array.from(element.childNodes)
				.filter((node) => node.nodeType === Node.TEXT_NODE)
				.map((node) => node.textContent ?? ''),
			...['aria-label', 'title', 'placeholder', 'alt'].map(
				(name) => element.getAttribute(name) ?? ''
			)
		]
			.join(' ')
			.trim();
	const describe = (element: Element) =>
		`<${element.localName}> "${readable(element).slice(0, 60)}"`;
	const shown = Array.from(document.body.querySelectorAll('*')).filter(
		(element) =>
			element.getClientRects().length > 0 &&
			getComputedStyle(element).visibility !== 'hidden' &&
			readable(element) !== ''
	);
	const keySet = new Set(keys);
	const faults: RenderFaults = { keys: [], unrendered: [], overflowing: [] };
	for (const element of shown) {
		const text = readable(element);
		for (const token of text.split(/[\s"“”„',:;()]+/)) {
			if (keySet.has(token)) faults.keys.push(`${token} in ${describe(element)}`);
		}
		if (/\[object \w+\]|=>|function\s*\(/.test(text)) faults.unrendered.push(describe(element));
		const style = getComputedStyle(element);
		const scrollsByDesign = ['auto', 'scroll'].includes(style.overflowX);
		const truncatesByDesign = style.textOverflow === 'ellipsis';
		// A container whose child hangs out by design (the rail's resize handle) is no text that runs out.
		const holdsText = Array.from(element.childNodes).some(
			(node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim() !== ''
		);
		if (
			holdsText &&
			!scrollsByDesign &&
			!truncatesByDesign &&
			element.clientWidth > 1 &&
			element.scrollWidth > element.clientWidth + 1
		) {
			faults.overflowing.push(
				`${describe(element)} ${element.scrollWidth}px in ${element.clientWidth}px`
			);
		}
	}
	return faults;
}

for (const language of languages.filter((offered) => offered !== sourceLanguage)) {
	test.describe(`the interface in ${language}`, () => {
		test.use({ locale: language });

		test.beforeEach(async ({ page }, testInfo) => {
			if (shellOf(testInfo) === 'desktop') await page.setViewportSize(RENDER_PASS_DESKTOP_VIEWPORT);
		});

		for (const surface of surfaces) {
			test.describe(surface.name, () => {
				if (surface.signedOut) test.use({ storageState: { cookies: [], origins: [] } });

				test(`renders whole in ${language}`, async ({ page }) => {
					await surface.open(page, readSeededLibrary(), language);

					await expect(page.locator('html')).toHaveAttribute('lang', language);
					await expect(page.getByText(await stillLoading(language))).toHaveCount(0);
					const text = await loadWords(language);
					for (const key of surface.says ?? []) {
						await expect(page.getByText(text[key] as string, { exact: true })).toBeVisible();
					}
					await expect
						.poll(() => page.evaluate(renderFaults, Object.keys(words)))
						.toEqual({
							keys: [],
							unrendered: [],
							overflowing: []
						});
				});
			});
		}
	});
}
