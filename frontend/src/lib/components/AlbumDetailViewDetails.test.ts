// Editing the album's details in place of its title: opening the editor from the
// menu, saving, refusing what the server refuses, and the ways out.

import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { serverRefusal } from '#lib/test-utils/network.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { words } from '#lib/words/en.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import {
	describeBackClosesOverlay,
	standingHistoryEntry
} from '#lib/test-utils/library-history.ts';
import { field, type } from '#lib/test-utils/new-place-card.ts';
import {
	createComponentMount,
	openCollectionMenu,
	requireElement
} from './shell/rail-test-fixtures';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { openCollection } from '#lib/stores/collection.ts';

const updateAlbum = vi.fn();

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return { ...actual, updateAlbum: (...args: unknown[]) => updateAlbum(...args) };
});
vi.mock('#lib/api/songs.ts', () => ({
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbumCoverSuggestions: async () => ({ job: null, suggestions: [] })
}));
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn(),
	addUndoToast: vi.fn(),
	dismissToast: vi.fn()
}));

import AlbumDetailView from './AlbumDetailView.svelte';
import { addToast } from '#lib/stores/toast.ts';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
	songList.set([
		song({ id: 's-local', album_id: 'a-local', album_title: 'Night Drive', generation_count: 1 })
	]);
	selectedAlbumId.set('a-local');
	updateAlbum.mockReset();
	vi.mocked(addToast).mockReset();
});

afterEach(async () => {
	await cleanup();
	selectedAlbumId.set(null);
	albumList.set([]);
	songList.set([]);
	openCollection.set(null);
	resetConnectivityForTests();
	resetLibraryDataForTests();
});

async function openEditDetails(target: HTMLElement): Promise<HTMLFormElement> {
	const menu = await openCollectionMenu(target);
	Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item'))
		.find((item) => item.textContent?.trim() === words['collectionMenu.editDetails'])
		?.click();
	await tick();
	return requireElement<HTMLFormElement>(
		target,
		`form[aria-label="${words['collectionMenu.editDetails']}"]`
	);
}

function detailsForm(target: HTMLElement): HTMLFormElement | null {
	return target.querySelector<HTMLFormElement>(
		`form[aria-label="${words['collectionMenu.editDetails']}"]`
	);
}

async function saveDetails(form: HTMLFormElement): Promise<void> {
	getByRoleButton(form, words['albumDetails.save']).click();
	await tick();
	await tick();
	await tick();
}

