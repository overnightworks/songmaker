// A shared album opens as the player view with its songs (#1443, #1374
// slice 6), signed out, at the desktop and the phone width. The real seeded
// album (three three-second songs) carries the flows that need a real song
// to end; the mocked one (share-album-fixtures.ts) holds a state still and
// is long enough to scroll.

import { mkdirSync } from 'node:fs';
import { expect, test as base, type Locator, type Page } from '@playwright/test';
import { LEGAL_SECTIONS } from '../src/lib/constants/legal';
import {
	NOW_PLAYING_GO_TO_SONG,
	SEEK_PLAYBACK_LABEL,
	SONG_NEXT_LABEL,
	SONG_PREVIOUS_LABEL,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { NOW_PLAYING_PLAY_AGAIN_LABEL } from '../src/lib/constants/now-playing';
import { SHARE_BACK_TO_PLAYER_LABEL, shareNowPlayingLine } from '../src/lib/constants/share';
import {
	boundingBoxes,
	FlowGuard,
	nameStartingWith,
	ONLY_IN_SHELL,
	type ExpectedRefusal
} from './helpers';
import {
	control,
	MOCK_STREAM_REFUSAL,
	openMockSharedAlbum,
	MOCK_ALBUM_TITLE,
	MOCK_UNPLAYABLE_TITLE,
	MOCK_URL,
	mockSharedAlbum,
	mockSongLyrics,
	mockSongs,
	mockSongTitle
} from './share-album-fixtures';
import { readSeededLibrary } from './seed';

const SEEDED_SONG_TITLES = ['Opening Move', 'Second Wind', 'Closing Time'];
const SHORT_WINDOW_HEIGHT_PX = 600;
const LYRICS_BOX_MAX_PX = 300;
const LONG_LYRICS = Array.from({ length: 300 }, (_, line) => `Line ${line + 1}`).join('\n');
const PLAYER_SCROLL_ROOT = '.shared-page';

interface Visitor {
	page: Page;
	guard: FlowGuard;
	expectedRefusals: ExpectedRefusal[];
}

const test = base.extend<{ visitor: Visitor }>({
	visitor: async ({ browser }, use, testInfo) => {
		const { viewport, isMobile, hasTouch } = testInfo.project.use;
		const context = await browser.newContext({
			storageState: undefined,
			viewport,
			isMobile,
			hasTouch
		});
		const page = await context.newPage();
		const expectedRefusals: ExpectedRefusal[] = [];
		const guard = new FlowGuard(page, { refusalsExpectedOn: expectedRefusals });
		try {
			await use({ page, guard, expectedRefusals });
		} finally {
			try {
				guard.assertClean();
			} finally {
				await context.close();
			}
		}
	}
});

function songs(page: Page): Locator {
	return page.locator('.np-page-songs');
}

function songRow(page: Page, title: string): Locator {
	return songs(page).getByRole('button', { name: nameStartingWith(title) });
}

function playingRow(page: Page): Locator {
	return songs(page).locator('.queue-row[aria-current="true"]');
}

async function openMockAlbum(
	{ page, guard, expectedRefusals }: Visitor,
	albumSongs = mockSongs(3)
): Promise<FlowGuard> {
	expectedRefusals.push(MOCK_STREAM_REFUSAL);
	await openMockSharedAlbum(page, albumSongs);
	return guard;
}

async function openSeededAlbum({ page }: Visitor): Promise<void> {
	await page.goto(readSeededLibrary().albumShareUrl);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(readSeededLibrary().albumTitle);
}

async function expectNowPlayingLine(page: Page, title: string, position: number, total: number) {
	await expect(page.locator('.now-playing-line')).toHaveText(
		shareNowPlayingLine(title, position, total)
	);
}

async function expectLyricsOf(page: Page, title: string): Promise<void> {
	await expect(page.locator('.lyrics-heading')).toHaveText(`Lyrics · ${title}`);
}

async function scrollPageTo(page: Page, edge: 'top' | 'bottom'): Promise<void> {
	await page
		.locator(PLAYER_SCROLL_ROOT)
		.evaluate((root, to) => root.scrollTo(0, to === 'top' ? 0 : root.scrollHeight), edge);
}

test.describe('before Play', () => {
	test(
		'1374_rule_11 landscape touch keeps cover left and Play in the first screen',
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ visitor }, testInfo) => {
			const { page } = visitor;
			await page.setViewportSize({ width: 844, height: 390 });
			await openMockAlbum(visitor);
			const [cover, title, songsBox] = await boundingBoxes(
				page.locator('.cover-art'),
				page.getByRole('heading', { level: 1 }),
				songs(page)
			);
			await page.screenshot({ path: testInfo.outputPath('album-landscape-844-390.png') });
			expect(cover.x + cover.width).toBeLessThanOrEqual(title.x);
			await expect(control(page, TRANSPORT_PLAY_LABEL)).toBeInViewport({ ratio: 1 });
			expect(cover.x + cover.width).toBeLessThanOrEqual(songsBox.x);
		}
	);

	for (const height of [900, 600]) {
		test(
			`1374_rule_11 A1 A2 at ${height}: album keeps desktop columns and phone reading order`,
			{ tag: height === 600 ? ONLY_IN_SHELL.desktop : [] },
			async ({ visitor }, testInfo) => {
				if (testInfo.project.name === 'desktop')
					await visitor.page.setViewportSize({ width: 1440, height });
				await openMockAlbum(visitor);
				const { page } = visitor;
				const stackedTop = [
					page.getByRole('heading', { level: 1 }),
					page.locator('.cover-line').first(),
					page.locator('.now-playing-line'),
					control(page, TRANSPORT_PLAY_LABEL),
					page.getByRole('slider', { name: SEEK_PLAYBACK_LABEL }),
					page.locator('.lyrics-heading'),
					songs(page).getByRole('heading', { name: 'Songs' })
				];
				const boxes = await boundingBoxes(...stackedTop);
				const phone = (testInfo.project.use.viewport?.width ?? 0) <= 768;
				for (let index = 1; index < (phone ? boxes.length : 5); index++)
					expect(boxes[index].y).toBeGreaterThan(boxes[index - 1].y);

				const [cover, title] = await boundingBoxes(
					page.locator('.now-playing.page .cover-art'),
					stackedTop[0]
				);
				if (phone) expect(cover.y + cover.height).toBeLessThanOrEqual(title.y);
				else {
					expect(cover.y + cover.height).toBeLessThanOrEqual(title.y);
					expect(cover.x + cover.width).toBeLessThanOrEqual(boxes[5].x);
					expect(boxes[5].x + boxes[5].width).toBeLessThanOrEqual(boxes[6].x);
				}
				const [artwork] = await boundingBoxes(page.locator('.cover-art'));
				expect(artwork.width).toBeGreaterThan(100);
				expect(artwork.height).toBeCloseTo(artwork.width, 0);
				const [lyrics] = await boundingBoxes(page.locator('.np-page-lyrics'));
				if (!phone) expect(lyrics.y + lyrics.height).toBeLessThanOrEqual(height);
				await songRow(page, mockSongTitle(2)).click();
				await expectLyricsOf(page, mockSongTitle(2));
				await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(2)));
				await expect(page.getByRole('heading', { level: 1 })).toHaveText(MOCK_ALBUM_TITLE);
				const directory = process.env.SHARE_PLAYLIST_SCREENSHOTS;
				if (directory) {
					mkdirSync(directory, { recursive: true });
					await scrollPageTo(page, 'top');
					await page.screenshot({
						path: `${directory}/album-${page.viewportSize()?.width ?? 1440}-${page.viewportSize()?.height ?? 900}.png`
					});
				}
			}
		);
	}

	test('1374_rule_2 A3 A5: song 1 stands ready with its lyrics and the one h1 is the album title', async ({
		visitor
	}) => {
		await openMockAlbum(visitor);
		const { page } = visitor;

		await expectLyricsOf(page, mockSongTitle(1));
		await expect(page.locator('.np-page-lyrics')).toContainText(mockSongLyrics(1));
		await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
		await expectNowPlayingLine(page, mockSongTitle(1), 1, 3);
	});

	test('1374_rule_2 A4: Previous song is disabled and Next song enabled', async ({ visitor }) => {
		await openMockAlbum(visitor);

		await expect(control(visitor.page, SONG_PREVIOUS_LABEL)).toBeDisabled();
		await expect(control(visitor.page, SONG_NEXT_LABEL)).toBeEnabled();
	});
});

