import { makeGeneration, makeSong, makeVersion } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/api/client', () => ({
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn(),
	fetchSong: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { get } from 'svelte/store';
import { deleteVersion, fetchSong, fetchVersions } from '$lib/api/client';
import { ApiError, NetworkError } from '$lib/api/fetch';
import { loadSongData, setDraftLyrics, versions } from '$lib/stores/editor';
import { closeTopLayer, resetLayersForTests } from '$lib/stores/layers';
import { selectedSongId } from '$lib/stores/player';
import { addToast } from '$lib/stores/toast';
import {
	DIALOG_CANCEL_LABEL,
	VERSION_DELETE_CONFIRM_LABEL,
	VERSION_DELETE_PICK_WARNING,
	VERSIONS_SHEET_LABEL,
	versionDeleteLabel,
	versionDeleteTitle,
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
	selectedSongId.set(SONG.id);
	vi.mocked(fetchVersions).mockResolvedValueOnce(VERSION_ROWS);
	loadSongData(SONG);
	await vi.waitFor(() => expect(get(versions)).toEqual(VERSION_ROWS));
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetLayersForTests();
	vi.mocked(addToast).mockClear();
	vi.mocked(deleteVersion).mockReset();
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

function confirmDialog(): HTMLElement | null {
	return document.querySelector<HTMLElement>('.dialog');
}

function confirmText(): string[] {
	const dialog = confirmDialog();
	if (!dialog) throw new Error('Expected the delete confirm');
	return [
		dialog.querySelector('h3')?.textContent?.trim() ?? '',
		...Array.from(dialog.querySelectorAll('li')).map((item) => item.textContent?.trim() ?? '')
	];
}

function confirmButton(label: string): HTMLButtonElement {
	const button = Array.from(
		confirmDialog()?.querySelectorAll<HTMLButtonElement>('button') ?? []
	).find((el) => el.textContent?.trim() === label);
	if (!button) throw new Error(`Expected the confirm's ${label} button`);
	return button;
}

async function askToDelete(open: HTMLElement, versionNumber: number): Promise<void> {
	const button = open.querySelector<HTMLButtonElement>(
		`button[aria-label="${versionDeleteLabel(versionNumber)}"]`
	);
	if (!button) throw new Error(`Expected the delete on the v${versionNumber} row`);
	button.click();
	await tick();
}

const SONG_WITHOUT_V6 = makeSong({
	...SONG,
	generations: SONG.generations.filter((take) => take.version_number !== 6)
});

describe('VersionsSheet', () => {
	it('names the latest version on the chip, and the draft once it differs', async () => {
		const target = await renderSheet(vi.fn());
		expect(versionChip(target).textContent?.trim()).toBe('v7');
		expect(versionChip(target).getAttribute('aria-label')).toBe(versionsChipAccessibleLabel('v7'));

		setDraftLyrics('an unsaved line');
		await tick();
		expect(versionChip(target).textContent?.trim()).toBe('v7 · draft');
	});

	it('lists every version newest first with its takes, the pick, its day and first sung line, if it has one', async () => {
		const target = await renderSheet(vi.fn());
		await openSheet(target);
		expect(versionRowTexts(target)).toEqual([
			'v7 2 takes current today 14:02 · Headlights cut the rain in two',
			'v6 1 take · ★ picked yesterday 09:30 · Headlights cut the rain in two',
			'v4 no takes 20 Sep · Rain on the window, the city asleep',
			'v3 no takes 18 Sep'
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
			shown: [versionDeleteTitle(6, 1), VERSION_DELETE_PICK_WARNING],
			says: 'names its one take and warns that the album pick is among them'
		},
		{
			versionNumber: 7,
			shown: [versionDeleteTitle(7, 2)],
			says: 'names its takes and warns of no pick'
		},
		{ versionNumber: 4, shown: [versionDeleteTitle(4, 0)], says: 'names no takes' }
	])('the confirm for v$versionNumber $says', async ({ versionNumber, shown }) => {
		const target = await renderSheet(vi.fn());
		const open = await openSheet(target);
		await askToDelete(open, versionNumber);
		expect(confirmText()).toEqual(shown);
	});

	it('Cancel on the confirm deletes nothing and keeps the sheet open', async () => {
		const target = await renderSheet(vi.fn());
		const open = await openSheet(target);
		await askToDelete(open, 6);
		confirmButton(DIALOG_CANCEL_LABEL).click();
		await tick();

		expect(confirmDialog()).toBeNull();
		expect(deleteVersion).not.toHaveBeenCalled();
		expect(sheet(target)).not.toBeNull();
		expect(versionRowTexts(target)).toHaveLength(VERSION_ROWS.length);
	});

	it('deletes the version with its takes once confirmed, and the sheet lists the rest', async () => {
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(SONG_WITHOUT_V6);
		const remaining = VERSION_ROWS.filter((version) => version.id !== 'v6');
		vi.mocked(fetchVersions).mockResolvedValueOnce(remaining);
		const target = await renderSheet(vi.fn());
		const open = await openSheet(target);
		await askToDelete(open, 6);
		confirmButton(VERSION_DELETE_CONFIRM_LABEL).click();

		await vi.waitFor(() => expect(get(versions)).toEqual(remaining));
		await tick();
		expect(deleteVersion).toHaveBeenCalledExactlyOnceWith('v6', true);
		expect(confirmDialog()).toBeNull();
		expect(sheet(target)).not.toBeNull();
		expect(deleteButtons(open)).toEqual([7, 4, 3].map(versionDeleteLabel));
		expect(vi.mocked(addToast).mock.calls).toEqual([['Deleted v6', 'success']]);
	});

	it.each([
		{
			failure: 'with no network answer',
			error: new NetworkError('/api/versions/v6', new TypeError('Failed to fetch')),
			shown: 'Delete failed'
		},
		{
			failure: 'refused by the server',
			error: new ApiError(409, 'A picked take stays', '/api/versions/v6'),
			shown: 'A picked take stays'
		}
	])('says $shown once when the delete fails $failure', async ({ error, shown }) => {
		vi.mocked(deleteVersion).mockRejectedValueOnce(error);
		const target = await renderSheet(vi.fn());
		const open = await openSheet(target);
		await askToDelete(open, 6);
		confirmButton(VERSION_DELETE_CONFIRM_LABEL).click();

		await vi.waitFor(() => expect(vi.mocked(addToast).mock.calls).toEqual([[shown, 'error']]));
		expect(versionRowTexts(target)).toHaveLength(VERSION_ROWS.length);
	});
});
