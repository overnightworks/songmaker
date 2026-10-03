import { makeGeneration, makeSong, makeVersion } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));

import { get } from 'svelte/store';
import { fetchVersions } from '$lib/api/client';
import { loadSongData, setDraftLyrics, versionDeleteRequest, versions } from '$lib/stores/editor';
import { closeTopLayer, resetLayersForTests } from '$lib/stores/layers';
import {
	VERSIONS_SHEET_LABEL,
	versionDeleteLabel,
	versionsChipAccessibleLabel
} from '$lib/constants';
import VersionsSheet from './VersionsSheet.svelte';

const NOW = new Date(2026, 9, 2, 15, 0);
const VERSION_ROWS = [
	makeVersion({
		id: 'v7',
		version_number: 7,
		lyrics: '[Verse 1]\nHeadlights cut the rain in two',
		created_at: new Date(2026, 9, 2, 14, 2).toISOString()
	}),
	makeVersion({
		id: 'v6',
		version_number: 6,
		lyrics: 'Headlights cut the rain in two',
		created_at: new Date(2026, 9, 1, 9, 30).toISOString()
	}),
	makeVersion({
		id: 'v4',
		version_number: 4,
		lyrics: '\n[Intro]\n\nRain on the window, the city asleep',
		created_at: new Date(2026, 8, 20, 8, 0).toISOString()
	}),
	makeVersion({
		id: 'v3',
		version_number: 3,
		lyrics: '[Chorus]\n',
		created_at: new Date(2026, 8, 18, 8, 0).toISOString()
	})
];
const SONG = makeSong({
	id: 's1',
	lyrics: 'Headlights cut the rain in two',
	generations: [
		makeGeneration({ id: 'g1', version_id: 'v7', version_number: 7 }),
		makeGeneration({ id: 'g2', version_id: 'v7', version_number: 7 }),
		makeGeneration({ id: 'g3', version_id: 'v6', version_number: 6, is_picked: true }),
		makeGeneration({ id: 'g4', version_id: null, version_number: null })
	]
});

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(async () => {
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(NOW);
	vi.mocked(fetchVersions).mockResolvedValueOnce(VERSION_ROWS);
	loadSongData(SONG);
	await vi.waitFor(() => expect(get(versions)).toEqual(VERSION_ROWS));
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetLayersForTests();
	versionDeleteRequest.set(null);
	vi.useRealTimers();
});

async function renderSheet(onload: (versionId: string) => Promise<boolean>): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(VersionsSheet, { target, props: { song: SONG, onload } }));
	await tick();
	return target;
}

function versionChip(target: HTMLElement): HTMLButtonElement {
	const button = target.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]');
	if (!button) throw new Error('Expected the version chip');
	return button;
}

function sheet(target: HTMLElement): HTMLElement | null {
	return target.querySelector<HTMLElement>(`[role="dialog"][aria-label="${VERSIONS_SHEET_LABEL}"]`);
}

function versionRowTexts(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.version-row')).map((row) =>
		(row.textContent ?? '').replace(/\s+/g, ' ').trim()
	);
}

async function openSheet(target: HTMLElement): Promise<HTMLElement> {
	versionChip(target).click();
	await tick();
	await tick();
	const open = sheet(target);
	if (!open) throw new Error('Expected the versions sheet');
	return open;
}

function clickRow(target: HTMLElement, versionNumber: number): void {
	const row = Array.from(target.querySelectorAll<HTMLButtonElement>('.version-row')).find((el) =>
		el.textContent?.trim().startsWith(`v${versionNumber}`)
	);
	if (!row) throw new Error(`Expected the v${versionNumber} row`);
	row.click();
}

function deleteButtons(open: HTMLElement): string[] {
	return Array.from(open.querySelectorAll('button'))
		.map((button) => button.getAttribute('aria-label') ?? button.textContent ?? '')
		.filter((name) => /delete/i.test(name));
}

async function askToDelete(open: HTMLElement, versionNumber: number): Promise<void> {
	const button = open.querySelector<HTMLButtonElement>(
		`button[aria-label="${versionDeleteLabel(versionNumber)}"]`
	);
	if (!button) throw new Error(`Expected the delete on the v${versionNumber} row`);
	button.click();
	await tick();
}

describe('VersionsSheet', () => {
	it('names the latest version on the chip, and the draft once it differs', async () => {
		const target = await renderSheet(vi.fn());
		expect(versionChip(target).textContent?.trim()).toBe('v7');
		expect(versionChip(target).getAttribute('aria-label')).toBe(versionsChipAccessibleLabel('v7'));

		setDraftLyrics('an unsaved line');
		await tick();
		expect(versionChip(target).textContent?.trim()).toBe('v7 · draft');
	});

	it('lists every version newest first with its takes, the pick, its day and first sung line, or that it has no lyrics', async () => {
		const target = await renderSheet(vi.fn());
		await openSheet(target);
		expect(versionRowTexts(target)).toEqual([
			'v7 2 takes current today 14:02 · Headlights cut the rain in two',
			'v6 1 take · ★ picked yesterday 09:30 · Headlights cut the rain in two',
			'v4 no takes 20 Sep · Rain on the window, the city asleep',
			'v3 no takes 18 Sep · No lyrics'
		]);
	});

	it('loads the tapped version and closes once it has loaded', async () => {
		const onload = vi.fn().mockResolvedValue(true);
		const target = await renderSheet(onload);
		await openSheet(target);
		clickRow(target, 4);
		await vi.waitFor(() => expect(sheet(target)).toBeNull());
		expect(onload).toHaveBeenCalledWith('v4');
	});

	it('stays open when the load was turned down', async () => {
		const onload = vi.fn().mockResolvedValue(false);
		const target = await renderSheet(onload);
		await openSheet(target);
		clickRow(target, 6);
		await Promise.resolve();
		await tick();
		expect(onload).toHaveBeenCalledWith('v6');
		expect(sheet(target)).not.toBeNull();
	});

	it('is a layer Back closes', async () => {
		const target = await renderSheet(vi.fn());
		await openSheet(target);
		expect(closeTopLayer()).toBe(true);
		await tick();
		expect(sheet(target)).toBeNull();
		expect(versionChip(target).getAttribute('aria-expanded')).toBe('false');
	});

	it('offers a delete on every row, the current one included', async () => {
		const target = await renderSheet(vi.fn());
		const open = await openSheet(target);
		expect(deleteButtons(open)).toEqual([7, 6, 4, 3].map(versionDeleteLabel));
	});

	it.each([
		{
			versionNumber: 6,
			takeCount: 1,
			holdsPick: true,
			editorLoss: null,
			takes: 'its one take with the album pick'
		},
		{
			versionNumber: 7,
			takeCount: 2,
			holdsPick: false,
			editorLoss: { kind: 'current-lyrics', replacedBy: 6 },
			takes: 'its two takes and the lyrics in the editor'
		},
		{ versionNumber: 4, takeCount: 0, holdsPick: false, editorLoss: null, takes: 'no takes' }
	])(
		'the delete on v$versionNumber asks to delete it with $takes, loading nothing',
		async ({ versionNumber, takeCount, holdsPick, editorLoss }) => {
			const onload = vi.fn();
			const target = await renderSheet(onload);
			const open = await openSheet(target);
			await askToDelete(open, versionNumber);

			expect(get(versionDeleteRequest)).toEqual({
				songId: SONG.id,
				version: VERSION_ROWS.find((version) => version.version_number === versionNumber),
				takeCount,
				holdsPick,
				editorLoss
			});
			expect(onload).not.toHaveBeenCalled();
			expect(sheet(target)).not.toBeNull();
		}
	);
});