test('1374_rule_2 A6: song 1 without lyrics shows No lyrics before Play', async ({ visitor }) => {
	const tracks = mockSongs(2);
	tracks[0].lyrics = null;
	await openMockAlbum(visitor, tracks);
	await expect(visitor.page.locator('.lyrics-empty')).toHaveText('No lyrics');
	await expectLyricsOf(visitor.page, mockSongTitle(1));
});

test('1374_rule_5 B5: an unplayable first song is neither listed nor staged', async ({
	visitor
}) => {
	await openMockAlbum(visitor, [
		{ title: MOCK_UNPLAYABLE_TITLE, lyrics: 'Hidden words', playable: false },
		...mockSongs(2)
	]);
	const { page } = visitor;
	await expect(page.getByText(MOCK_UNPLAYABLE_TITLE)).toHaveCount(0);
	await expect(page.getByText('Hidden words')).toHaveCount(0);
	await expect(songs(page).locator('.queue-title')).toHaveText([
		mockSongTitle(1),
		mockSongTitle(2)
	]);
	await expectNowPlayingLine(page, mockSongTitle(1), 1, 2);
	await expectLyricsOf(page, mockSongTitle(1));
	await control(page, TRANSPORT_PLAY_LABEL).click();
	await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(1)));
});

test('1374_rule_2 B6: no playable song shows only the title and no-audio notice', async ({
	visitor
}) => {
	await openMockAlbum(visitor, [
		{ title: MOCK_UNPLAYABLE_TITLE, lyrics: 'Hidden words', playable: false }
	]);
	await expect(visitor.page.getByRole('status')).toHaveText('No audio available yet.');
	await expect(
		visitor.page.locator('.now-playing, .np-page-lyrics, .np-page-songs, .player-bar')
	).toHaveCount(0);
	await expect(visitor.page.getByText(MOCK_UNPLAYABLE_TITLE)).toHaveCount(0);
});

