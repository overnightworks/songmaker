import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryListenItem } from '$lib/api/library';
import { get } from 'svelte/store';
import {
	COLLECTION_MENU_ARCHIVE_LABEL,
	COLLECTION_MENU_DELETE_LABEL,
	HOME_LISTEN_EMPTY,
	HOME_LISTEN_ERROR,
	PLAYING_MARK_LABEL
} from '$lib/constants';
import { albumList, allAlbumsLoad, songList } from '$lib/stores/libraryData';
import { deletePlaylist, playlistList, playlistLoad } from '$lib/stores/playlists';
import {
	ensureLastPlayedRead,
	readLastPlayed,
	resetLibraryOrderForTests
} from '$lib/stores/libraryOrder';
import { queueContext } from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { makeAlbum, makePlaylist, makeSong, makeGeneration } from '$lib/test-utils/factories';
import { toasts } from '$lib/stores/toast';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { openCollectionMenu, requireButtonContainingText } from './shell/rail-test-fixtures';
import AlbumDetailView from './AlbumDetailView.svelte';
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
	heldListenRead = Promise.resolve();
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
	toasts.set([]);
	vi.unstubAllGlobals();
});

async function showListen(): Promise<void> {
	component = mount(HomeListen, { target });
	await vi.waitFor(() => expect(target.querySelector('[role="status"]')).toBeNull());
	await tick();
}

// The album page of the first place, answering its delete, archive and their
// Undo the way the server does; Listen answers whatever `listenAnswer` holds
// when the read reaches it, and a held read answers only once released.
function serveAlbumPage(listenAnswer: () => LibraryListenItem[]): void {
	const album = homeAlbums[0];
	fetchListen.mockImplementation(async (url: string) => {
		const { pathname } = new URL(url, 'http://localhost');
		if (pathname === '/api/library/listen') {
			const items = listenAnswer();
			await heldListenRead;
			return Response.json({ items });
		}
		if (pathname === `/api/albums/${album.id}/cover-suggestions`)
			return Response.json({ job: null, suggestions: [], used_today: 0, daily_limit: 10 });
		if (pathname.startsWith(`/api/albums/${album.id}`)) return Response.json(album);
		return Response.json({ items: [], total: 0, offset: 0, limit: 200, has_more: false });
	});
}

async function removeOnAlbumPage(action: string): Promise<void> {
	const page = document.createElement('div');
	document.body.append(page);
	const albumPage = mount(AlbumDetailView, { target: page, props: { albumId: 'place-0' } });
	await tick();
	requireButtonContainingText(await openCollectionMenu(page), action).click();
	await tick();
	if (action === COLLECTION_MENU_DELETE_LABEL)
		getByRoleButton(document.body, 'Delete Album').click();
	await vi.waitFor(() => expect(get(toasts).some((toast) => toast.action)).toBe(true));
	await unmount(albumPage);
	page.remove();
}

let heldListenRead: Promise<void> = Promise.resolve();

function holdNextListenRead(): () => void {
	let release = () => {};
	heldListenRead = new Promise((resolve) => (release = resolve));
	return () => {
		heldListenRead = Promise.resolve();
		release();
	};
}

