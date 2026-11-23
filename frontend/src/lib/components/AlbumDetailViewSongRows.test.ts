import { tick } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';
import {
	albumList,
	loadSongsForAlbum,
	resetLibraryDataForTests,
	songList
} from '#lib/stores/libraryData.ts';
import { selectedAlbumId } from '#lib/stores/player.ts';
import { toasts } from '#lib/stores/toast.ts';
import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

vi.mock('#lib/api/songs.ts', () => ({ fetchSongs: vi.fn(), moveSong: vi.fn() }));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	renameSong: vi.fn(),
	deleteSong: vi.fn(),
	fetchPlaylists: vi.fn().mockResolvedValue([])
}));
vi.mock('#lib/stores/player.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/player.ts')>()),
	ensureGenerationsLoaded: vi.fn(),
	playAlbum: vi.fn(),
	playAlbumSong: vi.fn()
}));

import { deleteSong, renameSong } from '#lib/api/client.ts';
import { fetchSongs } from '#lib/api/songs.ts';
import AlbumDetailView from './AlbumDetailView.svelte';

const { render: renderDetail, cleanup } = createComponentMount(AlbumDetailView);

function songsWithOneWaitingForPick() {
	return [
		song({ id: 's-picked', album_id: 'a-local', title: 'Picked', track_number: 1, has_pick: true }),
		song({ id: 's-open', album_id: 'a-local', title: 'Open', track_number: 2, has_pick: false }),
		song({
			id: 's-empty',
			album_id: 'a-local',
			title: 'Empty',
			track_number: 3,
			generation_count: 0,
			has_pick: false
		})
	];
}

async function renderLoadedAlbum(): Promise<HTMLElement> {
	const items = songsWithOneWaitingForPick();
	vi.mocked(fetchSongs).mockResolvedValue({
		items,
		total: items.length,
		offset: 0,
		limit: 200,
		has_more: false
	});
	await loadSongsForAlbum('a-local');
	return renderDetail();
}

function rowOf(target: HTMLElement, title: string): HTMLElement {
	const row = [...target.querySelectorAll<HTMLElement>('.song-row')].find((candidate) =>
		candidate.querySelector('.song-row-title')?.textContent?.includes(title)
	);
	if (!row) throw new Error(`no row for ${title}`);
	return row;
}

beforeEach(() => {
	albumList.set([album({ id: 'a-local', title: 'Night Drive', song_count: 3 })]);
	songList.set([]);
	selectedAlbumId.set('a-local');
});

afterEach(async () => {
	await cleanup();
	selectedAlbumId.set(null);
	albumList.set([]);
	resetLibraryDataForTests();
	vi.mocked(renameSong).mockReset();
	vi.mocked(deleteSong).mockReset();
});

describe('AlbumDetailView song rows', () => {
	it('album_rule_11: a song with takes and no Pick carries the No Pick badge, and a song without takes carries none', async () => {
		const target = await renderLoadedAlbum();

		const badge = words['songRow.noPick'];
		expect(rowOf(target, 'Open').querySelector('.song-row-heading')?.textContent).toContain(badge);
		expect(rowOf(target, 'Picked').textContent).not.toContain(badge);
		expect(rowOf(target, 'Empty').textContent).not.toContain(badge);
	});

	it('album_rule_11: the header counts the songs without a Pick once the songs are loaded', async () => {
		const target = await renderLoadedAlbum();

		expect(requireElement(target, '.collection-header .header-count').textContent).toBe(
			`${words['collectionHeader.songCount'](3)} · ${words['collectionHeader.withoutPick']({ count: 1 })}`
		);
	});

	it('album_rule_11: the header counts no missing Picks while the songs still load', async () => {
		songList.set(songsWithOneWaitingForPick());
		const target = await renderDetail();

		expect(requireElement(target, '.collection-header .header-count').textContent).toBe(
			words['collectionHeader.songCount'](3)
		);
	});
});

describe('AlbumDetailView song row menu', () => {
	function rowMenuTrigger(row: HTMLElement): HTMLButtonElement {
		return requireElement<HTMLButtonElement>(row, '.menu-trigger');
	}

	async function openRowMenu(target: HTMLElement, title: string): Promise<HTMLElement> {
		const row = rowOf(target, title);
		rowMenuTrigger(row).click();
		await tick();
		return row;
	}

	it('album_rule_12: every song row carries ⋯ after its ✎', async () => {
		const target = await renderLoadedAlbum();

		for (const row of target.querySelectorAll<HTMLElement>('.song-row')) {
			const controls = [...requireElement(row, '.song-row-controls').children];
			expect(controls[0].classList.contains('song-row-edit')).toBe(true);
			expect(controls[1].querySelector('.menu-trigger')).not.toBeNull();
		}
	});

	it('album_rule_12: ⋯ opens the song menu of that song without Save version', async () => {
		const target = await renderLoadedAlbum();

		const row = await openRowMenu(target, 'Open');

		expect(requireElement(row, '.menu-heading').textContent).toContain('Open');
		expect(menuRowLabels(row)).toEqual([
			words['songMenu.rename'],
			words['songMenu.move'],
			words['songMenu.addTo'],
			words['songMenu.share'],
			words['songMenu.delete']
		]);
	});

	it('album_rule_12: Rename turns the row title into the title field, and Enter saves it', async () => {
		vi.mocked(renameSong).mockResolvedValue(
			song({ id: 's-open', album_id: 'a-local', title: 'Opener' })
		);
		const target = await renderLoadedAlbum();
		const row = await openRowMenu(target, 'Open');

		menuRow(row, words['songMenu.rename']).click();
		await tick();
		const field = requireElement<HTMLInputElement>(row, 'input.editable-title-input');
		expect(field.value).toBe('Open');
		field.value = 'Opener';
		field.dispatchEvent(new Event('input', { bubbles: true }));
		field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		await vi.waitFor(() => expect(row.querySelector('input.editable-title-input')).toBeNull());

		expect(renameSong).toHaveBeenCalledWith('s-open', 'Opener');
		expect(rowOf(target, 'Opener')).toBeDefined();
	});

	it('album_rule_12: Escape leaves the title as it was and the row is a button again', async () => {
		const target = await renderLoadedAlbum();
		const row = await openRowMenu(target, 'Open');
		menuRow(row, words['songMenu.rename']).click();
		await tick();

		requireElement(row, 'input.editable-title-input').dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
		);
		await tick();

		expect(renameSong).not.toHaveBeenCalled();
		expect(row.querySelector('button.song-row-body')).not.toBeNull();
	});

	it('album_rule_12: Delete asks first, then removes the song and offers Undo', async () => {
		vi.mocked(deleteSong).mockResolvedValue(undefined);
		const target = await renderLoadedAlbum();
		const row = await openRowMenu(target, 'Open');

		menuRow(row, words['songMenu.delete']).click();
		await tick();
		expect(deleteSong).not.toHaveBeenCalled();
		const confirm = [...document.body.querySelectorAll('button')].find(
			(button) => button.textContent?.trim() === words['songPage.deleteConfirm']
		);
		confirm?.click();
		await vi.waitFor(() => expect(deleteSong).toHaveBeenCalledWith('s-open'));
		await tick();

		expect(get(songList).map((item) => item.id)).not.toContain('s-open');
		expect(get(toasts).some((toast) => toast.action?.label === words['songPage.undo'])).toBe(true);
	});
});
