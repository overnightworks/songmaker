import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { NetworkError } from '#lib/api/fetch.ts';
import { PLAYING_MARK_LABEL } from '#lib/constants.ts';
import { PLAYLISTS_ROUTE_PATH } from '#lib/routes/addresses.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { openCollection, setOpenCollection } from '#lib/stores/collection.ts';
import { librarySurface, resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import {
	closeNowPlaying,
	nowPlayingOpen,
	nowPlayingPanel,
	queueContext,
	selectedSongId
} from '#lib/stores/player.ts';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import { pendingDirtyNavigation } from '#lib/stores/navigation.ts';
import {
	playlistList,
	resetPlaylistsForTests,
	selectedPlaylistDetail
} from '#lib/stores/playlists.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { pressBack } from '#lib/test-utils/library-history.ts';
import { railTreeQuery } from '#lib/stores/librarySearch.ts';
import { resetLibraryOrderForTests } from '#lib/stores/libraryOrder.ts';
import { chooseLibraryWallOrder } from '#lib/stores/ui.ts';
import { fetchLibraryListen } from '#lib/api/library.ts';
import {
	buildPlaylist as playlist,
	buildPlaylistDetail as detail,
	buildPlaylistEntry as entry,
	buildSong as song,
	createComponentMount,
	findElementByRoleAndName,
	lastPlayedPage,
	recordRailReveals,
	requireElement,
	revealedTitles
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
const fetchPlaylists = vi.fn().mockResolvedValue([]);
const fetchPlaylist = vi.fn();
vi.mock('#lib/api/client.ts', async () => {
	const { railClientApiMock } = await import('./rail-test-fixtures');
	return railClientApiMock({
		fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
		fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args)
	});
});

import RailPlaylistsGroup from './RailPlaylistsGroup.svelte';

const { render, cleanup } = createComponentMount(RailPlaylistsGroup);

beforeEach(() => {
	localStorage.clear();
	chooseLibraryWallOrder('title');
	resetLibraryOrderForTests();
	resetLibraryContextForTests();
	fetchPlaylists.mockClear().mockResolvedValue([]);
	fetchPlaylist.mockReset();
	playlistList.set([playlist()]);
	railTreeQuery.set('');
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
		audioPlayer.status = 'playing';
	});
	vi.spyOn(audioPlayer, 'preload').mockImplementation(() => {});
});

afterEach(async () => {
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	await cleanup();
	discardDraft();
	pendingDirtyNavigation.set(null);
	selectedSongId.set(null);
	resetPlaylistsForTests();
	resetLibraryContextForTests();
	resetConnectivityForTests();
	railTreeQuery.set('');
});