test('1374_rule_14 C3: seeking before the first Play readies song 1 paused', async ({
	visitor
}) => {
	await openMockAlbum(visitor);
	const { page } = visitor;
	const slider = page.getByRole('slider', { name: SEEK_PLAYBACK_LABEL });
	await slider.fill('45');
	await expect(slider).toHaveValue('45');
	await expect(control(page, TRANSPORT_PLAY_LABEL)).toBeVisible();
	await expect(control(page, TRANSPORT_PAUSE_LABEL)).toHaveCount(0);
	await expectNowPlayingLine(page, mockSongTitle(1), 1, 3);
	await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(1)));
});

test('1374_rule_2 endpoint controls: Next is disabled on the last song and Previous on the first', async ({
	visitor
}) => {
	await openMockAlbum(visitor, mockSongs(2));
	const { page } = visitor;
	await expect(control(page, SONG_PREVIOUS_LABEL)).toBeDisabled();
	await control(page, SONG_NEXT_LABEL).click();
	await expect(control(page, SONG_NEXT_LABEL)).toBeDisabled();
	await expect(control(page, SONG_PREVIOUS_LABEL)).toBeEnabled();
	await control(page, SONG_PREVIOUS_LABEL).click();
	await expect(control(page, SONG_PREVIOUS_LABEL)).toBeDisabled();
});

test.describe('songs', () => {
	test('1374_rule_5 B1: rows are numbered 1..N and carry their lengths', async ({ visitor }) => {
		await openMockAlbum(visitor, mockSongs(5));
		const rows = songs(visitor.page).locator('.queue-row');

		await expect(rows).toHaveCount(5);
		await expect(rows.locator('.queue-duration')).toHaveText(Array(5).fill('2:00'));
		await expect(rows.locator('.queue-position')).toHaveText(['1', '2', '3', '4', '5']);
	});

	test('1374_rule_5 B2 B3 B4: a tap on a row plays it, on the playing row pauses it, on row 1 restarts it', async ({
		visitor
	}) => {
		await openMockAlbum(visitor);
		const { page } = visitor;

		await songRow(page, mockSongTitle(2)).click();
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(2)));
		await expectLyricsOf(page, mockSongTitle(2));
		await expectNowPlayingLine(page, mockSongTitle(2), 2, 3);
		await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeVisible();

		await playingRow(page).click();
		await expect(control(page, TRANSPORT_PLAY_LABEL)).toBeVisible();

		await songRow(page, mockSongTitle(1)).click();
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(1)));
		await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeVisible();
		await expectNowPlayingLine(page, mockSongTitle(1), 1, 3);
	});

	test('1374_rule_5 B7: the playing row is marked violet', async ({ visitor }) => {
		await openMockAlbum(visitor);
		const { page } = visitor;
		const violet = await page.evaluate(() => {
			const probe = document.createElement('span');
			probe.style.color = 'var(--primary)';
			document.body.append(probe);
			const color = getComputedStyle(probe).color;
			probe.remove();
			return color;
		});

		await songRow(page, mockSongTitle(2)).click();

		await expect(playingRow(page)).toHaveCSS('border-left-color', violet);
	});
});