async function undoLastRemoval(): Promise<void> {
	await get(toasts)
		.find((toast) => toast.action)
		?.action?.handler();
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

	const deleteAlbumHere = () => removeOnAlbumPage(COLLECTION_MENU_DELETE_LABEL);
	const deletePlaylistHere = () => deletePlaylist('place-1');
	const album = 'Open album Place 0';
	const playlist = 'Open playlist Place 1';
	const reloads = [
		[
			'album',
			'loading',
			[album],
			deleteAlbumHere,
			() => allAlbumsLoad.set({ status: 'loading', error: null })
		],
		[
			'album',
			'unreachable',
			[album],
			deleteAlbumHere,
			() => allAlbumsLoad.set({ status: 'unreachable', error: null })
		],
		[
			'album',
			'error',
			[album],
			deleteAlbumHere,
			() => allAlbumsLoad.set({ status: 'error', error: null })
		],
		[
			'playlist',
			'loading',
			[playlist],
			deletePlaylistHere,
			() => playlistLoad.set({ status: 'loading', error: null })
		],
		[
			'playlist',
			'error',
			[playlist],
			deletePlaylistHere,
			() => playlistLoad.set({ status: 'error', error: null })
		],
		[
			'album and a playlist',
			'loading',
			[album, playlist],
			async () => {
				await deleteAlbumHere();
				await deletePlaylistHere();
			},
			() => {
				allAlbumsLoad.set({ status: 'loading', error: null });
				playlistLoad.set({ status: 'loading', error: null });
			}
		]
	] as const;
	it.each(
		reloads.flatMap(([type, reloadState, removedRows, deleteHere, reloadWithoutAnswer]) =>
			(['before', 'after'] as const).map(
				(answered) =>
					[type, reloadState, answered, removedRows, deleteHere, reloadWithoutAnswer] as const
			)
		)
	)(
		'1354_rule_20 keeps a %s deleted here off Listen while its collection reload is %s, a Listen read answering %s the delete',
		async (_type, _reloadState, answered, removedRows, deleteHere, reloadWithoutAnswer) => {
			serveAlbumPage(() => places);
			const release = answered === 'after' ? holdNextListenRead() : () => {};
			const read = ensureLastPlayedRead();
			if (answered === 'before') await read;
			await deleteHere();
			release();
			await read;
			reloadWithoutAnswer();
			await showListen();
			for (const row of removedRows) expect(rowNames()).not.toContain(row);
		}
	);

	// `around`: the read starts before the delete and answers after the Undo.
	// A post-Undo read that `fails` leaves Home to rank the album on its next
	// opening, so Home opens once more before the row must be back.
	it.each([
		[COLLECTION_MENU_DELETE_LABEL, 'before', 'answers'],
		[COLLECTION_MENU_DELETE_LABEL, 'after', 'answers'],
		[COLLECTION_MENU_ARCHIVE_LABEL, 'before', 'answers'],
		[COLLECTION_MENU_ARCHIVE_LABEL, 'after', 'answers'],
		[COLLECTION_MENU_DELETE_LABEL, 'around', 'fails'],
		[COLLECTION_MENU_DELETE_LABEL, 'before', 'fails']
	] as const)(
		'1354_rule_20 %s on the album page, a Listen read on Home answering %s the Undo, the read after the Undo %s, then the row is back',
		async (action, answered, readAfterUndo) => {
			let removed = false;
			let unreachable = false;
			serveAlbumPage(() => {
				if (unreachable) throw new TypeError('Listen unreachable');
				return removed ? places.slice(1) : places;
			});
			await showListen();
			await unmount(component);
			const releaseAround = answered === 'around' ? holdNextListenRead() : null;
			const readAround = answered === 'around' ? readLastPlayed() : null;
			await removeOnAlbumPage(action);
			removed = true;
			await showListen();
			expect(rowNames()).not.toContain(album);
			const release = releaseAround ?? (answered === 'after' ? holdNextListenRead() : () => {});
			const read = readAround ?? readLastPlayed();
			if (answered === 'before') await read;
			removed = false;
			unreachable = readAfterUndo === 'fails';
			await undoLastRemoval();
			release();
			if (answered === 'before' && readAfterUndo === 'fails') {
				expect(await readLastPlayed()).toBe(false);
				unreachable = false;
				await unmount(component);
				await showListen();
			}
			await vi.waitFor(() => expect(rowNames()[0]).toBe(album));
		}
	);

	it('1354_rule_19 reads Listen again on the return to the foreground and shows the new order', async () => {
		await showListen();
		fetchListen.mockImplementation(async () => Response.json({ items: places.toReversed() }));
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		document.dispatchEvent(new Event('visibilitychange'));
		await vi.waitFor(() =>
			expect(rowNames()).toEqual([
				'Open playlist Place 3',
				'Open album Place 2',
				'Open playlist Place 1'
			])
		);
		expect(fetchListen).toHaveBeenCalledTimes(2);
	});

	it.each(['album', 'playlist'] as const)(
		'1354_rule_15 shows pause and the playing mark for the playing %s and its current song subtitle',
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
			const playingRow = getByRoleButton(target, `Pause ${title}`).closest('.library-row');
			expect(
				playingRow?.querySelector(`[role="img"][aria-label="${PLAYING_MARK_LABEL}"]`)
			).not.toBeNull();
			expect(target.querySelectorAll(`[aria-label="${PLAYING_MARK_LABEL}"]`)).toHaveLength(1);
			expect(target.textContent).toContain(
				`${type === 'album' ? 'Album' : 'Playlist'} · playing · song 2 of 4`
			);
		}
	);
});
