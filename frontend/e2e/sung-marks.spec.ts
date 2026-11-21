// Spec: REQ-PLAYER-03 -- in Now Playing a word sung differently carries a dotted mark whose tap or hover shows one Sung line under its lyric line.
//
// The seeded takes carry no cues, so the song's own responses are rewritten to
// carry word cues built from its lyrics, one word sung as another and one left
// out. The seeded takes carry no version lyrics either, so they take the
// song's. Both shells walk the flow.

import { expect, test, type Page, type Route } from './coverage-test';
import { FlowGuard, shellOf } from './helpers';
import { openNowPlayingFromBar, playCollection } from './now-playing-flow';
import { readSeededLibrary } from './seed';
import { words } from '../src/lib/words/en';

const SECONDS_PER_WORD = 0.5;
const SUNG_AS = 'Seeder';
const LEFT_OUT = 'lyrics';
const REPLACED = 'seeded';

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

test.afterEach(() => {
	guard.assertClean();
});

interface TakeBody {
	version_lyrics: string | null;
	whisper_cues: unknown;
}

interface SongBody {
	title: string;
	lyrics: string;
	generations: TakeBody[];
}

// The lyrics sung word by word, "seeded" as "Seeder" and the last word not at all.
function sungDifferently(lyrics: string): unknown[] {
	const sung = lyrics
		.split(/\s+/)
		.filter((word) => word !== LEFT_OUT)
		.map((word) => (word === REPLACED ? SUNG_AS : word));
	const timed = sung.map((text, index) => ({
		start: index * SECONDS_PER_WORD,
		end: (index + 1) * SECONDS_PER_WORD,
		text
	}));
	return [{ start: 0, end: timed.length * SECONDS_PER_WORD, text: sung.join(' '), words: timed }];
}

async function singDifferently(route: Route, songTitle: string): Promise<void> {
	const response = await route.fetch();
	const body = await response.json();
	const songs: SongBody[] = 'items' in body ? body.items : [body];
	for (const song of songs.filter((candidate) => candidate.title === songTitle)) {
		for (const take of song.generations ?? []) {
			take.version_lyrics = song.lyrics;
			take.whisper_cues = sungDifferently(song.lyrics);
		}
	}
	await route.fulfill({ response, json: body });
}

async function routeSongReads(page: Page, songTitle: string): Promise<void> {
	await page.route(
		(url) => url.pathname === '/api/songs' || /^\/api\/songs\/[^/]+$/.test(url.pathname),
		(route) =>
			route.request().method() === 'GET' ? singDifferently(route, songTitle) : route.continue()
	);
}

test('words sung differently carry marks that show what was sung', async ({ page }, testInfo) => {
	const library = readSeededLibrary();
	const songTitle = library.albumTracks[0].songTitle;
	await routeSongReads(page, songTitle);
	await page.goto(`/album/${library.albumId}`);
	await playCollection(page, 'album');
	await openNowPlayingFromBar(page, testInfo, songTitle);

	const lyrics = page.locator('.lyrics');
	const marks = lyrics.getByRole('button');
	await expect(marks).toHaveText([REPLACED, LEFT_OUT]);
	await expect(marks.first()).not.toHaveCSS('text-decoration-line', /line-through/);

	const reveal = shellOf(testInfo) === 'mobile' ? 'click' : 'hover';
	await marks.first()[reveal]();
	const sung = lyrics.locator('.sung-line');
	await expect(sung).toHaveCount(1);
	await expect(sung).toContainText(words['nowPlaying.sungLine']);
	await expect(sung).toContainText(SUNG_AS);

	await marks.last().click();
	await expect(marks.last()).toHaveAttribute('aria-expanded', 'true');
	await expect(marks.first()).toHaveAttribute('aria-expanded', 'false');
	await expect(sung).toHaveCount(1);
	await expect(page.getByText('Sung vs. lyrics')).toHaveCount(0);
});
