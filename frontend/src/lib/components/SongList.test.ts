import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_BROWSE_EMPTY,
	LIBRARY_RETRY_LABEL,
	LIBRARY_SEARCH_DEBOUNCE_MS,
	LIBRARY_SEARCH_EMPTY,
	LIBRARY_SEARCH_LOADING,
	LIBRARY_SEARCH_PLACEHOLDER
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, songList } from '$lib/stores/player';
import { playlistList } from '$lib/stores/playlists';

const searchLibrary = vi.fn();

vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbums: vi.fn()
}));
vi.mock('$lib/api/songs', () => ({
	fetchSongs: vi.fn()
}));
vi.mock('$lib/stores/navigation', () => ({
	selectAlbumOverview: vi.fn(),
	selectPlaylistView: vi.fn(),
	selectSong: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn()
}));

import SongList from './SongList.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Local Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's-local',
		title: 'Local Only',
		album_id: 'a-local',
		album_title: 'Local Album',
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
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function render() {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const component = mount(SongList, { target });
	mounted.push(component);
	return target;
}

beforeEach(() => {
	vi.useFakeTimers();
	searchLibrary.mockReset();
	resetLibrarySearchForTests();
	searchQuery.set('');
	playlistList.set([]);
	albumList.set([album()]);
	songList.set([song()]);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.useRealTimers();
	resetLibrarySearchForTests();
	searchQuery.set('');
});

describe('SongList search', () => {
	it('uses a library-wide placeholder', async () => {
		const target = render();
		await tick();
		const input = target.querySelector('input.search') as HTMLInputElement;
		expect(input.placeholder).toBe(LIBRARY_SEARCH_PLACEHOLDER);
	});

	it('shows browse empty copy when there are no songs', async () => {
		albumList.set([]);
		songList.set([]);
		const target = render();
		await tick();
		expect(target.textContent).toContain(LIBRARY_BROWSE_EMPTY);
		expect(target.textContent).not.toContain(LIBRARY_SEARCH_EMPTY);
	});

	it('searches the server instead of filtering the loaded song list', async () => {
		searchLibrary.mockResolvedValue({
			items: [
				{
					type: 'album',
					album: album({ id: 'nachtstrom', title: 'Nachtstrom' })
				}
			],
			next_cursor: null,
			has_more: false
		});
		const target = render();
		await tick();
		searchQuery.set('Nachtstrom');
		await tick();
		expect(target.textContent).toContain(LIBRARY_SEARCH_LOADING);
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(searchLibrary).toHaveBeenCalled();
		expect(target.textContent).toContain('Nachtstrom');
		expect(target.textContent).not.toContain('Local Only');
		expect(get(songList)[0].title).toBe('Local Only');
	});

	it('shows search empty copy when the server returns no hits', async () => {
		searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
		const target = render();
		await tick();
		searchQuery.set('missing');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain(LIBRARY_SEARCH_EMPTY);
		expect(target.textContent).not.toContain(LIBRARY_BROWSE_EMPTY);
	});

	it('shows retry when search fails', async () => {
		searchLibrary.mockRejectedValue(new Error('offline'));
		const target = render();
		await tick();
		searchQuery.set('Tide');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain('offline');
		const retry = [...target.querySelectorAll('button')].find(
			(button) => button.textContent === LIBRARY_RETRY_LABEL
		);
		expect(retry).toBeDefined();
	});
});
