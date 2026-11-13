import { expect, test, type APIRequestContext, type Locator, type Page } from './coverage-test';
import { words } from '../src/lib/words/en';
import {
	NOW_PLAYING_CLOSE,
	NOW_PLAYING_RIGHT_PANEL_LABEL,
	NOW_PLAYING_TAKE_TAB,
	openNowPlayingLabel,
	takeRowLabel
} from '../src/lib/constants/now-playing';
import {
	FlowGuard,
	nameStartingWith,
	ONLY_IN_SHELL,
	playlistEntryRows,
	standsOnLayerEntry,
	workspace
} from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';

// Phone Back/× restores the origin without duplicate history (#1002). A take opens
// a sheet clear of × (#1052); Back closes the sheet first (#1119). Playlists play
// in place (#1010), so open through the mini-player. Imported songs have one take.
const SEEDED_TAKE_NUMBER = 1;

interface NowPlayingOrigin {
	playing: string;
	origin: Locator;
	cameFrom: Locator;
	opensOnTakeSheet: boolean;
}

const NOW_PLAYING_ORIGINS: {
	name: string;
	openFromRow: (page: Page, request: APIRequestContext) => Promise<NowPlayingOrigin>;
}[] = [
	{
		name: 'a playlist opened from the Playlists page',
		openFromRow: async (page, request) => {
			const playlist = await seedPlaylist(request, readSeededLibrary());
			const [playing] = playlist.songTitles;
			await page.goto('/playlists');
			await workspace(page)
				.locator('.library-wall .tile-grid')
				.locator('.wall-tile-body')
				.filter({ hasText: playlist.title })
				.click();
			const origin = workspace(page).getByRole('heading', { name: playlist.title });
			await expect(origin).toBeVisible();
			const playedCard = playlistEntryRows(page).first();
			const playedCardBox = await playedCard.boundingBox();
			if (!playedCardBox) throw new Error('Expected a visible playlist row');
			await playedCard.tap({ position: { x: 4, y: playedCardBox.height - 4 } });
			await expect(page.getByRole('contentinfo').getByText(playing)).toBeVisible();
			await expect(origin).toBeVisible();
			await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeHidden();
			await page
				.getByRole('contentinfo')
				.getByRole('button', { name: openNowPlayingLabel(playing), exact: true })
				.click();
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: words['places.playlists'] }),
				opensOnTakeSheet: false
			};
		}
	},
	{
		name: 'a song opened from its album',
		openFromRow: async (page) => {
			const library = readSeededLibrary();
			const playing = library.pickedSongTitle;
			await page.goto(`/album/${library.albumId}`);
			await workspace(page)
				.getByRole('button', { name: words['songRow.openInEditor']({ title: playing }) })
				.click();
			const origin = page.getByRole('heading', { name: playing });
			await expect(origin).toBeVisible();
			await page.getByRole('tab', { name: words['songTabs.takes'] }).click();
			await page
				.getByRole('tabpanel')
				.getByRole('button', { name: nameStartingWith(takeRowLabel(SEEDED_TAKE_NUMBER)) })
				.click();
			await expect(page.getByRole('tab', { name: NOW_PLAYING_TAKE_TAB })).toBeVisible();
			return {
				playing,
				origin,
				cameFrom: workspace(page).getByRole('heading', { name: library.albumTitle }),
				opensOnTakeSheet: true
			};
		}
	}
];

const NOW_PLAYING_LEAVES: {
	name: string;
	leave: (page: Page, opened: NowPlayingOrigin) => Promise<void>;
}[] = [
	{
		name: 'Back',
		leave: async (page, { playing, opensOnTakeSheet }) => {
			if (opensOnTakeSheet) {
				await page.goBack();
				await expect(
					page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL })
				).toBeHidden();
				await expect(page.getByRole('dialog', { name: playing })).toBeVisible();
			}
			await page.goBack();
		}
	},
	{
		// A reload -- or a phone restoring a tab it discarded -- drops the open
		// Now Playing, and the sheet over it, but not their history entries;
		// once its library has loaded the app steps back off each of them onto
		// an entry no layer marks, and Back is meant from then on.
		name: 'a reload',
		leave: async (page) => {
			await expect.poll(() => standsOnLayerEntry(page)).toBe(true);
			await page.reload();
			await expect.poll(() => standsOnLayerEntry(page)).toBe(false);
		}
	},
	{
		name: '× right after open',
		leave: async (page, { playing, opensOnTakeSheet }) => {
			const takeSheet = page.getByRole('dialog', { name: NOW_PLAYING_RIGHT_PANEL_LABEL });
			if (opensOnTakeSheet) await expect(takeSheet).toBeVisible();
			await page
				.getByRole('dialog', { name: playing })
				.getByRole('button', { name: NOW_PLAYING_CLOSE, exact: true })
				.tap();
		}
	}
];

test.describe('leaving Now Playing at phone width', { tag: ONLY_IN_SHELL.mobile }, () => {
	for (const { name: originName, openFromRow } of NOW_PLAYING_ORIGINS) {
		for (const { name: leaveName, leave } of NOW_PLAYING_LEAVES) {
			test(`${leaveName} from Now Playing shows ${originName} again`, async ({ page, request }) => {
				const guard = new FlowGuard(page);
				const opened = await openFromRow(page, request);
				const { origin, cameFrom } = opened;
				const nowPlaying = page.getByRole('dialog', { name: opened.playing });
				await expect(nowPlaying).toBeVisible();
				const originAddress = page.url();

				await leave(page, opened);

				await expect(nowPlaying).toBeHidden();
				await expect(origin).toBeVisible();
				expect(page.url()).toBe(originAddress);

				await page.goBack();
				await expect(cameFrom).toBeVisible();
				guard.assertClean();
			});
		}
	}
});
