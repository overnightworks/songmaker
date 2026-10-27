import {
	historyEntry,
	historyLength,
	pressBack,
	pressForward,
	replaceHistoryEntry
} from '$lib/test-utils/library-history';
import { makeAlbum as album, makeGeneration, makeSong as song } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { mount, tick, unmount } from 'svelte';
import SongDetailView from '$lib/components/SongDetailView.svelte';
import { goto } from '$app/navigation';
import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { historyComesToRest, installHistoryController } from '$lib/history/historyController';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { resetPlaylistsForTests } from '$lib/stores/playlists';
import { LIBRARY_ROUTE_PATH } from '$lib/routes/addresses';
import {
	DIALOG_CANCEL_LABEL,
	EDITOR_UNSAVED_DISCARD_LABEL,
	EDITOR_UNSAVED_TITLE
} from '$lib/constants';
import { activeJobs, removeJob, resetGenerationFailuresForTests } from '$lib/stores/jobs';
import { toasts } from '$lib/stores/toast';

const fetchSong = vi.fn();
const fetchAlbum = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLastFailedGeneration = vi.fn();
const fetchActiveGeneration = vi.fn();

// goto actually changes the URL (via the History API, like the real
// SvelteKit goto) so tests can assert the landed-on route, not just that
// goto was called with some argument (see issue #264's done-when).
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/loras', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/loras')>()),
	listLoras: vi.fn().mockResolvedValue([])
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => fetchLastFailedGeneration(...args),
	fetchActiveGeneration: (...args: unknown[]) => fetchActiveGeneration(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn(),
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn()
}));

import {
	followShellLayers,
	initNavigation,
	jumpToTake,
	openAlbum,
	resetNavigationForTests,
	selectSong
} from './navigation';

import { discardDraft, editLyrics, loadSongData, setDraftLyrics } from '$lib/stores/editor';
const SOURCE_TAKE_ID = 'source';
const OTHER_TAKE_ID = 'other';
const UNSAVED_LYRICS = 'unsaved edit';
const TIDE_DEFAULTS = { title: 'Tide', album_title: 'Nachtstrom', generations: [makeGeneration()] };

let stopFollowingShellLayers: () => void = () => undefined;
let stopNavigation: () => void = () => undefined;

beforeEach(() => {
	fetchSong.mockReset().mockImplementation(async () => song({ ...TIDE_DEFAULTS, slug: 's1' }));
	fetchAlbum.mockReset().mockImplementation(async () => album({ share_slug: null }));
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset();
	fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	fetchActiveGeneration.mockReset().mockResolvedValue(null);
	resetGenerationFailuresForTests();
	toasts.set([]);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetNavigationForTests();
	stopFollowingShellLayers = followShellLayers();
	albumList.set([album({ share_slug: null })]);
	songList.set([song({ ...TIDE_DEFAULTS, slug: 's1' })]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	startFakeRouter();
	installHistoryController();
	vi.mocked(goto).mockClear();
	stopNavigation = initNavigation();
});

afterEach(() => {
	stopNavigation();
	stopFollowingShellLayers();
	for (const { job } of get(activeJobs)) removeJob(job.id);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
});

async function openTheSongFromItsAlbum(): Promise<void> {
	await openAlbum('a1');
	await selectSong('s1');
	await historyComesToRest();
}

function anchor(takeId: string): string {
	return `#take-${takeId}`;
}

describe('jumpToTake and the entries it writes (rule 10, cells J1, J3, J10)', () => {
	it('writes one entry of the song at the take anchor and keeps the song open', async () => {
		await openTheSongFromItsAlbum();
		const entries = historyLength();

		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(historyLength()).toBe(entries + 1);
		expect(get(selectedSongId)).toBe('s1');
		expect(historyEntry().songId).toBe('s1');
	});

	it('writes nothing when the address already ends in that anchor', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();
		const entries = historyLength();

		await jumpToTake(SOURCE_TAKE_ID);

		expect(historyLength()).toBe(entries);
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
	});

	it('writes a further entry for another take', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();
		const entries = historyLength();

		await jumpToTake(OTHER_TAKE_ID);
		await historyComesToRest();

		expect(historyLength()).toBe(entries + 1);
		expect(location.hash).toBe(anchor(OTHER_TAKE_ID));
	});

	it('goes Back to the song without the anchor and Forward to the anchor, with the song open', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();

		await pressBack();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe('');
		expect(get(selectedSongId)).toBe('s1');

		await pressForward();

		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(get(selectedSongId)).toBe('s1');
	});

	it('steps album, song and anchor in order with no question when the draft is clean', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();

		await pressBack();
		await pressBack();

		expect(location.pathname).toBe('/album/a1');
		expect(get(selectedSongId)).toBeNull();

		await pressForward();
		await pressForward();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(get(selectedSongId)).toBe('s1');
	});
});

