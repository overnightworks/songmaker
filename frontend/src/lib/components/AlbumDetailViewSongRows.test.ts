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
import { createComponentMount, requireElement } from './shell/rail-test-fixtures';

vi.mock('#lib/api/songs.ts', () => ({ fetchSongs: vi.fn() }));
vi.mock('#lib/stores/player.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/player.ts')>()),
	ensureGenerationsLoaded: vi.fn(),
	playAlbum: vi.fn(),
	playAlbumSong: vi.fn()
}));

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
