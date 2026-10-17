import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryListenItem } from '$lib/api/library';
import { HOME_LISTEN_EMPTY, HOME_LISTEN_ERROR } from '$lib/constants';
import { albumList, allAlbumsLoad, songList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import {
	ensureLastPlayedRead,
	readLastPlayed,
	resetLibraryOrderForTests
} from '$lib/stores/libraryOrder';
import { queueContext } from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { makeAlbum, makePlaylist, makeSong, makeGeneration } from '$lib/test-utils/factories';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import HomeListen from './HomeListen.svelte';

const places: LibraryListenItem[] = Array.from({ length: 4 }, (_, index) => ({
	type: index % 2 === 0 ? 'album' : 'playlist',
	id: `place-${index}`,
	title: `Place ${index}`,
	cover: null,
	album_covers: [],
	song_id: null,
	song_title: null,
	song_number: null,
	played_at: '2026-10-17T10:00:00Z'
}));
const homeAlbums = places
	.filter((place) => place.type === 'album')
	.map((place) => makeAlbum({ id: place.id, title: place.title }));
const homePlaylists = places
	.filter((place) => place.type === 'playlist')
	.map((place) => makePlaylist({ id: place.id, title: place.title }));
const fetchListen = vi.fn();
let component: ReturnType<typeof mount>;
let target: HTMLElement;

beforeEach(() => {
	resetLibraryOrderForTests();
	albumList.set(homeAlbums);
	allAlbumsLoad.set({ status: 'ready', error: null });
	playlistList.set(homePlaylists);
	playlistLoad.set({ status: 'ready', error: null });
	queueContext.set({ type: 'library' });
	audioPlayer.current = null;
	fetchListen.mockReset().mockImplementation(async () => Response.json({ items: places }));
	vi.stubGlobal('fetch', fetchListen);
	target = document.createElement('div');
	document.body.append(target);
});

afterEach(async () => {
	if (component) await unmount(component);
	target.remove();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	vi.unstubAllGlobals();
});

async function showListen(): Promise<void> {
	component = mount(HomeListen, { target });
	await vi.waitFor(() => expect(target.querySelector('[role="status"]')).toBeNull());
	await tick();
}

const rowNames = () =>
	[...target.querySelectorAll('.wall-tile-body')].map((row) => row.getAttribute('aria-label'));

describe('1354_rule_14 Listen', () => {
	it('shows the first three places in the shared owner order with one read', async () => {
		await ensureLastPlayedRead();
		await showListen();
		expect(rowNames()).toEqual([
			'Open album Place 0',
			'Open playlist Place 1',
			'Open album Place 2'
		]);
		expect(
			fetchListen.mock.calls.map(([url]) => new URL(url, 'http://localhost').pathname)
		).toEqual(['/api/library/listen']);
		expect(target.querySelectorAll('.library-row')).toHaveLength(3);
	});

	it('1354_rule_18 names what fills an empty Listen', async () => {
		fetchListen.mockImplementation(async () => Response.json({ items: [] }));
		await showListen();
		expect(target.textContent).toContain(HOME_LISTEN_EMPTY);
		expect(rowNames()).toEqual([]);
	});

	it('1354_rule_19 retains rows after a failed refresh and remount', async () => {
		await showListen();
		fetchListen.mockRejectedValue(new TypeError('offline'));
		await readLastPlayed();
		await unmount(component);
		await showListen();
		expect(rowNames()).toHaveLength(3);
		expect(target.textContent).not.toContain(HOME_LISTEN_ERROR);
	});

	it('1354_rule_19 offers Retry when never loaded and Retry fills the rows', async () => {
		fetchListen.mockRejectedValueOnce(new TypeError('offline'));
		await showListen();
		expect(target.textContent).toContain(HOME_LISTEN_ERROR);
		getByRoleButton(target, 'Retry').click();
		await vi.waitFor(() => expect(rowNames()).toHaveLength(3));
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it.each(['delete album', 'archive album', 'delete playlist'])(
		'1354_rule_20 %s removes the row immediately',
		async (action) => {
			await showListen();
			if (action === 'delete playlist') playlistList.set(homePlaylists.slice(1));
			else if (action === 'archive album')
				albumList.set(
					homeAlbums.map((album, index) => (index === 0 ? { ...album, is_archived: true } : album))
				);
			else albumList.set(homeAlbums.slice(1));
			await tick();
			expect(rowNames()).not.toContain(
				action === 'delete playlist' ? 'Open playlist Place 1' : 'Open album Place 0'
			);
			if (action === 'delete album') {
				albumList.set(homeAlbums);
				await tick();
				expect(rowNames()[0]).toBe('Open album Place 0');
			}
		}
	);

	it.each(['album', 'playlist'] as const)(
		'1354_rule_15 shows pause for the playing %s and its current song subtitle',
		async (type) => {
			const id = type === 'album' ? 'place-0' : 'place-1';
			const title = type === 'album' ? 'Place 0' : 'Place 1';
			playlistList.set([
				makePlaylist({ id: 'place-1', entry_count: 4 }),
				...homePlaylists.slice(1)
			]);
			albumList.set([makeAlbum({ id: 'place-0', song_count: 4 }), ...homeAlbums.slice(1)]);
			songList.set([makeSong({ id: 'song', album_id: 'place-0', track_number: 2 })]);
			queueContext.set(
				type === 'album'
					? { type, albumId: id }
					: { type, playlist: { id, title }, entries: [], index: 1 }
			);
			audioPlayer.current = {
				generation: makeGeneration(),
				songId: 'song',
				songTitle: 'Song',
				albumTitle: 'Place 0',
				artist: '',
				lyrics: null
			};
			audioPlayer.status = 'playing';
			await showListen();
			expect(getByRoleButton(target, `Pause ${title}`)).toBeTruthy();
			expect(target.textContent).toContain(
				`${type === 'album' ? 'Album' : 'Playlist'} · playing · song 2 of 4`
			);
		}
	);
});