describe('Back and Forward with a draft nobody saved (rule 15, cells J6, J8)', () => {
	let target: HTMLElement;
	let view: ReturnType<typeof mount>;

	beforeEach(async () => {
		target = document.createElement('div');
		document.body.append(target);
		view = mount(SongDetailView, { target });
		await openTheSongFromItsAlbum();
		loadSongData(song({ ...TIDE_DEFAULTS, slug: 's1' }));
		setDraftLyrics(UNSAVED_LYRICS);
	});

	afterEach(async () => {
		discardDraft();
		await unmount(view);
		target.remove();
	});

	function unsavedChangesDialog(): HTMLElement | null {
		return document.querySelector(`[role="dialog"][aria-label="${EDITOR_UNSAVED_TITLE}"]`);
	}

	function answer(label: string): void {
		const buttons = Array.from(unsavedChangesDialog()?.querySelectorAll('button') ?? []);
		buttons.find((candidate) => candidate.textContent?.trim() === label)?.click();
	}

	it('asks nothing on Back and Forward between the entries of the song, and keeps the draft', async () => {
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();
		await jumpToTake(OTHER_TAKE_ID);
		await historyComesToRest();

		await pressBack();
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		await pressBack();
		expect(location.hash).toBe('');
		await pressForward();
		await pressForward();
		await tick();

		expect(location.hash).toBe(anchor(OTHER_TAKE_ID));
		expect(unsavedChangesDialog()).toBeNull();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe(UNSAVED_LYRICS);
	});

	it('still asks on the Back that leaves the song, and Cancel keeps the song and the draft', async () => {
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();
		await pressBack();
		expect(unsavedChangesDialog()).toBeNull();

		await pressBack();
		await vi.waitFor(() => expect(unsavedChangesDialog()).not.toBeNull());
		await historyComesToRest();
		answer(DIALOG_CANCEL_LABEL);

		await vi.waitFor(() => expect(unsavedChangesDialog()).toBeNull());
		expect(location.pathname).toBe('/album/a1/s1');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe(UNSAVED_LYRICS);
	});

	it('leaves for the album on Discard from the Back that leaves the song', async () => {
		await jumpToTake(SOURCE_TAKE_ID);
		await historyComesToRest();
		await pressBack();
		await pressBack();
		await vi.waitFor(() => expect(unsavedChangesDialog()).not.toBeNull());
		await historyComesToRest();

		answer(EDITOR_UNSAVED_DISCARD_LABEL);

		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());
		expect(location.pathname).toBe('/album/a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('still asks on a Back onto an entry of another song, and Cancel keeps that song and its draft', async () => {
		discardDraft();
		const other = song({ ...TIDE_DEFAULTS, id: 's2', slug: 's2', album_id: 'a2' });
		await selectSong('s2', other);
		await historyComesToRest();
		loadSongData(other);
		setDraftLyrics(UNSAVED_LYRICS);

		await pressBack();
		await vi.waitFor(() => expect(unsavedChangesDialog()).not.toBeNull());
		await historyComesToRest();
		answer(DIALOG_CANCEL_LABEL);

		await vi.waitFor(() => expect(unsavedChangesDialog()).toBeNull());
		expect(get(selectedSongId)).toBe('s2');
		expect(get(editLyrics)).toBe(UNSAVED_LYRICS);
	});
});
