// The song every takes-folding spec starts from: v1 holds three takes and v2,
// saved over it, two, so v2 is the current version and v1 stands folded. The
// provenance spec (#1843, rule 10) shares it with take-folds.spec.ts.

import { expect, type Page } from '@playwright/test';
import type { SongItem } from '../src/lib/api/types';
import { EDITOR_TAB_TAKES_LABEL, songEditorOpenLabel } from '../src/lib/constants';
import { sameOriginHeaders, nameStartingWith, workspace } from './helpers';
import {
	completeGenerationJobWithoutEvent,
	seedRunningGenerationJob,
	seedSongPhoneSong
} from './seed';

export const FIRST_VERSION_TAKE_COUNT = 3;
export const SECOND_VERSION_TAKE_COUNT = 2;
export const SECOND_VERSION_LYRICS = 'Second version lyrics';
export interface FoldedSong {
	albumId: string;
	songId: string;
	title: string;
	// Take ids, by the version they sit on.
	v1: string[];
	v2: string[];
}

export async function readSong(page: Page, songId: string): Promise<SongItem> {
	const response = await page.request.get(`/api/songs/${songId}`);
	expect(response.ok()).toBe(true);
	return (await response.json()) as SongItem;
}

export async function createAlbum(page: Page): Promise<string> {
	const album = await page.request.post('/api/albums', {
		headers: await sameOriginHeaders(page),
		data: { title: `E2E Take folds ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	return ((await album.json()) as { id: string }).id;
}

export async function seedFoldedSong(
	page: Page,
	albumId: string,
	label: string
): Promise<FoldedSong> {
	const title = `Folds ${label} ${Date.now()}`;
	const songId = await seedSongPhoneSong(albumId, title, 1, FIRST_VERSION_TAKE_COUNT);
	const saved = await page.request.put(`/api/songs/${songId}`, {
		headers: await sameOriginHeaders(page),
		data: { lyrics: SECOND_VERSION_LYRICS }
	});
	expect(saved.ok()).toBe(true);
	const jobId = await seedRunningGenerationJob(songId, {
		progress: 0.5,
		takeIndex: 1,
		takeCount: SECOND_VERSION_TAKE_COUNT,
		phase: 'loading_model'
	});
	await completeGenerationJobWithoutEvent(jobId);
	const { generations } = await readSong(page, songId);
	const idsOf = (version: number) =>
		generations.filter((take) => take.version_number === version).map((take) => take.id);
	expect(idsOf(1)).toHaveLength(FIRST_VERSION_TAKE_COUNT);
	expect(idsOf(2)).toHaveLength(SECOND_VERSION_TAKE_COUNT);
	return { albumId, songId, title, v1: idsOf(1), v2: idsOf(2) };
}

export async function openTakes(page: Page, song: FoldedSong): Promise<void> {
	await page.goto(`/album/${song.albumId}`);
	await workspace(page)
		.getByRole('button', { name: songEditorOpenLabel(song.title) })
		.click();
	await showTab(page, EDITOR_TAB_TAKES_LABEL);
	await expect(workspace(page).locator('.take-row')).toHaveCount(SECOND_VERSION_TAKE_COUNT);
}

// The phone has the tabs, the desktop shows both columns at once.
export async function showTab(page: Page, label: string): Promise<void> {
	const tab = page.getByRole('tab', { name: nameStartingWith(label) });
	if (await tab.isVisible()) await tab.click();
}
