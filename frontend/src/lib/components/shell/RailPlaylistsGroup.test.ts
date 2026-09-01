import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { PlaylistDetailItem, PlaylistEntryItem, PlaylistItem } from '$lib/api/types';
import { openCollection, setOpenCollection } from '$lib/stores/collection';
import {
	libraryFilter,
	librarySurface,
	resetLibraryContextForTests
} from '$lib/stores/libraryContext';
import { closeNowPlaying, nowPlayingOpen, nowPlayingPanel, queueContext } from '$lib/stores/player';
import { playlistList, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';

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
const fetchPlaylists = vi.fn().mockResolvedValue([]);
const fetchPlaylist = vi.fn();
vi.mock('$lib/api/client', () => ({
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false }),
	fetchAlbum: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args)
}));

import RailPlaylistsGroup from './RailPlaylistsGroup.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function entry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Tide',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'tide.mp3',
		seed: 1,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

function detail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [entry()],
		...overrides
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(RailPlaylistsGroup, { target });
	await tick();
	return target;
}

beforeEach(() => {
	localStorage.clear();
	resetLibraryContextForTests();
	fetchPlaylists.mockClear().mockResolvedValue([]);
	fetchPlaylist.mockReset();
	playlistList.set([playlist()]);
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
		audioPlayer.status = 'playing';
	});
});

afterEach(async () => {
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetPlaylists();
	resetLibraryContextForTests();
});

describe('RailPlaylistsGroup', () => {
	it('shows the PLAYLISTS group with its icon and the current playlist count, collapsed with no playlist open', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(target.querySelector('.group-title')?.textContent?.trim()).toBe('Playlists');
		expect(target.querySelector('.meta')?.textContent).toBe('1');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('opens the library grid on the Playlists tab when the PLAYLISTS title is clicked', async () => {
		librarySurface.set('detail');
		libraryFilter.set('albums');
		const target = await render();
		const titleButton = requireElement<HTMLButtonElement>(target, 'button.group-title');
		titleButton.click();
		await vi.waitFor(() => expect(get(libraryFilter)).toBe('playlists'));
		expect(get(librarySurface)).toBe('browse');
	});

	it('loads every playlist on mount regardless of the current route', async () => {
		await render();
		await vi.waitFor(() => expect(fetchPlaylists).toHaveBeenCalled());
	});

	it('opens on click and lists every playlist with its own track count', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive', entry_count: 2 }),
			playlist({ id: 'p2', title: 'Favorites', entry_count: 12 })
		]);
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const rows = target.querySelectorAll('.playlist-label .row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Night Drive', 'Favorites']);
		const counts = target.querySelectorAll('.playlist-label .row-meta');
		expect(Array.from(counts).map((row) => row.textContent)).toEqual(['2', '12']);
	});

	it('pre-expands the open playlist and shows its tracks, marking the currently playing one', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Favorites' })
		]);
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			detail({
				id: 'p1',
				entries: [
					entry({ id: 'pe1', song_title: 'Tide', generation_id: 'g1', mp3_path: 'tide.mp3' }),
					entry({ id: 'pe2', song_title: 'Ebb', generation_id: 'g2', mp3_path: 'ebb.mp3' })
				]
			})
		);
		audioPlayer.current = {
			generation: { id: 'g2', mp3_path: 'ebb.mp3' }
		} as unknown as typeof audioPlayer.current;
		audioPlayer.status = 'playing';

		const target = await render();

		const rows = target.querySelectorAll('.row-sub2 .row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
		const active = target.querySelector('.row-sub2.row-active .row-title');
		expect(active?.textContent).toBe('Ebb');
		expect(target.querySelector('.row-sub2.row-active .equalizer')).not.toBeNull();
	});

	it('navigates into the playlist and expands it when its label is clicked', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Favorites' })
		]);
		fetchPlaylist.mockResolvedValue(detail({ id: 'p2', title: 'Favorites' }));
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const labels = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		labels[1]?.click();
		await tick();
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p2' }));
		await tick();

		const rows = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		expect(rows[1]?.classList.contains('row-active')).toBe(true);
	});

	it('plays a clicked track and surfaces it in Now Playing', async () => {
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		selectedPlaylistDetail.set(
			detail({
				id: 'p1',
				entries: [
					entry({ id: 'pe1', song_title: 'Tide', generation_id: 'g1' }),
					entry({ id: 'pe2', song_title: 'Ebb', generation_id: 'g2' })
				]
			})
		);
		const target = await render();

		const rows = target.querySelectorAll<HTMLButtonElement>('.row-sub2');
		rows[1]?.click();
		await tick();

		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.entries[ctx.index]?.id).toBe('pe2');
	});
});