describe('AlbumDetailView Edit details', () => {
	beforeEach(() => {
		albumList.set([
			album({ id: 'a-local', title: 'Night Drive', subtitle: 'Live at the Roxy', year: '1994' })
		]);
	});

	it('reads subtitle · year under the title, with no Add subtitle · Add year line', async () => {
		const target = await renderDetail();
		expect(target.querySelector('.header-meta')?.textContent).toBe('Live at the Roxy · 1994');

		albumList.set([album({ id: 'a-local', title: 'Night Drive' })]);
		await tick();

		expect(target.querySelector('.header-meta')).toBeNull();
		expect(target.textContent).not.toContain('Add subtitle');
		expect(target.textContent).not.toContain('Add year');
	});

	it('keeps focus in Title once the menu that opened Edit details has closed', async () => {
		const target = await renderDetail();
		const form = await openEditDetails(target);
		await Promise.resolve();
		await tick();

		expect(document.activeElement).toBe(field(form, words['albumDetails.title']));
	});

	it('saves title, subtitle and year in one update, and the header reads the new details', async () => {
		updateAlbum.mockResolvedValue(
			album({ id: 'a-local', title: 'Nightdrive', subtitle: 'Late-night synthwave', year: '2026' })
		);
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, words['albumDetails.title']), 'Nightdrive');
		type(field(form, words['albumDetails.subtitle']), 'Late-night synthwave');
		type(field(form, words['albumDetails.year']), '2026');
		await saveDetails(form);

		expect(updateAlbum).toHaveBeenCalledWith('a-local', {
			title: 'Nightdrive',
			subtitle: 'Late-night synthwave',
			year: 2026
		});
		await vi.waitFor(() => expect(detailsForm(target)).toBeNull());
		expect(get(albumList)[0].title).toBe('Nightdrive');
		expect(target.querySelector('.header-title')?.textContent?.trim()).toBe('Nightdrive');
		expect(target.querySelector('.header-meta')?.textContent).toBe('Late-night synthwave · 2026');
		expect(addToast).toHaveBeenCalledWith(words['albumDetails.saved'], 'success');
	});

	it('clears the year with an emptied field', async () => {
		updateAlbum.mockResolvedValue(album({ id: 'a-local', title: 'Night Drive' }));
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, words['albumDetails.year']), '');
		await saveDetails(form);

		expect(updateAlbum).toHaveBeenCalledWith('a-local', {
			title: 'Night Drive',
			subtitle: 'Live at the Roxy',
			year: null
		});
	});

	it.each([
		{ year: 'abcd', reason: words['albumPage.yearWhole'] },
		{ year: '1899', reason: words['albumPage.yearRange']({ min: '1900', max: '2100' }) }
	])('refuses the year $year with a readable reason, saving nothing', async ({ year, reason }) => {
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, words['albumDetails.year']), year);
		await saveDetails(form);

		expect(updateAlbum).not.toHaveBeenCalled();
		expect(addToast).toHaveBeenCalledWith(reason, 'error');
		expect(detailsForm(target)).not.toBeNull();
		expect(field(form, words['albumDetails.year']).value).toBe(year);
	});

	it('names the server refusal and keeps the editor open with the draft', async () => {
		updateAlbum.mockRejectedValue(serverRefusal('Title is already taken'));
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, words['albumDetails.title']), 'Taken');
		await saveDetails(form);

		await vi.waitFor(() =>
			expect(addToast).toHaveBeenCalledWith('Title is already taken', 'error')
		);
		expect(detailsForm(target)).not.toBeNull();
		expect(field(form, words['albumDetails.title']).value).toBe('Taken');
		expect(get(albumList)[0].title).toBe('Night Drive');
	});

	it('× closes the editor without saving the draft', async () => {
		const target = await renderDetail();
		const form = await openEditDetails(target);

		type(field(form, words['albumDetails.year']), '2026');
		getByRoleButton(form, words['albumDetails.close']).click();
		await tick();

		expect(detailsForm(target)).toBeNull();
		expect(updateAlbum).not.toHaveBeenCalled();
		expect(target.querySelector('.header-meta')?.textContent).toBe('Live at the Roxy · 1994');
	});

	it('ends editing, its draft unsaved, when another album opens', async () => {
		albumList.update((albums) => [...albums, album({ id: 'a-other', title: 'Other Night' })]);
		const target = await renderDetail();
		await openEditDetails(target);

		selectedAlbumId.set('a-other');
		await tick();

		expect(detailsForm(target)).toBeNull();
		expect(target.querySelector('.header-title')?.textContent?.trim()).toBe('Other Night');
		expect(updateAlbum).not.toHaveBeenCalled();
	});
});

describeBackClosesOverlay({
	name: 'the Edit details editor',
	render: renderDetail,
	open: async (target) => {
		const form = await openEditDetails(target);
		await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('details-editing'));
		type(field(form, words['albumDetails.year']), '2026');
	},
	isShown: (target) => detailsForm(target) !== null,
	afterBack: () => expect(updateAlbum).not.toHaveBeenCalled(),
	closeWays: [
		{
			way: '×',
			close: (target) => getByRoleButton(target, words['albumDetails.close']).click()
		},
		{
			way: 'Escape in a field',
			close: (target) =>
				detailsForm(target)
					?.querySelector('input')
					?.dispatchEvent(
						new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
					)
		},
		{
			way: 'Escape outside the form',
			close: () =>
				document.body.dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
				)
		}
	]
});
