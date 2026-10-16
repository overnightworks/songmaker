// A shared album opens as the player view with its songs (#1443, #1374
// slice 6), signed out, at the desktop and the phone width. The real seeded
// album (three three-second songs) carries the flows that need a real song
// to end; the mocked one (share-album-fixtures.ts) holds a state still and
// is long enough to scroll.

import { expect, test as base, type Locator, type Page } from '@playwright/test';
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
import { boundingBoxes, FlowGuard, nameStartingWith } from './helpers';
import {
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
		await use({ page, guard: new FlowGuard(page, { refusalsExpectedOn: [MOCK_STREAM_REFUSAL] }) });
		await context.close();
	}
});

const MOCK_STREAM_REFUSAL = { path: '/shared/mock-album/stream', statuses: [404] };

function songs(page: Page): Locator {
	return page.locator('.np-page-songs');
}

function songRow(page: Page, title: string): Locator {
	return songs(page).getByRole('button', { name: nameStartingWith(title) });
}

function playingRow(page: Page): Locator {
	return songs(page).locator('.queue-row[aria-current="true"]');
}

function control(page: Page, name: string): Locator {
	return page.locator('.now-playing.page').getByRole('button', { name, exact: true });
}

async function openMockAlbum(
	{ page, guard }: Visitor,
	albumSongs = mockSongs(3)
): Promise<FlowGuard> {
	await mockSharedAlbum(page, albumSongs);
	await page.goto(MOCK_URL);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(MOCK_ALBUM_TITLE);
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
	test('1374_rule_2 A1 A2: cover, title, line, controls, slider, lyrics, then Songs, the cover beside them wide', async ({
		visitor
	}, testInfo) => {
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
		for (let index = 1; index < boxes.length; index++)
			expect(boxes[index].y).toBeGreaterThan(boxes[index - 1].y);

		const [cover, title] = await boundingBoxes(
			page.locator('.now-playing.page .cover-art'),
			stackedTop[0]
		);
		const phone = (testInfo.project.use.viewport?.width ?? 0) <= 768;
		if (phone) expect(cover.y + cover.height).toBeLessThanOrEqual(title.y);
		else expect(cover.x + cover.width).toBeLessThanOrEqual(title.x);
	});

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
	}) => {
		const albumSongs = mockSongs(3);
		albumSongs[0].lyrics = LONG_LYRICS;
		await openMockAlbum(visitor, albumSongs);
		const { page } = visitor;

		const [lyricsBox] = await boundingBoxes(page.locator('.np-page-lyrics'));
		expect(lyricsBox.height).toBeLessThanOrEqual(LYRICS_BOX_MAX_PX);
		const lastRow = songRow(page, mockSongTitle(3));
		await lastRow.scrollIntoViewIfNeeded();
		await expect(lastRow).toBeInViewport();
	});

	test('1374_rule_16 E5: scrolling the player out of view shows the bar, and a tap on it scrolls back up', async ({
		visitor
	}) => {
		await openMockAlbum(visitor, mockSongs(24));
		const { page } = visitor;
		const bar = page.locator('footer.player-bar');
		await control(page, TRANSPORT_PLAY_LABEL).click();
		await expect(bar).toBeHidden();

		await scrollPageTo(page, 'bottom');
		await expect(bar).toBeVisible();

		await bar.getByRole('button', { name: SHARE_BACK_TO_PLAYER_LABEL }).first().click();
		await expect(control(page, TRANSPORT_PAUSE_LABEL)).toBeInViewport();
		await expect(bar).toBeHidden();
	});
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
		expect(hrefs).toEqual(['/']);
	});

	test('1374_rule_2 F2: an unshared address still shows its status line', async ({ browser }) => {
		const context = await browser.newContext({ storageState: undefined });
		const page = await context.newPage();
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/shared/', statuses: [404] }]
		});

		await page.goto(`${new URL(MOCK_URL).origin}/share/no-such-share-1443`);

		await expect(page.getByRole('heading', { level: 1 })).toHaveText(/not found/i);
		guard.assertClean();
		await context.close();
	});

	test('1374_rule_2 F3: the footer legal links still open', async ({ visitor }) => {
		await openMockAlbum(visitor);
		const { page } = visitor;

		await page.getByRole('button', { name: 'Impressum' }).click();

		await expect(page.getByRole('dialog', { name: 'Legal information' })).toBeVisible();
	});

	test('1374_rule_2 F5: a shared playlist still renders the old header and list', async ({
		visitor
	}) => {
		await visitor.page.goto(readSeededLibrary().playlistShareUrl);

		await expect(visitor.page.locator('.collection-header')).toBeVisible();
		await expect(visitor.page.locator('.track-row').first()).toBeVisible();
		await expect(visitor.page.locator('.now-playing.page')).toHaveCount(0);
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