test.describe('controls', () => {
	test('1374_rule_2 C1: Next song and Previous song change the song and its lyrics', async ({
		visitor
	}) => {
		await openMockAlbum(visitor);
		const { page } = visitor;
		await control(page, TRANSPORT_PLAY_LABEL).click();

		await control(page, SONG_NEXT_LABEL).click();
		await expectLyricsOf(page, mockSongTitle(2));
		await expectNowPlayingLine(page, mockSongTitle(2), 2, 3);

		await control(page, SONG_PREVIOUS_LABEL).click();
		await expectLyricsOf(page, mockSongTitle(1));
		await expectNowPlayingLine(page, mockSongTitle(1), 1, 3);
	});

	test('1374_rule_2 C2: shuffle keeps the playing song and the mark follows it', async ({
		visitor
	}) => {
		await openMockAlbum(visitor, mockSongs(8));
		const { page } = visitor;
		await songRow(page, mockSongTitle(3)).click();

		await control(page, 'Shuffle').click();

		await expect(control(page, 'Disable shuffle')).toHaveAttribute('aria-pressed', 'true');
		await expectLyricsOf(page, mockSongTitle(3));
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(3)));
	});
});

test.describe('the end', () => {
	test('1374_rule_7 D1 D2: the last song ends on Play again with the slider full, and Play again starts song 1', async ({
		visitor
	}) => {
		await openSeededAlbum(visitor);
		const { page } = visitor;
		const lastSong = SEEDED_SONG_TITLES.at(-1) ?? '';

		await songRow(page, lastSong).click();
		const playAgain = control(page, NOW_PLAYING_PLAY_AGAIN_LABEL);
		await expect(playAgain).toBeVisible();
		const slider = page.getByRole('slider', { name: SEEK_PLAYBACK_LABEL });
		await expect
			.poll(
				async () => Number(await slider.inputValue()) / Number(await slider.getAttribute('max'))
			)
			.toBeGreaterThan(0.95);

		await playAgain.click();
		await expectNowPlayingLine(page, SEEDED_SONG_TITLES[0], 1, SEEDED_SONG_TITLES.length);
		await expect(playAgain).toBeHidden();
	});
});

test.describe('a long album', () => {
	test('1374_rule_14 E1 E2 E4: the 24th song is reachable by scrolling and plays, and song 20 plays while another plays', async ({
		visitor
	}) => {
		await openMockAlbum(visitor, mockSongs(24));
		const { page } = visitor;

		const lastRow = songRow(page, mockSongTitle(24));
		await lastRow.scrollIntoViewIfNeeded();
		await expect(lastRow).toBeInViewport();
		await lastRow.click();
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(24)));
		await expectNowPlayingLine(page, mockSongTitle(24), 24, 24);

		await songRow(page, mockSongTitle(20)).click();
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(20)));
		await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeVisible();
	});

	test('1374_rule_14 E3: long lyrics stay in a bounded box and Songs stays reachable', async ({
		visitor
	}, testInfo) => {
		const albumSongs = mockSongs(3);
		albumSongs[0].lyrics = LONG_LYRICS;
		await openMockAlbum(visitor, albumSongs);
		const { page } = visitor;

		const [lyricsBox] = await boundingBoxes(page.locator('.np-page-lyrics'));
		expect(lyricsBox.height).toBeLessThanOrEqual(
			testInfo.project.name === 'mobile'
				? LYRICS_BOX_MAX_PX
				: (page.viewportSize()?.height ?? LYRICS_BOX_MAX_PX)
		);
		const lastRow = songRow(page, mockSongTitle(3));
		await lastRow.scrollIntoViewIfNeeded();
		await expect(lastRow).toBeInViewport();
	});

	for (const height of [900, 600]) {
		test(
			`1374_rule_11 E5 D3 scrolling at ${height} keeps desktop transport and phone return available`,
			{ tag: height === 600 ? ONLY_IN_SHELL.desktop : [] },
			async ({ visitor }, testInfo) => {
				if (testInfo.project.name === 'desktop')
					await visitor.page.setViewportSize({ width: 1440, height });
				await openMockAlbum(visitor, mockSongs(40));
				const { page } = visitor;
				const bar = page.locator('footer.player-bar');
				await control(page, TRANSPORT_PLAY_LABEL).click();
				await control(page, SONG_NEXT_LABEL).click();
				await expectNowPlayingLine(page, mockSongTitle(2), 2, 40);

				const [transportBox] = await boundingBoxes(control(page, TRANSPORT_PAUSE_LABEL));
				const history = await page.evaluate(() => window.history.length);
				await scrollPageTo(page, 'bottom');
				if (testInfo.project.name === 'desktop') {
					await expect
						.poll(() => page.locator(PLAYER_SCROLL_ROOT).evaluate((root) => root.scrollTop))
						.toBeGreaterThan(transportBox.y + transportBox.height);
					await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeInViewport({ ratio: 1 });
					await expect(bar).toBeHidden();
					return;
				}
				await expect(bar).toBeVisible();
				await page.screenshot({ path: testInfo.outputPath('album-scroll-bar.png') });
				const [barBox, footerBox] = await boundingBoxes(
					bar,
					page.getByRole('link', { name: 'Impressum' })
				);
				expect(footerBox.y + footerBox.height).toBeLessThanOrEqual(barBox.y);

				await bar.getByRole('button', { name: SHARE_BACK_TO_PLAYER_LABEL }).first().click();
				await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeInViewport();
				await expect(bar).toBeHidden();
				expect(await page.evaluate(() => window.history.length)).toBe(history);
			}
		);
	}
});

