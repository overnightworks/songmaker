import { makeAlbum, makeGeneration, makeSong } from '#lib/test-utils/factories.ts';
import { historyLength, replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { get } from 'svelte/store';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { installHistoryController } from '#lib/history/historyController.ts';
import {
	RAIL_LIBRARY_LOAD_ERROR,
	SONG_MOVE_ALBUM_GONE,
	SONG_MOVE_FAILED_REASON,
	SONG_MOVE_NO_CONNECTION,
	songMoveFailedLine
} from '#lib/constants.ts';
import { LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import type { AlbumItem } from '#lib/api/types.ts';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('#lib/api/albums.ts', () => ({
	fetchAlbum: vi.fn().mockImplementation(async () => makeAlbum()),
	fetchAlbums: vi.fn()
}));
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	moveSong: vi.fn()
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null }),
	fetchActiveGeneration: vi.fn().mockResolvedValue(null),
	fetchVersions: vi.fn().mockResolvedValue([])
}));

import { fetchAlbums } from '#lib/api/albums.ts';
import { moveSong } from '#lib/api/songs.ts';
import {
	discardDraft,
	editLyrics,
	isDirty,
	loadSongData,
	setDraftLyrics
} from '#lib/stores/editor.ts';
import {
	initNavigation,
	followShellLayers,
	openAlbum,
	selectSong
} from '#lib/stores/navigation.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { detailTab, resetLibraryContextForTests, showSongTab } from '#lib/stores/libraryContext.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { albumList, resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { libraryWallOrder } from '#lib/stores/ui.ts';
import { toasts } from '#lib/stores/toast.ts';
import {
	askToMoveOpenSongTo,
	cancelSongMove,
	closeSongMovePicker,
	confirmSongMove,
	openSongMovePicker,
	retrySongMove,
	songMoveConfirm,
	songMoveFilter,
	songMovePicker,
	songMoveRun
} from './songMove';

const HOME = makeAlbum({ id: 'home', title: 'Homeoffice', song_count: 3 });
const ABEND = makeAlbum({ id: 'abend', title: 'Abendrot', song_count: 5 });
const NEON = makeAlbum({ id: 'neon', title: 'Neon Harbour', song_count: 2, is_shared: true });

function ownAlbums(...items: AlbumItem[]): void {
	vi.mocked(fetchAlbums).mockResolvedValue({
		items,
		total: items.length,
		offset: 0,
		limit: 50,
		has_more: false
	});
}

function readyPicker() {
	const picker = get(songMovePicker);
	if (picker.status !== 'ready') throw new Error(`picker is ${picker.status}`);
	return picker;
}

let stopFollowingShellLayers: () => void = () => undefined;
let stopNavigation: () => void = () => undefined;

const OPEN_SONG = makeSong({
	id: 's1',
	slug: 'storytime',
	album_id: 'home',
	album_title: 'Homeoffice',
	generations: [makeGeneration()]
});

