import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import {
	LIBRARY_RETRY_LABEL,
	PLAYING_MARK_LABEL,
	RAIL_LIBRARY_LOAD_ERROR,
	UNREACHABLE_RELOAD_DELAYS_MS
} from '#lib/constants.ts';
import { LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { openCollection } from '#lib/stores/collection.ts';
import { librarySurface, resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import {
	albumList,
	allAlbumsLoad,
	resetLibraryDataForTests,
	songList
} from '#lib/stores/libraryData.ts';
import { railTreeQuery } from '#lib/stores/librarySearch.ts';
import { resetLibraryOrderForTests } from '#lib/stores/libraryOrder.ts';
import { chooseLibraryWallOrder } from '#lib/stores/ui.ts';
import { fetchLibraryListen } from '#lib/api/library.ts';
import { closeNowPlaying, selectedSongId, setShuffle } from '#lib/stores/player.ts';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import { pendingDirtyNavigation } from '#lib/stores/navigation.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { pressBack } from '#lib/test-utils/library-history.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import {
	albumsPage,
	buildAlbum as album,
	buildGeneration as generation,
	buildSong as song,
	createComponentMount,
	findElementByRoleAndName,
	lastPlayedPage,
	railRevealsSettled,
	recordRailReveals,
	revealedTitles,
	requireButtonContainingText,
	requireElement,
	songsPage
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('#lib/api/library.ts', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('#lib/api/albums.ts', async () =>
	(await import('./rail-test-fixtures')).railAlbumsApiMock()
);
vi.mock('#lib/api/songs.ts', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
const fetchAlbums = vi.fn();
const fetchSongs = vi.fn();
vi.mock('#lib/api/client.ts', async () => {
	const { railClientApiMock } = await import('./rail-test-fixtures');
	return railClientApiMock({
		fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
		fetchSongs: (...args: unknown[]) => fetchSongs(...args)
	});
});

import RailLibraryGroup from './RailLibraryGroup.svelte';

const { render, cleanup } = createComponentMount(RailLibraryGroup);

beforeEach(async () => {
	localStorage.clear();
	chooseLibraryWallOrder('title');
	resetLibraryOrderForTests();
	resetLibraryContextForTests();
	fetchAlbums.mockClear().mockResolvedValue(albumsPage());
	fetchSongs.mockClear().mockResolvedValue(songsPage());
	resetLibraryDataForTests();
	albumList.set([album()]);
	songList.set([
		song({ id: 's1', title: 'Tide', track_number: 1 }),
		song({ id: 's2', title: 'Ebb', track_number: 2 })
	]);
	selectedSongId.set(null);
	railTreeQuery.set('');
	setShuffle(false);
	closeNowPlaying();
	// The default surface, browse, stands on the Library's address.
	await goto(resolve(LIBRARY_ROUTE_PATH));
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
	});
});

afterEach(async () => {
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	setShuffle(false);
	closeNowPlaying();
	await cleanup();
	discardDraft();
	pendingDirtyNavigation.set(null);
	openCollection.set(null);
	resetLibraryContextForTests();
	resetConnectivityForTests();
	railTreeQuery.set('');
	vi.useRealTimers();
});

function showAlbumDetail(albumId: string): void {
	openCollection.set({ kind: 'album', id: albumId });
	librarySurface.set('detail');
}

describe('RailLibraryGroup', () => {
	it.each([
		{ status: 'idle', count: undefined, rows: 2, query: '' },
		{ status: 'loading', count: undefined, rows: 2, query: '' },
		{ status: 'unreachable', count: undefined, rows: 2, query: '' },
		{ status: 'error', count: undefined, rows: 2, query: '' },
		{ status: 'ready', count: '2', rows: 2, query: '' },
		{ status: 'ready', count: '0', rows: 0, query: '' },
		{ status: 'ready', count: '2', rows: 1, query: 'Other' }
	] as const)(
		'1160-F30-count 1160-F30-filter: $status total $count with $rows rows ($query)',
		async ({ status, count, rows, query }) => {
			fetchAlbums.mockReturnValue(new Promise(() => {}));
			const target = await render();
			albumList.set(count === '0' ? [] : [album(), album({ id: 'a2', title: 'Other' })]);
			allAlbumsLoad.set({ status, error: null });
			railTreeQuery.set(query);
			await tick();
			expect(target.querySelector('.group-title')?.textContent?.trim()).toBe('Library');
			expect(target.querySelector('.meta')?.textContent).toBe(count);
			expect(target.querySelectorAll('.album-label')).toHaveLength(rows);
		}
	);

	it('#1354 rule 40: the arrow folds the LIBRARY group without navigating', async () => {
		librarySurface.set('detail');
		const target = await render();
		const arrow = requireElement<HTMLButtonElement>(target, 'button.disclose');
		arrow.click();
		await tick();
		expect(arrow.getAttribute('aria-expanded')).toBe('true');
		expect(get(librarySurface)).toBe('detail');
	});

	it('#1354 rule 40: the word Library opens the album covers and leaves the fold alone', async () => {
		librarySurface.set('detail');
		const target = await render();
		const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
		expect(word.getAttribute('href')).toBe(LIBRARY_ROUTE_PATH);
		expect(word.textContent).toContain('Library');

		word.click();
		await vi.waitFor(() => expect(get(librarySurface)).toBe('browse'));
	});

	it('#1354 rule 40 (D1): on the Library page its group is the current page and unfolded, until the arrow folds it', async () => {
		const target = await render();
		const arrow = requireElement<HTMLButtonElement>(target, 'button.disclose');
		const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
		expect(arrow.getAttribute('aria-expanded')).toBe('true');
		expect(word.getAttribute('aria-current')).toBe('page');

		arrow.click();
		await tick();
		expect(arrow.getAttribute('aria-expanded')).toBe('false');
		expect(word.getAttribute('aria-current')).toBe('page');

		librarySurface.set('detail');
		await tick();
		expect(word.hasAttribute('aria-current')).toBe(false);
	});

	it.each([
		{ address: LIBRARY_ROUTE_PATH, current: true },
		{ address: '/settings', current: false },
		{ address: '/playlists', current: false },
		{ address: '/?song=s1', current: false }
	] as const)(
		'defect:#1523: with the surface still on browse, the word Library is current: $current and its group is unfolded at $address',
		async ({ address, current }) => {
			await goto(resolve(address));
			const target = await render();

			expect(
				requireElement<HTMLButtonElement>(target, 'button.disclose').getAttribute('aria-expanded')
			).toBe('true');
			const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
			expect(word.hasAttribute('aria-current')).toBe(current);
			expect(get(librarySurface)).toBe('browse');
		}
	);

	it('defect:#1523: the word Library is current again after Back from Settings, with no reload', async () => {
		const target = await render();
		const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
		expect(word.getAttribute('aria-current')).toBe('page');

		await goto(resolve('/settings'));
		await tick();
		expect(word.hasAttribute('aria-current')).toBe(false);

		await pressBack();
		expect(word.getAttribute('aria-current')).toBe('page');
	});

	it.each(['home', 'playlists'] as const)(
		'1354_rule_31: the word Library is not the current page while %s shows',
		async (surface) => {
			librarySurface.set(surface);
			const target = await render();
			const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
			expect(word.hasAttribute('aria-current')).toBe(false);
		}
	);

	it('#1354 rule 40: the Library list carries no All albums row', async () => {
		const target = await render();
		expect(target.textContent).not.toContain('All albums');
		expect(target.querySelectorAll('.album-list > li')).toHaveLength(1);
	});

	it('loads every album on mount regardless of the current route', async () => {
		await render();
		await vi.waitFor(() => expect(fetchAlbums).toHaveBeenCalled());
	});

	it('opens on click and lists every album with its own song count', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield', song_count: 5 })
		]);
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const albumRows = target.querySelectorAll('.album-label .row-title');
		expect(Array.from(albumRows).map((row) => row.textContent)).toEqual(['Anfield', 'Nachtstrom']);
		const counts = target.querySelectorAll('.album-label .row-meta');
		expect(Array.from(counts).map((row) => row.textContent)).toEqual(['5', '2']);
	});

	it('lists the albums in the order the wall is switched to, A–Z by natural title first', async () => {
		albumList.set([
			album({ id: 'filler-10', title: 'Filler 10' }),
			album({ id: 'vernissage', title: 'Vernissage' }),
			album({ id: 'filler-2', title: 'Filler 2' }),
			album({ id: 'afterglow', title: 'Afterglow' })
		]);
		vi.mocked(fetchLibraryListen).mockResolvedValue(
			lastPlayedPage('album', ['vernissage', 'filler-2'])
		);
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const albumTitles = () =>
			Array.from(target.querySelectorAll('.album-label .row-title')).map((row) => row.textContent);

		expect(albumTitles()).toEqual(['Afterglow', 'Filler 2', 'Filler 10', 'Vernissage']);

		chooseLibraryWallOrder('played');
		await vi.waitFor(() =>
			expect(albumTitles()).toEqual(['Vernissage', 'Filler 2', 'Afterglow', 'Filler 10'])
		);
	});

	it('1354_rule_8: lists no album while Last played is chosen and Listen has not answered', async () => {
		albumList.set([
			album({ id: 'afterglow', title: 'Afterglow' }),
			album({ id: 'v', title: 'Vernissage' })
		]);
		const listen = Promise.withResolvers<ReturnType<typeof lastPlayedPage>>();
		vi.mocked(fetchLibraryListen).mockReturnValue(listen.promise);
		chooseLibraryWallOrder('played');
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const albumTitles = () =>
			Array.from(target.querySelectorAll('.album-label .row-title')).map((row) => row.textContent);

		expect(albumTitles()).toEqual([]);

		listen.resolve(lastPlayedPage('album', ['v']));
		await vi.waitFor(() => expect(albumTitles()).toEqual(['Vernissage', 'Afterglow']));
	});

	it('narrows known albums and songs, while keeping the open album visible', async () => {
		albumList.set([
			album({ id: 'a-open', title: 'Anfield' }),
			album({ id: 'a-match', title: 'Other album' }),
			album({ id: 'a-hidden', title: 'Quiet room' })
		]);
		songList.set([
			song({ id: 's-open', album_id: 'a-open', title: 'Tide', track_number: 1 }),
			song({ id: 's-match', album_id: 'a-match', title: 'Stadion', track_number: 1 })
		]);
		showAlbumDetail('a-open');
		railTreeQuery.set('stadion');

		const target = await render();
		await tick();

		expect(target.textContent).toContain('Anfield');
		expect(target.textContent).toContain('Other album');
		expect(target.textContent).toContain('Stadion');
		expect(target.textContent).not.toContain('Quiet room');
		expect(
			requireElement<HTMLButtonElement>(target, '.album-label').getAttribute('aria-expanded')
		).toBe('true');
	});

	it('shows each album cover in the rail and keeps initials as its fallback', async () => {
		albumList.set([
			album({
				id: 'a1',
				title: 'Nachtstrom',
				cover: { card: '/covers/nachtstrom.jpg', detail: '/covers/nachtstrom-detail.jpg' }
			}),
			album({ id: 'a2', title: 'Anfield', cover: null })
		]);
		const target = await render();

		const cover = requireElement<HTMLImageElement>(target, '.album-art img');
		expect(cover.src).toContain('/covers/nachtstrom.jpg');
		expect(cover.alt).toBe('Album Nachtstrom');
		expect(target.querySelectorAll('.album-art img')).toHaveLength(1);
		expect(target.querySelectorAll('.album-art span')).toHaveLength(1);
		expect(target.querySelector('.album-art span')?.textContent).toBe('AN');
	});

	it('does not render tracks for a collapsed album', async () => {
		const target = await render();
		expect(target.querySelectorAll('.row-sub2')).toHaveLength(0);
	});

	it('keeps each collapsed album row connected to its empty track container', async () => {
		const target = await render();
		const row = requireElement<HTMLButtonElement>(target, '.album-label');
		const controlledId = row.getAttribute('aria-controls');

		expect(controlledId).toBe('rail-library-album-a1');
		expect(target.querySelector(`#${controlledId}`)?.getAttribute('data-open')).toBe('false');
		expect((target.querySelector(`#${controlledId}`) as HTMLElement).inert).toBe(true);
	});

	it('renders a newly opened album tracks in track order', async () => {
		songList.set([
			song({ id: 's1', title: 'Ebb', track_number: 2 }),
			song({ id: 's2', title: 'Tide', track_number: 1 })
		]);
		const target = await render();
		requireElement<HTMLButtonElement>(target, '.album-label').click();
		await tick();

		const rows = target.querySelectorAll('.row-sub2 .row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
	});

	it('pre-expands the open album and marks its selected track, in track order', async () => {
		showAlbumDetail('a1');
		selectedSongId.set('s2');
		const target = await render();
		const albumRow = requireElement<HTMLButtonElement>(target, '.album-label');
		expect(albumRow.getAttribute('aria-expanded')).toBe('true');

		const rows = target.querySelectorAll('.row-sub2 .row-title');
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
		const active = target.querySelector('.row-sub2.row-active .row-title');
		expect(active?.textContent).toBe('Ebb');
	});

	it('shows a take/pick summary per track', async () => {
		showAlbumDetail('a1');
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 0, generations: [] }),
			song({
				id: 's2',
				title: 'Ebb',
				track_number: 2,
				generation_count: 3,
				generations: [generation({ id: 'g1', is_picked: true })]
			})
		]);
		const target = await render();
		const meta = Array.from(target.querySelectorAll('.row-sub2 .row-meta')).map(
			(el) => el.textContent
		);
		expect(meta).toEqual(['—', '3 takes · pick']);
	});

	it('1354_rule_11: shows nothing to hear for a track of only archived takes, and no pick for an archived one', async () => {
		showAlbumDetail('a1');
		songList.set([
			song({
				id: 's1',
				title: 'Tide',
				track_number: 1,
				generation_count: 1,
				generations: [generation({ id: 'g1', is_picked: true, is_archived: true })]
			}),
			song({
				id: 's2',
				title: 'Ebb',
				track_number: 2,
				generation_count: 2,
				generations: [
					generation({ id: 'g2', is_picked: true, is_archived: true }),
					generation({ id: 'g3' })
				]
			})
		]);
		const target = await render();
		const meta = Array.from(target.querySelectorAll('.row-sub2 .row-meta')).map(
			(el) => el.textContent
		);
		expect(meta).toEqual(['—', '2 takes']);
	});

	it('selects a track when its row is clicked', async () => {
		showAlbumDetail('a1');
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 0 }),
			song({ id: 's2', title: 'Ebb', track_number: 2, generation_count: 0 })
		]);
		const target = await render();
		const rows = target.querySelectorAll<HTMLButtonElement>('.row-sub2');
		rows[1]?.click();
		await tick();
		await vi.waitFor(() => expect(get(selectedSongId)).toBe('s2'));
	});

	it('opens an album and loads its songs on demand with its one row target', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Anfield' }),
			album({ id: 'a2', title: 'Nachtstrom' })
		]);
		songList.set([]);
		fetchSongs.mockImplementation((albumId: string) =>
			Promise.resolve(
				songsPage({
					items:
						albumId === 'a2'
							? [song({ id: 's9', title: 'Kickoff', album_id: 'a2', track_number: 1 })]
							: []
				})
			)
		);
		const target = await render();
		const albumRows = target.querySelectorAll<HTMLButtonElement>('.album-label');
		albumRows[1]?.click();
		await tick();
		expect(albumRows[1]?.getAttribute('aria-expanded')).toBe('true');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
		await vi.waitFor(() => expect(target.textContent).toContain('Kickoff'));
	});

	it('loads no songs of the album the wall keeps open, and expands and loads it once its detail opens', async () => {
		albumList.set([album({ id: 'a2', title: 'Nachtstrom' })]);
		songList.set([]);
		fetchSongs.mockResolvedValue(
			songsPage({ items: [song({ id: 's9', title: 'Kickoff', album_id: 'a2' })] })
		);
		const target = await render();

		openCollection.set({ kind: 'album', id: 'a2' });
		await tick();
		expect(fetchSongs).not.toHaveBeenCalled();

		librarySurface.set('detail');
		await tick();
		expect(
			requireElement<HTMLButtonElement>(target, '.album-label').getAttribute('aria-expanded')
		).toBe('true');
		await vi.waitFor(() => expect(target.textContent).toContain('Kickoff'));
	});

	it('holds an album row for the unsaved-changes dialog while the open song has a dirty draft (issue #1143)', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Anfield' }),
			album({ id: 'a2', title: 'Nachtstrom' })
		]);
		showAlbumDetail('a1');
		selectedSongId.set('s1');
		loadSongData(song({ id: 's1', title: 'Tide' }));
		setDraftLyrics('unsaved edit');
		const target = await render();

		target.querySelectorAll<HTMLButtonElement>('.album-label')[1]?.click();
		await tick();

		expect(get(pendingDirtyNavigation)).not.toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(selectedSongId)).toBe('s1');
	});

	it('navigates into the album and expands it when its label is clicked', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Anfield' }),
			album({ id: 'a2', title: 'Nachtstrom' })
		]);
		const target = await render();
		const labels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		labels[1]?.click();
		await tick();
		await Promise.resolve();

		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
		expect(labels[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('has no separate album disclosure: the only album button navigates and expands', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
		const target = await render();
		const row = requireElement<HTMLButtonElement>(target, '.album-label');

		row.click();
		await tick();
		await Promise.resolve();

		expect(target.querySelector('.album-disclose')).toBeNull();
		expect(row.getAttribute('aria-expanded')).toBe('true');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('closes the previously open album when a different album is opened by its label', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
		]);
		const target = await render();
		const labels = target.querySelectorAll<HTMLButtonElement>('.album-label');
		labels[0]?.click();
		await tick();
		await Promise.resolve();
		expect(labels[0]?.getAttribute('aria-expanded')).toBe('true');

		labels[1]?.click();
		await tick();
		await Promise.resolve();
		expect(labels[0]?.getAttribute('aria-expanded')).toBe('false');
		expect(labels[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('keeps an already open album expanded when its row is opened again', async () => {
		showAlbumDetail('a1');
		const target = await render();
		const albumRow = requireElement<HTMLButtonElement>(target, '.album-label');
		expect(albumRow.getAttribute('aria-expanded')).toBe('true');

		albumRow.click();
		await tick();
		expect(albumRow.getAttribute('aria-expanded')).toBe('true');
	});

	it.each([
		{ currentSongId: 's1', status: 'playing' as const, markedTrack: 'Tide' },
		{ currentSongId: 's2', status: 'playing' as const, markedTrack: 'Ebb' },
		{ currentSongId: 's2', status: 'paused' as const, markedTrack: 'Ebb' }
	])(
		'shows a playing marker only for the current track while it plays or is paused',
		async ({ currentSongId, status, markedTrack }) => {
			showAlbumDetail('a1');
			songList.set([
				song({ id: 's1', title: 'Tide', track_number: 1 }),
				song({ id: 's2', title: 'Ebb', track_number: 2 })
			]);
			audioPlayer.current = {
				songId: currentSongId,
				generation: generation({ id: `g-${currentSongId}`, song_id: currentSongId })
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await render();

			for (const trackTitle of ['Tide', 'Ebb']) {
				const track = requireButtonContainingText(target, trackTitle);
				expect(findElementByRoleAndName(track, 'img', PLAYING_MARK_LABEL) !== null).toBe(
					trackTitle === markedTrack
				);
			}
		}
	);

	it('summarizes a single take in the singular, with no pick suffix', async () => {
		showAlbumDetail('a1');
		songList.set([
			song({ id: 's1', title: 'Tide', track_number: 1, generation_count: 1, generations: [] })
		]);
		const target = await render();
		expect(target.querySelector('.row-sub2 .row-meta')?.textContent).toBe('1 take');
	});

	it('shows a retry-able error instead of a silent empty library when the load fails', async () => {
		albumList.set([]);
		fetchAlbums.mockRejectedValueOnce(new ApiError(503, 'Backend unreachable', '/api/albums'));
		const target = await render();

		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		await vi.waitFor(() => expect(toggle.getAttribute('aria-expanded')).toBe('true'));
		const panel = requireElement<HTMLDivElement>(target, '#rail-library-group');
		expect(panel.inert).toBe(false);
		expect(requireElement(target, '[role="alert"]').textContent).toBe('Backend unreachable');

		fetchAlbums.mockResolvedValueOnce(
			albumsPage({ items: [album({ id: 'a9', title: 'Recovered' })] })
		);
		requireButtonContainingText(target, LIBRARY_RETRY_LABEL).click();

		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).toBeNull());
		expect(requireButtonContainingText(target, 'Recovered')).toBeInstanceOf(HTMLButtonElement);
	});

	it('offline, keeps the albums it shows with no failure of its own and loads again once back online', async () => {
		reportResourceStreamReachable(false);
		fetchAlbums.mockRejectedValueOnce(
			new NetworkError('/api/albums', new TypeError('Failed to fetch'))
		);
		const target = await render();
		await vi.waitFor(() => expect(get(allAlbumsLoad).status).toBe('unreachable'));
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();

		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(target.textContent).not.toContain(LIBRARY_RETRY_LABEL);
		expect(target.querySelectorAll('.album-label')).toHaveLength(1);

		fetchAlbums.mockResolvedValueOnce(
			albumsPage({ items: [album(), album({ id: 'a9', title: 'Recovered' })] })
		);
		reportResourceStreamReachable(true);

		await vi.waitFor(() =>
			expect(requireButtonContainingText(target, 'Recovered')).toBeInstanceOf(HTMLButtonElement)
		);
	});

	it('offline with nothing loaded yet, claims no album count until the albums have loaded', async () => {
		reportResourceStreamReachable(false);
		albumList.set([]);
		fetchAlbums.mockRejectedValueOnce(
			new NetworkError('/api/albums', new TypeError('Failed to fetch'))
		);
		const target = await render();
		await vi.waitFor(() => expect(get(allAlbumsLoad).status).toBe('unreachable'));
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();

		expect(target.querySelector('.meta')).toBeNull();

		fetchAlbums.mockResolvedValueOnce(albumsPage({ items: [] }));
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelector('.meta')?.textContent).toBe('0'));
	});

	it('while no strip shows, loads again on a bounded backoff and then names the failure with its Retry', async () => {
		vi.useFakeTimers();
		albumList.set([]);
		fetchAlbums.mockRejectedValue(
			new NetworkError('/api/albums', new TypeError('Failed to fetch'))
		);
		const target = await render();
		await vi.advanceTimersByTimeAsync(0);
		expect(target.querySelector('[role="alert"]')).toBeNull();

		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		expect(fetchAlbums).toHaveBeenCalledTimes(1 + UNREACHABLE_RELOAD_DELAYS_MS.length);
		expect(requireElement(target, '[role="alert"]').textContent).toBe(RAIL_LIBRARY_LOAD_ERROR);
		fetchAlbums.mockResolvedValueOnce(
			albumsPage({ items: [album({ id: 'a9', title: 'Recovered' })] })
		);
		requireButtonContainingText(target, LIBRARY_RETRY_LABEL).click();
		await vi.advanceTimersByTimeAsync(0);

		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(requireButtonContainingText(target, 'Recovered')).toBeInstanceOf(HTMLButtonElement);
	});
});