describe('RailPlaylistsGroup', () => {
	it('shows the PLAYLISTS group with its icon and the current playlist count, collapsed with no playlist open', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(target.querySelector('.group-title')?.textContent?.trim()).toBe('Playlists');
		expect(target.querySelector('.meta')?.textContent).toBe('1');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('shows no playlist count while the playlists could not be loaded, and loads them once back online', async () => {
		playlistList.set([]);
		reportResourceStreamReachable(false);
		fetchPlaylists.mockRejectedValueOnce(
			new NetworkError('/api/playlists', new TypeError('Failed to fetch'))
		);
		const target = await render();
		await vi.waitFor(() => expect(fetchPlaylists).toHaveBeenCalledOnce());
		await tick();

		expect(target.querySelector('.meta')).toBeNull();

		fetchPlaylists.mockResolvedValueOnce([playlist({ id: 'p1', title: 'Night Drive' })]);
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelector('.meta')?.textContent).toBe('1'));
	});

	it('shows 0 for a library that really has no playlists', async () => {
		playlistList.set([]);
		const target = await render();

		await vi.waitFor(() => expect(target.querySelector('.meta')?.textContent).toBe('0'));
	});

	it('#1354 rule 40: the arrow folds the PLAYLISTS group without navigating', async () => {
		librarySurface.set('detail');
		const target = await render();
		const arrow = requireElement<HTMLButtonElement>(target, 'button.disclose');
		arrow.click();
		await tick();
		expect(arrow.getAttribute('aria-expanded')).toBe('true');
		expect(get(librarySurface)).toBe('detail');
	});

	it('#1354 rule 40: the word Playlists opens the Playlists covers', async () => {
		const target = await render();
		const word = requireElement<HTMLAnchorElement>(target, 'a.page-link');
		expect(word.getAttribute('href')).toBe('/playlists');
		expect(word.textContent).toContain('Playlists');

		word.click();
		await vi.waitFor(() => expect(get(librarySurface)).toBe('playlists'));
	});

	it('#1354 rule 40 (D3): on the Playlists page its group is the current page and unfolded', async () => {
		librarySurface.set('playlists');
		await goto(resolve(PLAYLISTS_ROUTE_PATH));
		const target = await render();
		expect(
			requireElement<HTMLButtonElement>(target, 'button.disclose').getAttribute('aria-expanded')
		).toBe('true');
		expect(requireElement(target, 'a.page-link').getAttribute('aria-current')).toBe('page');

		librarySurface.set('browse');
		await tick();
		expect(requireElement(target, 'a.page-link').hasAttribute('aria-current')).toBe(false);
	});

	it.each([
		{ address: PLAYLISTS_ROUTE_PATH, current: true },
		{ address: '/settings', current: false },
		{ address: '/library', current: false },
		{ address: '/', current: false }
	] as const)(
		'defect:#1523: with the surface still on playlists, the word Playlists is current: $current and its group is unfolded at $address',
		async ({ address, current }) => {
			librarySurface.set('playlists');
			await goto(resolve(address));
			const target = await render();

			expect(
				requireElement<HTMLButtonElement>(target, 'button.disclose').getAttribute('aria-expanded')
			).toBe('true');
			expect(requireElement(target, 'a.page-link').hasAttribute('aria-current')).toBe(current);
			expect(get(librarySurface)).toBe('playlists');
		}
	);

	it('defect:#1523: the word Playlists is current again after Back from Settings, with no reload', async () => {
		librarySurface.set('playlists');
		await goto(resolve(PLAYLISTS_ROUTE_PATH));
		const target = await render();
		const word = requireElement(target, 'a.page-link');
		expect(word.getAttribute('aria-current')).toBe('page');

		await goto(resolve('/settings'));
		await tick();
		expect(word.hasAttribute('aria-current')).toBe(false);

		await pressBack();
		expect(word.getAttribute('aria-current')).toBe('page');
	});

	it('lists the playlists in the order the wall is switched to, A–Z by natural title first', async () => {
		playlistList.set([
			playlist({ id: 'mix-10', title: 'Mix 10' }),
			playlist({ id: 'night', title: 'night drive' }),
			playlist({ id: 'mix-2', title: 'Mix 2' })
		]);
		fetchPlaylists.mockResolvedValue(get(playlistList));
		vi.mocked(fetchLibraryListen).mockResolvedValue(
			lastPlayedPage('playlist', ['night', 'mix-10'])
		);
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const playlistTitles = () =>
			Array.from(target.querySelectorAll('.playlist-label .row-title')).map(
				(row) => row.textContent
			);

		expect(playlistTitles()).toEqual(['Mix 2', 'Mix 10', 'night drive']);

		chooseLibraryWallOrder('played');
		await vi.waitFor(() => expect(playlistTitles()).toEqual(['night drive', 'Mix 10', 'Mix 2']));
	});

	it('1354_rule_8: lists no playlist while Last played is chosen and Listen has not answered', async () => {
		playlistList.set([
			playlist({ id: 'mix', title: 'Mix' }),
			playlist({ id: 'night', title: 'night drive' })
		]);
		fetchPlaylists.mockResolvedValue(get(playlistList));
		const listen = Promise.withResolvers<ReturnType<typeof lastPlayedPage>>();
		vi.mocked(fetchLibraryListen).mockReturnValue(listen.promise);
		chooseLibraryWallOrder('played');
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const playlistTitles = () =>
			Array.from(target.querySelectorAll('.playlist-label .row-title')).map(
				(row) => row.textContent
			);

		expect(playlistTitles()).toEqual([]);

		listen.resolve(lastPlayedPage('playlist', ['night']));
		await vi.waitFor(() => expect(playlistTitles()).toEqual(['night drive', 'Mix']));
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
		expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Favorites', 'Night Drive']);
		const counts = target.querySelectorAll('.playlist-label .row-meta');
		expect(Array.from(counts).map((row) => row.textContent)).toEqual(['12', '2']);
	});

	it('shows each playlist mosaic while keeping the whole row as its navigation target', async () => {
		playlistList.set([
			playlist({
				id: 'p1',
				title: 'Night Drive',
				album_covers: [
					{ card: '/covers/night.jpg', detail: '/covers/night-detail.jpg' },
					{ card: '/covers/drive.jpg', detail: '/covers/drive-detail.jpg' }
				]
			})
		]);
		fetchPlaylist.mockResolvedValue(detail({ id: 'p1', title: 'Night Drive' }));
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();

		const row = requireElement<HTMLButtonElement>(target, '.playlist-label');
		expect(row.querySelectorAll('.playlist-cover-cell')).toHaveLength(4);
		expect(row.querySelectorAll('.playlist-cover-cell img')).toHaveLength(2);
		expect(row.querySelectorAll('.playlist-cover-initials')).toHaveLength(2);
		expect(row.querySelector('.playlist-cover-initials')?.textContent).toBe('ND');
		expect(row.querySelectorAll('button')).toHaveLength(0);

		row.click();
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' }));
	});

	it('narrows playlists by title without hiding the open playlist', async () => {
		playlistList.set([
			playlist({ id: 'p-open', title: 'Night Drive' }),
			playlist({ id: 'p-match', title: 'Stadium nights' }),
			playlist({ id: 'p-hidden', title: 'Quiet hour' })
		]);
		setOpenCollection({ kind: 'playlist', id: 'p-open' });
		railTreeQuery.set('stadium');

		const target = await render();
		await tick();

		expect(target.textContent).toContain('Night Drive');
		expect(target.textContent).toContain('Stadium nights');
		expect(target.textContent).not.toContain('Quiet hour');
	});

	const tide = entry({ id: 'pe1', song_title: 'Tide', generation_id: 'g1', mp3_path: 'tide.mp3' });
	const tideThenEbb = [
		tide,
		entry({ id: 'pe2', position: 1, song_title: 'Ebb', generation_id: 'g2', mp3_path: 'ebb.mp3' })
	];
	const tideTwice = [tide, entry({ ...tide, id: 'pe3', position: 1 })];

	it.each([
		{ held: 'Tide, Ebb', entries: tideThenEbb, played: 0, status: 'playing', marks: [true, false] },
		{ held: 'Tide, Ebb', entries: tideThenEbb, played: 1, status: 'playing', marks: [false, true] },
		{ held: 'Tide, Ebb', entries: tideThenEbb, played: 1, status: 'paused', marks: [false, true] },
		{ held: 'Tide twice', entries: tideTwice, played: 1, status: 'playing', marks: [false, true] }
	] as const)(
		'marks only the entry played from its row ($held, row $played, $status)',
		async ({ entries, played, status, marks }) => {
			setOpenCollection({ kind: 'playlist', id: 'p1' });
			selectedPlaylistDetail.set(detail({ id: 'p1', entries: [...entries] }));
			const target = await render();
			const rows = Array.from(target.querySelectorAll<HTMLButtonElement>('.row-sub2'));

			rows[played].click();
			await tick();
			audioPlayer.status = status;
			await tick();

			expect(rows.map((row) => row.classList.contains('row-active'))).toEqual(
				entries.map((_, index) => index === played)
			);
			expect(
				rows.map((row) => findElementByRoleAndName(row, 'img', PLAYING_MARK_LABEL) !== null)
			).toEqual(marks);
		}
	);

	it('navigates into the playlist and marks it as the current page when its label is clicked', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Favorites' })
		]);
		fetchPlaylist.mockResolvedValue(detail({ id: 'p2', title: 'Favorites' }));
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();
		const labels = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		labels[0]?.click();
		await tick();
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p2' }));
		await tick();

		const rows = target.querySelectorAll<HTMLButtonElement>('.playlist-label');
		expect(rows[0]?.getAttribute('aria-current')).toBe('page');
	});

	it('scrolls the open playlist row into view once listed and each time another playlist opens', async () => {
		const reveals = recordRailReveals();
		playlistList.set([
			playlist({ id: 'p1', title: 'Morning Run' }),
			playlist({ id: 'p2', title: 'Night Drive' })
		]);
		setOpenCollection({ kind: 'playlist', id: 'p1' });
		librarySurface.set('detail');
		await render();
		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Morning Run']));

		setOpenCollection({ kind: 'playlist', id: 'p2' });

		await vi.waitFor(() => expect(revealedTitles(reveals)).toEqual(['Morning Run', 'Night Drive']));
	});

	it('holds a playlist row for the unsaved-changes dialog while the open song has a dirty draft (issue #1143)', async () => {
		playlistList.set([playlist({ id: 'p2', title: 'Favorites' })]);
		selectedSongId.set('s1');
		loadSongData(song({ id: 's1', title: 'Tide' }));
		setDraftLyrics('unsaved edit');
		const target = await render();
		requireElement<HTMLButtonElement>(target, 'button.disclose').click();
		await tick();

		requireElement<HTMLButtonElement>(target, '.playlist-label').click();
		await tick();

		expect(get(pendingDirtyNavigation)).not.toBeNull();
		expect(get(openCollection)).not.toEqual({ kind: 'playlist', id: 'p2' });
		expect(get(selectedSongId)).toBe('s1');
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
