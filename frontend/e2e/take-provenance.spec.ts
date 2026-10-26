// The provenance link of a take that was made from another take (#1843, rule 10):
// a plain click unfolds the folded version holding the source and writes one
// entry of the song at the take's anchor, so the song stays open and Back and
// Forward step through the jump. Nothing in the seed writes a repaint take, so
// the relation is added to the song's responses; history, the draft, the folds
// and scrolling stay real. A cell that leaves a dirty draft reverts it before
// teardown, because a dirty page raises the browser's unload prompt.

import { expect, test, type Page, type Route } from '@playwright/test';
import {
	DIALOG_CANCEL_LABEL,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_TITLE,
	openNowPlayingLabel,
	TAKE_PROVENANCE_REPAINT_PREFIX
} from '../src/lib/constants';
import { foldedGroupLabel } from '../src/lib/constants/now-playing';
import {
	createAlbum,
	FIRST_VERSION_TAKE_COUNT,
	openTakes,
	readSong,
	SECOND_VERSION_LYRICS,
	seedFoldedSong,
	showTab,
	type FoldedSong
} from './foldedSong';
import { ONLY_IN_SHELL, workspace } from './helpers';
import { archiveOwnedAlbum } from './seed';

const EDITED_LYRICS = 'Lyrics nobody saved';

interface JumpSong extends FoldedSong {
	// The v2 take that reads "Repaint from v1 · take N", and the v1 take it names.
	repaint: string;
	source: string;
}

// A song, or the list of songs: the JSON responses that carry takes. A stream
// never matches, because fetching it would never end.
const SONG_RESPONSES = (url: URL) => /^\/api\/songs(\/[^/]+)?$/.test(url.pathname);

let albumId: string;

test.beforeEach(async ({ page }) => {
	albumId = await createAlbum(page);
});

test.afterEach(async ({ page }) => {
	await archiveOwnedAlbum(page.request, albumId);
});

function withRepaintRelation(
	body: unknown,
	relation: Record<string, unknown>,
	id: string
): unknown {
	if (Array.isArray(body)) return body.map((item) => withRepaintRelation(item, relation, id));
	if (body === null || typeof body !== 'object') return body;
	const entries = Object.entries(body).map(([key, value]) => [
		key,
		withRepaintRelation(value, relation, id)
	]);
	const copy: Record<string, unknown> = Object.fromEntries(entries);
	if (copy.id !== id) return copy;
	const params = (copy.generation_params ?? {}) as Record<string, unknown>;
	return { ...copy, ...relation, generation_params: { ...params, task_type: 'repaint' } };
}

async function seedJumpSong(page: Page, label: string): Promise<JumpSong> {
	const song = await seedFoldedSong(page, albumId, label);
	const [repaint] = song.v2;
	const [source] = song.v1;
	const sourceTake = (await readSong(page, song.songId)).generations.find(
		(take) => take.id === source
	);
	const relation = {
		src_generation_id: source,
		src_generation_number: sourceTake?.generation_number,
		src_generation_version_number: 1
	};
	await page.route(SONG_RESPONSES, async (route: Route) => {
		if (route.request().method() !== 'GET') return route.continue();
		const response = await route.fetch();
		await route.fulfill({
			response,
			json: withRepaintRelation(await response.json(), relation, repaint)
		});
	});
	return { ...song, repaint, source };
}

const folded = (page: Page) =>
	workspace(page).getByRole('button', {
		name: foldedGroupLabel(1, FIRST_VERSION_TAKE_COUNT, 0),
		exact: false
	});
const takeRow = (page: Page, id: string) => workspace(page).locator(`#take-${id}`);
const provenanceLink = (page: Page, song: JumpSong) =>
	takeRow(page, song.repaint).getByRole('link', {
		name: new RegExp(TAKE_PROVENANCE_REPAINT_PREFIX)
	});
const unsavedChangesDialog = (page: Page) =>
	page.getByRole('dialog', { name: EDITOR_UNSAVED_TITLE });