describe('RailLibraryGroup keeps the open album in view', () => {
	const anfield = album({ id: 'a1', title: 'Anfield' });
	const lunarStatic = album({ id: 'a2', title: 'Lunar Static' });

	it.each([
		{ reducedMotion: false, behavior: 'smooth' },
		{ reducedMotion: true, behavior: 'auto' }
	] as const)(
		'scrolls the open album row into view once a reload lists it ($behavior)',
		async ({ reducedMotion, behavior }) => {
			const reveals = recordRailReveals({ reducedMotion });
			albumList.set([]);
			fetchAlbums.mockResolvedValue(albumsPage({ items: [anfield, lunarStatic], total: 2 }));
			showAlbumDetail('a2');

			await render();

			await vi.waitFor(() =>
				expect(reveals).toEqual([
					{ title: 'Lunar Static', options: { block: 'nearest', behavior } }
				])
			);
		}
	);

	it('scrolls each album opened after it into view, and not again while it stays open', async () => {
		const reveals = recordRailReveals();
		albumList.set([anfield, lunarStatic]);
		showAlbumDetail('a1');
		await render();
		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Anfield']));

		showAlbumDetail('a2');
		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Anfield', 'Lunar Static']));
		showAlbumDetail('a1');
		await vi.waitFor(() =>
			expect(revealedTitles(reveals)).toEqual(['Anfield', 'Lunar Static', 'Anfield'])
		);

		albumList.set([{ ...anfield, song_count: 3 }, lunarStatic]);
		await railRevealsSettled();
		expect(revealedTitles(reveals)).toEqual(['Anfield', 'Lunar Static', 'Anfield']);
	});

	it('scrolls nothing while search results replace the tree, and the album a result opened once the search clears', async () => {
		const reveals = recordRailReveals();
		albumList.set([anfield, lunarStatic]);
		railTreeQuery.set('lunar');
		await render();

		showAlbumDetail('a2');
		await railRevealsSettled();
		expect(reveals).toEqual([]);

		railTreeQuery.set('');

		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Lunar Static']));
	});

	it('scrolls nothing while the wall keeps an album in the closed group, and its row once a cover opens it', async () => {
		const reveals = recordRailReveals();
		albumList.set([anfield, lunarStatic]);
		openCollection.set({ kind: 'album', id: 'a2' });
		await render();
		await railRevealsSettled();
		expect(reveals).toEqual([]);

		librarySurface.set('detail');

		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Lunar Static']));
	});

	it('scrolls an album row into view only once its group has finished opening, and not if another album opened meanwhile', async () => {
		let finishOpening!: () => void;
		const reveals = recordRailReveals({
			animatingUntil: new Promise<void>((resolve) => (finishOpening = resolve))
		});
		albumList.set([anfield, lunarStatic]);
		await render();

		showAlbumDetail('a2');
		await railRevealsSettled();
		expect(reveals).toEqual([]);

		showAlbumDetail('a1');
		finishOpening();
		await railRevealsSettled();

		expect(revealedTitles(reveals)).toEqual(['Anfield']);
	});
});