test.describe('rights and neighbours', () => {
	test('1374_rule_2 F1: the signed-out album carries no edit, source, take or unplayable song', async ({
		visitor
	}) => {
		const albumSongs = [
			...mockSongs(2),
			{ title: MOCK_UNPLAYABLE_TITLE, lyrics: null, playable: false }
		];
		await openMockAlbum(visitor, albumSongs);
		const { page } = visitor;

		await expect(page.getByRole('button', { name: /edit|pencil/i })).toHaveCount(0);
		await expect(page.getByText(NOW_PLAYING_GO_TO_SONG)).toHaveCount(0);
		await expect(page.locator('.queue-take')).toHaveCount(0);
		await expect(page.getByText(/\bTake\b|\bv\d+\b/)).toHaveCount(0);
		await expect(page.getByText(MOCK_UNPLAYABLE_TITLE)).toHaveCount(0);
		await expect(songs(page).locator('.queue-row')).toHaveCount(2);
		const hrefs = await page
			.locator(`${PLAYER_SCROLL_ROOT} a`)
			.evaluateAll((links) => links.map((link) => link.getAttribute('href')));
		expect(hrefs).toEqual(['/', ...LEGAL_SECTIONS.map(({ href }) => href)]);
	});

	test('1374_rule_2 F2: an unshared address still shows its status line', async ({ browser }) => {
		const context = await browser.newContext({ storageState: undefined });
		const page = await context.newPage();
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/shared/no-such-share-1443', statuses: [404] }]
		});

		try {
			await page.goto(`${new URL(MOCK_URL).origin}/share/no-such-share-1443`);
			await expect(page.getByRole('heading', { level: 1 })).toHaveText(/not found/i);
		} finally {
			try {
				guard.assertClean();
			} finally {
				await context.close();
			}
		}
	});
});

test.describe('short windows', () => {
	test('1374_rule_5 G: Songs is reachable in a window 600 px high', async ({
		visitor
	}, testInfo) => {
		await visitor.page.setViewportSize({
			width: testInfo.project.use.viewport?.width ?? 0,
			height: SHORT_WINDOW_HEIGHT_PX
		});
		await openMockAlbum(visitor, mockSongs(6));
		const { page } = visitor;

		const lastRow = songRow(page, mockSongTitle(6));
		await lastRow.scrollIntoViewIfNeeded();
		await expect(lastRow).toBeInViewport();
		await lastRow.click();
		await expect(playingRow(page)).toHaveAccessibleName(nameStartingWith(mockSongTitle(6)));
	});
});

test('1374_rule_16 F6: a shared song scrolled past its transport has no bar or bar padding', async ({
	visitor
}) => {
	const { page } = visitor;
	await mockSharedAlbum(page, mockSongs(1));
	await page.route('**/shared/song/mock-song', (route) =>
		route.fulfill({
			json: {
				title: mockSongTitle(1),
				artist: 'Mock Artist',
				album_title: MOCK_ALBUM_TITLE,
				album_cover: null,
				audio_url: '/shared/mock-album/audio/1',
				audio_duration: 120,
				lyrics: LONG_LYRICS,
				whisper_cues: null
			}
		})
	);
	await page.goto(`${new URL(MOCK_URL).origin}/share/song/mock-song`);
	await control(page, TRANSPORT_PLAY_LABEL).click();
	await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeVisible();
	// The single-song player shrinks to fit; a very short window lets the legal footer
	// scroll its transport completely away without changing the page's content or CSS.
	await page.setViewportSize({ width: page.viewportSize()?.width ?? 1440, height: 80 });
	await scrollPageTo(page, 'bottom');
	await expect(page.locator('.now-playing.page .transport')).not.toBeInViewport();
	await expect(page.locator('footer.player-bar')).toHaveCount(0);
	await expect(page.locator('.shared-page')).not.toHaveClass(/bar-room/);
});
