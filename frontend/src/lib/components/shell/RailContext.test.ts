import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaylistDetailItem, SongItem } from '$lib/api/types';
import { openCollection } from '$lib/stores/collection';
import { albumList, selectedSongId, songList } from '$lib/stores/player';
import { resetPlaylistsForTests, selectedPlaylistDetail } from '$lib/stores/playlists';

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/client', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchPlaylist: vi.fn()
}));

import RailContext from './RailContext.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function playlistDetail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [],
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RailContext, { target });
	await tick();
	return target;
}

beforeEach(() => {
	resetPlaylistsForTests();
	albumList.set([
		{
			id: 'a1',
			title: 'Nachtstrom',
			artist: 'Artist',
			subtitle: '',
			year: '',
			colors: {},
			song_count: 2,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	songList.set([
		song({ id: 's1', title: 'Tide', track_number: 1 }),
		song({ id: 's2', title: 'Ebb', track_number: 2 })
	]);
	selectedSongId.set(null);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	openCollection.set(null);
	resetPlaylistsForTests();
});

describe('RailContext', () => {
	it('renders nothing when no collection is open', async () => {
		const target = await render();
		expect(target.querySelector('.rail-context')).toBeNull();
	});

	it('shows the open album title and its tracks in order, with the selected track marked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set('s2');
		const target = await render();
		const rows = target.querySelectorAll('.context-row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
		expect(target.querySelector('.context-add')?.textContent).toContain('+ Song');
		const selected = target.querySelector('.context-row.selected .context-row-title');
		expect(selected?.textContent).toBe('Ebb');
	});

	it('shows the open playlist title and its entries', async () => {
		openCollection.set({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			playlistDetail({
				entries: [
					{
						id: 'e1',
						position: 0,
						generation_id: 'g1',
						song_id: 's1',
						song_title: 'First Track',
						album_title: 'Nachtstrom',
						artist: 'Artist',
						generation_number: 1,
						mp3_path: 'g1.mp3',
						seed: 7,
						model_mode: 'turbo',
						lyrics: null
					}
				]
			})
		);
		const target = await render();
		expect(target.textContent).toContain('Night Drive');
		expect(target.textContent).toContain('First Track');
		expect(target.querySelector('.context-add')).toBeNull();
	});
});
