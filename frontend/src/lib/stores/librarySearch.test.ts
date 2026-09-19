import {
	makeAlbum as album,
	makeSong as song,
	makeSongSummary as searchSong
} from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedSongId } from '$lib/stores/player';

const searchLibrary = vi.fn();
const fetchAlbums = vi.fn();
const fetchSongs = vi.fn();

vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('$lib/api/songs', () => ({
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));

import {
	applySyncedSong,
	forgetSyncedSong,
	librarySearch,
	searchQuery,
	libraryBrowse,
	listLoadedSongIds,
	watchLoadedSongIds,
	loadLibraryBrowse,
	resetLibrarySearchForTests,
	restoreLibraryBrowse,
	restoreLibrarySearch
} from './librarySearch';

beforeEach(() => {
	vi.useFakeTimers();
	searchLibrary.mockReset();
	fetchAlbums.mockReset();
	fetchSongs.mockReset();
	resetLibrarySearchForTests();
	searchQuery.set('');
	selectedSongId.set(null);
	albumList.set([album({ id: 'a-local', title: 'Local Album' })]);
	songList.set([song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0 })]);
});

afterEach(() => {
	vi.useRealTimers();
	selectedSongId.set(null);
	resetLibrarySearchForTests();
});

describe('restoreLibrarySearch', () => {
	it('restoreLibrarySearch replays pages until the saved count is loaded', async () => {
		searchLibrary
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album() }],
				next_cursor: 'cursor-1',
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album({ id: 'a2', title: 'Catalog 2' }) }],
				next_cursor: null,
				has_more: false
			});
		await restoreLibrarySearch('Catalog', 'newest', 2);
		expect(searchLibrary).toHaveBeenCalledTimes(2);
		expect(get(librarySearch).items).toHaveLength(2);
	});
});

describe('restoreLibraryBrowse', () => {
	it('replays pages until the saved offsets are loaded', async () => {
		fetchAlbums
			.mockResolvedValueOnce({
				items: [album()],
				total: 2,
				offset: 0,
				limit: 50,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [album({ id: 'a2', title: 'Second' })],
				total: 2,
				offset: 1,
				limit: 50,
				has_more: false
			});
		fetchSongs
			.mockResolvedValueOnce({
				items: [song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0 })],
				total: 1,
				offset: 0,
				limit: 200,
				has_more: false
			})
			.mockResolvedValueOnce({
				items: [],
				total: 1,
				offset: 1,
				limit: 200,
				has_more: false
			});
		await restoreLibraryBrowse('newest', 2, 1);
		expect(fetchAlbums).toHaveBeenCalledTimes(2);
		expect(get(libraryBrowse).albumOffset).toBe(2);
		expect(get(albumList).map((item) => item.id)).toEqual(['a1', 'a2']);
	});

	it('stops paging a resource once it is exhausted even if the other target remains', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		fetchSongs
			.mockResolvedValueOnce({
				items: [song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0 })],
				total: 1,
				offset: 0,
				limit: 200,
				has_more: false
			})
			.mockResolvedValueOnce({
				items: [],
				total: 1,
				offset: 1,
				limit: 200,
				has_more: false
			});
		await restoreLibraryBrowse('newest', 50, 1);
		expect(fetchAlbums).toHaveBeenCalledTimes(1);
		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});
});

describe('loadLibraryBrowse', () => {
	it('does not let a superseded browse response replace the later page', async () => {
		let resolveFirstAlbums:
			((value: { items: AlbumItem[]; has_more: boolean }) => void) | undefined;
		let resolveFirstSongs: ((value: { items: SongItem[]; has_more: boolean }) => void) | undefined;
		fetchAlbums
			.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						resolveFirstAlbums = resolve;
					})
			)
			.mockResolvedValueOnce({
				items: [album({ id: 'new-album' })],
				has_more: false
			});
		fetchSongs
			.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						resolveFirstSongs = resolve;
					})
			)
			.mockResolvedValueOnce({
				items: [
					song({
						album_id: 'a-local',
						album_title: 'Local Album',
						generation_count: 0,
						id: 'new-song'
					})
				],
				has_more: false
			});

		const first = loadLibraryBrowse({ reset: true });
		await loadLibraryBrowse({ reset: true });
		resolveFirstAlbums?.({
			items: [album({ id: 'old-album' })],
			has_more: false
		});
		resolveFirstSongs?.({
			items: [
				song({
					album_id: 'a-local',
					album_title: 'Local Album',
					generation_count: 0,
					id: 'old-song'
				})
			],
			has_more: false
		});

		expect(await first).toBe(false);
		expect(get(albumList).map((item) => item.id)).toEqual(['new-album']);
		expect(get(songList).map((item) => item.id)).toEqual(['new-song']);
	});

	it('keeps browse offsets independent of songs appended from search', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album({ id: 'a-page' })],
			total: 2,
			offset: 0,
			limit: 50,
			has_more: true
		});
		fetchSongs.mockResolvedValue({
			items: [
				song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0, id: 's-page' })
			],
			total: 2,
			offset: 0,
			limit: 200,
			has_more: true
		});
		await loadLibraryBrowse({ reset: true });
		expect(get(libraryBrowse).songOffset).toBe(1);

		songList.update((songs) => [
			...songs,
			song({
				album_id: 'a-local',
				album_title: 'Local Album',
				generation_count: 0,
				id: 's-search-only'
			})
		]);
		fetchAlbums.mockResolvedValue({
			items: [],
			total: 2,
			offset: 1,
			limit: 50,
			has_more: false
		});
		fetchSongs.mockResolvedValue({
			items: [
				song({
					album_id: 'a-local',
					album_title: 'Local Album',
					generation_count: 0,
					id: 's-page-2'
				})
			],
			total: 2,
			offset: 1,
			limit: 200,
			has_more: false
		});
		await loadLibraryBrowse({ reset: false });
		expect(fetchSongs).toHaveBeenLastCalledWith(undefined, 1, expect.any(Number), {
			sort: 'newest'
		});
		expect(get(libraryBrowse).songOffset).toBe(2);
	});

	it('keeps loaded generations when browse resets over a summary page', async () => {
		songList.set([
			song({
				album_id: 'a-local',
				album_title: 'Local Album',
				id: 's-page',
				generation_count: 1,
				generations: [
					{
						id: 'g1',
						song_id: 's-page',
						version_id: 'v1',
						version_number: 1,
						generation_number: 1,
						mp3_path: 'g1.mp3',
						wav_path: null,
						seed: 1,
						status: 'completed',
						is_archived: false,
						is_picked: false,
						is_kept: false,
						is_shared: false,
						share_slug: null,
						model_mode: 'sft',
						whisper_text: null,
						whisper_cues: null,
						version_lyrics: null,
						scores: null,
						generation_params: null,
						audio_duration_sec: null,
						created_at: '2026-01-01T00:00:00+00:00'
					}
				]
			})
		]);
		fetchAlbums.mockResolvedValue({
			items: [album()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		fetchSongs.mockResolvedValue({
			items: [
				song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0, id: 's-page' })
			],
			total: 1,
			offset: 0,
			limit: 200,
			has_more: false
		});
		await loadLibraryBrowse({ reset: true });
		expect(get(songList)[0].generations.map((item) => item.id)).toEqual(['g1']);
		expect(get(songList)[0].generation_count).toBe(1);
	});
});