beforeEach(async () => {
	libraryWallOrder.set('title');
	toasts.set([]);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
	stopFollowingShellLayers = followShellLayers();
	songList.set([OPEN_SONG]);
	albumList.set([HOME, ABEND, NEON]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	startFakeRouter();
	installHistoryController();
	stopNavigation = initNavigation();
	await openAlbum('home');
	await selectSong('s1');
	loadSongData(OPEN_SONG);
});

afterEach(() => {
	discardDraft();
	closeSongMovePicker();
	cancelSongMove();
	songMoveFilter.set('');
	stopNavigation();
	stopFollowingShellLayers();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
	resetLibraryDataForTests();
	vi.mocked(fetchAlbums).mockReset();
	vi.mocked(moveSong).mockReset();
});

describe('the move picker', () => {
	it('lists only the owned albums, the current one pinned and the others in library order', async () => {
		ownAlbums(NEON, HOME, ABEND);

		const loading = openSongMovePicker();
		expect(get(songMovePicker).status).toBe('loading');
		await loading;

		const picker = readyPicker();
		expect(picker.current?.id).toBe('home');
		expect(picker.others.map((album) => album.id)).toEqual(['abend', 'neon']);
		expect(vi.mocked(fetchAlbums)).toHaveBeenCalledWith(0, expect.any(Number), { owned: true });
	});

	it('narrows the others by title with the filter and keeps the current album', async () => {
		ownAlbums(HOME, ABEND, NEON);
		await openSongMovePicker();

		songMoveFilter.set('  NEON ');

		const picker = readyPicker();
		expect(picker.current?.id).toBe('home');
		expect(picker.others.map((album) => album.id)).toEqual(['neon']);
	});

	it('says there is no other album when the person owns only the current one', async () => {
		ownAlbums(HOME);
		await openSongMovePicker();

		expect(readyPicker()).toMatchObject({ current: HOME, others: [], hasOthers: false });
	});

	it('names a failed list and loads again on a second open', async () => {
		vi.mocked(fetchAlbums).mockRejectedValueOnce(new Error('boom'));
		await openSongMovePicker();
		expect(get(songMovePicker)).toEqual({ status: 'failed', message: RAIL_LIBRARY_LOAD_ERROR });

		ownAlbums(HOME, ABEND);
		await openSongMovePicker();

		expect(readyPicker().others.map((album) => album.id)).toEqual(['abend']);
	});

	it('ignores a list that arrives after the picker closed', async () => {
		ownAlbums(HOME, ABEND);
		const loading = openSongMovePicker();
		closeSongMovePicker();
		await loading;

		expect(get(songMovePicker).status).toBe('closed');
	});
});

describe('moving the open song', () => {
	const movedSong = {
		...OPEN_SONG,
		album_id: 'abend',
		album_title: 'Abendrot',
		track_number: 6
	};

	it('puts the song in the new album and adjusts both counts', async () => {
		vi.mocked(moveSong).mockResolvedValue(movedSong);

		await askToMoveOpenSongTo(ABEND);

		expect(get(songList)[0]).toMatchObject({ album_id: 'abend', album_title: 'Abendrot' });
		const counts = Object.fromEntries(get(albumList).map((a) => [a.id, a.song_count]));
		expect(counts).toMatchObject({ home: 2, abend: 6, neon: 2 });
	});

	it('keeps the person on the song with its draft, tab and pinned take and replaces the address', async () => {
		onTestFinished(discardDraft);
		vi.mocked(moveSong).mockResolvedValue(movedSong);
		setDraftLyrics('unsaved move draft');
		showSongTab('s1', 'takes');
		selectedGenerationId.set('g1');
		const entries = historyLength();

		await askToMoveOpenSongTo(ABEND);

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved move draft');
		expect(get(isDirty)).toBe(true);
		expect(get(detailTab)).toBe('takes');
		expect(get(selectedGenerationId)).toBe('g1');
		expect(location.pathname).toBe('/album/abend/storytime/take/1');
		expect(historyLength()).toBe(entries);
	});

	it('does nothing for the album the song already stands in', async () => {
		await askToMoveOpenSongTo(HOME);

		expect(moveSong).not.toHaveBeenCalled();
		expect(get(songList)[0].album_id).toBe('home');
	});

	it('leaves the song where it is and names the server refusal, with a retry', async () => {
		vi.mocked(moveSong).mockRejectedValue(
			new ApiError(422, 'Album is full', '/api/songs/s1/album')
		);

		await askToMoveOpenSongTo(ABEND);

		expect(get(songList)[0].album_id).toBe('home');
		expect(location.pathname).toBe('/album/home/storytime');
		expect(get(songMoveRun)).toEqual({
			status: 'failed',
			albumId: 'abend',
			line: songMoveFailedLine('Album is full'),
			retryable: true
		});
		expect(get(toasts)).toEqual([]);
	});

	it('names a failed network as no connection', async () => {
		vi.mocked(moveSong).mockRejectedValue(
			new NetworkError('/api/songs/s1/album', new TypeError('offline'))
		);

		await askToMoveOpenSongTo(ABEND);

		expect(get(songMoveRun)).toMatchObject({ line: songMoveFailedLine(SONG_MOVE_NO_CONNECTION) });
	});

	it('falls back to a plain reason when the error carries no detail', async () => {
		vi.mocked(moveSong).mockRejectedValue(new Error('boom'));

		await askToMoveOpenSongTo(ABEND);

		expect(get(songMoveRun)).toMatchObject({ line: songMoveFailedLine(SONG_MOVE_FAILED_REASON) });
	});

	it('says album gone without a retry on a 404 and loads the album list again', async () => {
		ownAlbums(HOME, ABEND);
		await openSongMovePicker();
		ownAlbums(HOME);
		vi.mocked(moveSong).mockRejectedValue(
			new ApiError(404, 'Song or album not found', '/api/songs/s1/album')
		);

		await askToMoveOpenSongTo(ABEND);

		expect(get(songMoveRun)).toEqual({
			status: 'failed',
			albumId: 'abend',
			line: songMoveFailedLine(SONG_MOVE_ALBUM_GONE),
			retryable: false
		});
		expect(readyPicker().hasOthers).toBe(false);
	});

	it('is busy for the tapped album only while the move runs and idle once it succeeded', async () => {
		const pending = Promise.withResolvers<typeof movedSong>();
		vi.mocked(moveSong).mockReturnValue(pending.promise);

		const moving = askToMoveOpenSongTo(ABEND);

		expect(get(songMoveRun)).toEqual({ status: 'busy', albumId: 'abend' });
		pending.resolve(movedSong);
		await moving;
		expect(get(songMoveRun)).toEqual({ status: 'idle' });
	});

	it('starts no second move while one runs', async () => {
		const pending = Promise.withResolvers<typeof movedSong>();
		vi.mocked(moveSong).mockReturnValue(pending.promise);

		const first = askToMoveOpenSongTo(ABEND);
		await askToMoveOpenSongTo(NEON);
		await askToMoveOpenSongTo(ABEND);
		pending.resolve(movedSong);
		await first;

		expect(moveSong).toHaveBeenCalledTimes(1);
		expect(get(songMoveConfirm)).toBeNull();
	});

	it('repeats the same move on retry and is idle after it passed', async () => {
		vi.mocked(moveSong).mockRejectedValueOnce(new Error('boom')).mockResolvedValue(movedSong);
		ownAlbums(HOME, ABEND);
		await openSongMovePicker();
		await askToMoveOpenSongTo(ABEND);

		await retrySongMove();

		expect(moveSong).toHaveBeenLastCalledWith('s1', 'abend');
		expect(get(songMoveRun)).toEqual({ status: 'idle' });
		expect(get(songList)[0].album_id).toBe('abend');
	});

	it('goes idle when the picker closes after a refusal', async () => {
		vi.mocked(moveSong).mockRejectedValue(new Error('boom'));
		await askToMoveOpenSongTo(ABEND);

		closeSongMovePicker();

		expect(get(songMoveRun)).toEqual({ status: 'idle' });
	});

	it('does not pull the person back when another song is open once the move resolves', async () => {
		const other = makeSong({ id: 's2', slug: 'other', album_id: 'home', generations: [] });
		songList.set([OPEN_SONG, other]);
		const pending = Promise.withResolvers<typeof movedSong>();
		vi.mocked(moveSong).mockReturnValue(pending.promise);
		const moving = askToMoveOpenSongTo(ABEND);

		await selectSong('s2');
		pending.resolve(movedSong);
		await moving;

		expect(get(selectedSongId)).toBe('s2');
		expect(get(songList).find((song) => song.id === 's1')?.album_id).toBe('abend');
		const counts = Object.fromEntries(get(albumList).map((a) => [a.id, a.song_count]));
		expect(counts).toMatchObject({ home: 2, abend: 6 });
	});
});

describe('asking before a move', () => {
	beforeEach(() => {
		vi.mocked(moveSong).mockResolvedValue({ ...OPEN_SONG, album_id: 'neon' });
	});

	it('asks first when the target album has a public page and moves nothing yet', async () => {
		await askToMoveOpenSongTo(NEON);

		expect(get(songMoveConfirm)).toEqual(NEON);
		expect(moveSong).not.toHaveBeenCalled();
	});

	it('moves at once into a private album without asking', async () => {
		vi.mocked(moveSong).mockResolvedValue({ ...OPEN_SONG, album_id: 'abend' });

		await askToMoveOpenSongTo(ABEND);

		expect(get(songMoveConfirm)).toBeNull();
		expect(get(songList)[0].album_id).toBe('abend');
	});

	it('moves the song into the asked album once confirmed and stops asking', async () => {
		await askToMoveOpenSongTo(NEON);

		await confirmSongMove();

		expect(get(songMoveConfirm)).toBeNull();
		expect(get(songList)[0].album_id).toBe('neon');
	});

	it('moves nothing and stops asking when cancelled', async () => {
		await askToMoveOpenSongTo(NEON);

		cancelSongMove();

		expect(get(songMoveConfirm)).toBeNull();
		expect(moveSong).not.toHaveBeenCalled();
		expect(get(songList)[0].album_id).toBe('home');
	});
});