const lyricsField = (page: Page) => page.getByRole('textbox', { name: /^Lyrics/ });
const entriesOf = (page: Page) => page.evaluate(() => history.length);
// Chromium's Navigation API: the index of the entry on screen, which every Back lowers by one.
const historyIndex = (page: Page) =>
	page.evaluate(
		() =>
			(window as unknown as { navigation: { currentEntry: { index: number } } }).navigation
				.currentEntry.index
	);
// Now Playing's own layers: the dialog and its This-take panel.
const NOW_PLAYING_LAYERS = 2;

async function expectOnTheSong(page: Page, song: JumpSong, hash: string): Promise<void> {
	await expect
		.poll(() => {
			const address = new URL(page.url());
			return address.pathname.startsWith(`/album/${song.albumId}/`) ? address.hash : null;
		})
		.toBe(hash);
}

const anchorOf = (id: string) => `#take-${id}`;

async function startDirtyDraft(page: Page): Promise<void> {
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await lyricsField(page).fill(EDITED_LYRICS);
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
}

async function revertDraft(page: Page): Promise<void> {
	await showTab(page, EDITOR_TAB_EDIT_LABEL);
	await lyricsField(page).fill(SECOND_VERSION_LYRICS);
}

test.describe('a link to a take inside a folded version', () => {
	test('J1 a click unfolds the version, scrolls to the take and writes one entry of the song', async ({
		page
	}) => {
		const song = await seedJumpSong(page, 'jump');
		await openTakes(page, song);
		const entries = await entriesOf(page);
		await expect(takeRow(page, song.source)).toHaveCount(0);

		await provenanceLink(page, song).click();

		await expect(folded(page)).toHaveAttribute('aria-expanded', 'true');
		await expect(takeRow(page, song.source)).toBeInViewport();
		await expectOnTheSong(page, song, anchorOf(song.source));
		expect(await entriesOf(page)).toBe(entries + 1);
		await expect(takeRow(page, song.repaint)).toBeVisible();
	});

	test('J2 Enter on the focused link does the same', async ({ page }) => {
		const song = await seedJumpSong(page, 'enter');
		await openTakes(page, song);
		const entries = await entriesOf(page);

		await provenanceLink(page, song).focus();
		await page.keyboard.press('Enter');

		await expect(folded(page)).toHaveAttribute('aria-expanded', 'true');
		await expect(takeRow(page, song.source)).toBeInViewport();
		await expectOnTheSong(page, song, anchorOf(song.source));
		expect(await entriesOf(page)).toBe(entries + 1);
	});

	test('J3 the same link again writes no further entry and scrolls to the take', async ({
		page
	}) => {
		const song = await seedJumpSong(page, 'again');
		await openTakes(page, song);
		await provenanceLink(page, song).click();
		await expect(takeRow(page, song.source)).toBeInViewport();
		const entries = await entriesOf(page);
		await takeRow(page, song.repaint).scrollIntoViewIfNeeded();

		await provenanceLink(page, song).click();

		await expect(takeRow(page, song.source)).toBeInViewport();
		expect(await entriesOf(page)).toBe(entries);
	});

	test('J4 a Ctrl or middle click leaves this tab as it was', async ({ page }) => {
		const song = await seedJumpSong(page, 'modified');
		await openTakes(page, song);
		const entries = await entriesOf(page);
		const address = page.url();

		await provenanceLink(page, song).click({ modifiers: ['ControlOrMeta'] });
		await provenanceLink(page, song).click({ button: 'middle' });

		await expect(folded(page)).toHaveAttribute('aria-expanded', 'false');
		expect(await entriesOf(page)).toBe(entries);
		expect(page.url()).toBe(address);
		for (const other of page.context().pages()) if (other !== page) await other.close();
	});

	test('J6 with an unsaved draft, Back and Forward between the entries of the song ask nothing', async ({
		page
	}) => {
		const song = await seedJumpSong(page, 'draft');
		await openTakes(page, song);
		await startDirtyDraft(page);
		await provenanceLink(page, song).click();
		await expect(takeRow(page, song.source)).toBeInViewport();

		await page.goBack();

		await expect(unsavedChangesDialog(page)).toHaveCount(0);
		await expectOnTheSong(page, song, '');
		await expect(takeRow(page, song.repaint)).toBeVisible();

		await page.goForward();

		await expect(unsavedChangesDialog(page)).toHaveCount(0);
		await expectOnTheSong(page, song, anchorOf(song.source));
		await showTab(page, EDITOR_TAB_EDIT_LABEL);
		await expect(lyricsField(page)).toHaveValue(EDITED_LYRICS);
		await revertDraft(page);
	});

	test('J8 Discard on the Back that leaves the song leaves for the album', async ({ page }) => {
		const song = await seedJumpSong(page, 'discard');
		await openTakes(page, song);
		await startDirtyDraft(page);
		await provenanceLink(page, song).click();
		await expect(takeRow(page, song.source)).toBeInViewport();

		await page.goBack();
		await page.goBack();

		await expect(unsavedChangesDialog(page)).toBeVisible();
		await unsavedChangesDialog(page)
			.getByRole('button', { name: EDITOR_UNSAVED_DISCARD_LABEL, exact: true })
			.click();
		await expect(unsavedChangesDialog(page)).toHaveCount(0);
		await expect.poll(() => new URL(page.url()).pathname).toBe(`/album/${song.albumId}`);
	});

	test('J8 Back off the song asks as ever, and Cancel keeps the song and its draft', async ({
		page
	}) => {
		const song = await seedJumpSong(page, 'leave');
		await openTakes(page, song);
		await startDirtyDraft(page);
		await provenanceLink(page, song).click();
		await expect(takeRow(page, song.source)).toBeInViewport();

		await page.goBack();
		await expect(unsavedChangesDialog(page)).toHaveCount(0);
		await page.goBack();

		await expect(unsavedChangesDialog(page)).toBeVisible();
		await unsavedChangesDialog(page).getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();
		await expect(unsavedChangesDialog(page)).toHaveCount(0);
		await expectOnTheSong(page, song, '');
		await showTab(page, EDITOR_TAB_EDIT_LABEL);
		await expect(lyricsField(page)).toHaveValue(EDITED_LYRICS);
		await revertDraft(page);
	});
});