describe('applySyncedSong', () => {
	it('updates selected and listed browse songs and loaded search hits', () => {
		const listed = song({
			album_id: 'a-local',
			album_title: 'Local Album',
			generation_count: 0,
			title: 'Listed'
		});
		const searchHit = searchSong({
			slug: 'local-only',
			album_id: 'a-local',
			album_title: 'Local Album',
			bpm: 120,
			audio_duration: 180,
			key_scale: 'Am',
			generation_params: null,
			generation_count: 0,
			share_slug: null,
			best_scores: null,
			best_rating: null,
			cover: null,
			id: 's-search',
			title: 'Search'
		});
		songList.set([listed]);
		selectedSongId.set('s1');
		librarySearch.set({
			q: 'Search',
			status: 'ready',
			error: null,
			items: [{ type: 'song', song: searchHit, album_id: 'a-local', album_title: 'Local Album' }],
			hasMore: false,
			nextCursor: null
		});
		applySyncedSong(
			song({
				album_id: 'a-local',
				album_title: 'Local Album',
				title: 'Listed Updated',
				generation_count: 2
			})
		);
		applySyncedSong(
			song({
				album_id: 'a-local',
				album_title: 'Local Album',
				id: 's-search',
				title: 'Search Updated',
				generation_count: 1
			})
		);
		expect(get(songList)[0].title).toBe('Listed Updated');
		expect(get(librarySearch).items[0]).toMatchObject({
			type: 'song',
			song: expect.objectContaining({ title: 'Search Updated' })
		});
		const firstHit = get(librarySearch).items[0];
		expect(firstHit?.type).toBe('song');
		if (firstHit?.type === 'song') {
			expect(firstHit.song).not.toHaveProperty('generations');
		}
		expect(listLoadedSongIds().sort()).toEqual(['s-search', 's1']);
	});

	it('forgetSyncedSong removes browse, search, and selection', () => {
		songList.set([
			song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0 }),
			song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0, id: 's2' })
		]);
		selectedSongId.set('s1');
		librarySearch.set({
			q: 'Tide',
			status: 'ready',
			error: null,
			items: [
				{
					type: 'song',
					song: searchSong({
						slug: 'local-only',
						title: 'Local Only',
						album_id: 'a-local',
						album_title: 'Local Album',
						bpm: 120,
						audio_duration: 180,
						key_scale: 'Am',
						generation_params: null,
						generation_count: 0,
						share_slug: null,
						best_scores: null,
						best_rating: null,
						cover: null
					}),
					album_id: 'a1',
					album_title: 'Nachtstrom'
				}
			],
			hasMore: false,
			nextCursor: null
		});
		forgetSyncedSong('s1');
		expect(get(songList).map((item) => item.id)).toEqual(['s2']);
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySearch).items).toEqual([]);
	});

	it('does not insert an unlisted unselected song into browse', () => {
		songList.set([song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0 })]);
		selectedSongId.set(null);
		applySyncedSong(
			song({
				album_id: 'a-local',
				album_title: 'Local Album',
				generation_count: 0,
				id: 's-other',
				title: 'Other'
			})
		);
		expect(get(songList).map((item) => item.id)).toEqual(['s1']);
	});

	it('watchLoadedSongIds notifies until unsubscribed', () => {
		const seen: number[] = [];
		const stop = watchLoadedSongIds(() => seen.push(1));
		expect(seen.length).toBeGreaterThanOrEqual(1);
		const afterSubscribe = seen.length;
		songList.set([
			song({ album_id: 'a-local', album_title: 'Local Album', generation_count: 0, id: 's-watch' })
		]);
		expect(seen.length).toBeGreaterThan(afterSubscribe);
		stop();
		const afterStop = seen.length;
		songList.set([]);
		selectedSongId.set('s-watch');
		expect(seen).toHaveLength(afterStop);
	});
});