test.describe(
	'a link to a take on the phone, over Now Playing and the tabs',
	{ tag: ONLY_IN_SHELL.mobile },
	() => {
		test('J7 Back leaves Now Playing, the tab switch rewrites the entry and the next Back asks nothing', async ({
			page
		}) => {
			const song = await seedJumpSong(page, 'phone');
			await openTakes(page, song);
			await takeRow(page, song.repaint).locator('.play-btn').click();
			await startDirtyDraft(page);
			await provenanceLink(page, song).click();
			await expect(takeRow(page, song.source)).toBeInViewport();
			await page
				.getByRole('contentinfo')
				.getByRole('button', { name: new RegExp(`${openNowPlayingLabel('')}$`) })
				.click();
			const nowPlaying = page.getByRole('dialog', { name: song.title });
			await expect(nowPlaying).toBeVisible();

			// Now Playing's inner This-take panel is its topmost layer and takes the
			// first Back; the second Back closes the dialog itself.
			const entryIndex = await historyIndex(page);
			await page.goBack();
			await expect.poll(() => historyIndex(page)).toBe(entryIndex - 1);
			await expect(nowPlaying).toBeVisible();
			await page.goBack();
			await expect.poll(() => historyIndex(page)).toBe(entryIndex - NOW_PLAYING_LAYERS);
			await expect(nowPlaying).toHaveCount(0);
			await expectOnTheSong(page, song, anchorOf(song.source));

			await showTab(page, EDITOR_TAB_EDIT_LABEL);
			await expectOnTheSong(page, song, '');

			await page.goBack();

			await expect(unsavedChangesDialog(page)).toHaveCount(0);
			await expect(takeRow(page, song.repaint)).toBeVisible();

			await page.goForward();

			await expect(unsavedChangesDialog(page)).toHaveCount(0);
			await expect(lyricsField(page)).toHaveValue(EDITED_LYRICS);
			await revertDraft(page);
		});
	}
);
