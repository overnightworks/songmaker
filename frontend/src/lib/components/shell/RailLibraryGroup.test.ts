import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { ApiError } from '$lib/api/fetch';
import { LIBRARY_RETRY_LABEL, RAIL_PLAYING_MARKER_LABEL } from '$lib/constants';
import { openCollection } from '$lib/stores/collection';
import {
	libraryFilter,
	librarySurface,
	resetLibraryContextForTests
} from '$lib/stores/libraryContext';
import { albumList, allAlbumsLoad, songList } from '$lib/stores/libraryData';
import { closeNowPlaying, selectedSongId, setShuffle } from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import {
	albumsPage,
	buildAlbum as album,
	buildGeneration as generation,
	buildSong as song,
	createComponentMount,
	findElementByRoleAndName,
	requireButtonContainingText,
	requireElement,
	songsPage
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () => (await import('./rail-test-fixtures')).railNavigationMock());
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('$lib/api/library', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('$lib/api/albums', async () => (await import('./rail-test-fixtures')).railAlbumsApiMock());
vi.mock('$lib/api/songs', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
const fetchAlbums = vi.fn();
const fetchSongs = vi.fn();
vi.mock('$lib/api/client', async () => {
	const { railClientApiMock } = await import('./rail-test-fixtures');
	return railClientApiMock({
		fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
		fetchSongs: (...args: unknown[]) => fetchSongs(...args)
	});
});

import RailLibraryGroup from './RailLibraryGroup.svelte';

const { render, cleanup } = createComponentMount(RailLibraryGroup);

beforeEach(() => {
	localStorage.clear();
	resetLibraryContextForTests();
	fetchAlbums.mockClear().mockResolvedValue(albumsPage());
	fetchSongs.mockClear().mockResolvedValue(songsPage());
	allAlbumsLoad.set({ status: 'idle', error: null });
	albumList.set([album()]);
	songList.set([
		song({ id: 's1', title: 'Tide', track_number: 1 }),
		song({ id: 's2', title: 'Ebb', track_number: 2 })
	]);
	selectedSongId.set(null);
	setShuffle(false);
	closeNowPlaying();
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
	openCollection.set(null);
	resetLibraryContextForTests();
});

describe('RailLibraryGroup', () => {
	it('shows the LIBRARY group with its icon and the current album count, collapsed with no album open', async () => {
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(target.querySelector('.group-title')?.textContent?.trim()).toBe('Library');
		expect(target.querySelector('.meta')?.textContent).toBe('1');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('toggles the LIBRARY group without navigating when its label is clicked', async () => {
		librarySurface.set('detail');
		libraryFilter.set('playlists');
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		requireElement<HTMLSpanElement>(toggle, '.group-title').click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(get(libraryFilter)).toBe('playlists');
		expect(get(librarySurface)).toBe('detail');
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
		expect(Array.from(albumRows).map((row) => row.textContent)).toEqual(['Nachtstrom', 'Anfield']);
		const counts = target.querySelectorAll('.album-label .row-meta');
		expect(Array.from(counts).map((row) => row.textContent)).toEqual(['2', '5']);
	});

	it('puts All albums first and returns to the wall with the group closed', async () => {
		librarySurface.set('detail');
		const target = await render();
		const groupToggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		groupToggle.click();
		await tick();

		const allAlbums = requireElement<HTMLButtonElement>(
			target,
			'.album-list > li:first-child button'
		);
		expect(allAlbums.classList.contains('all-albums')).toBe(true);
		expect(allAlbums.textContent).toContain('All albums');
		expect(allAlbums.textContent).toContain('1');

		allAlbums.click();
		await vi.waitFor(() => expect(get(librarySurface)).toBe('browse'));
		await tick();
		expect(
			requireElement<HTMLButtonElement>(target, 'button.disclose').getAttribute('aria-expanded')
		).toBe('false');
		expect(localStorage.getItem('songmaker.rail-library-open')).toBe('false');
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
		openCollection.set({ kind: 'album', id: 'a1' });
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
		openCollection.set({ kind: 'album', id: 'a1' });
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

	it('selects a track when its row is clicked', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
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
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
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

	it('navigates into the album and expands it when its label is clicked', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
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
		openCollection.set({ kind: 'album', id: 'a1' });
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
		{ currentSongId: 's2', status: 'paused' as const, markedTrack: null }
	])(
		'shows a playing marker only for the current track while playback is active',
		async ({ currentSongId, status, markedTrack }) => {
			openCollection.set({ kind: 'album', id: 'a1' });
			songList.set([
				song({ id: 's1', title: 'Tide', track_number: 1 }),
				song({ id: 's2', title: 'Ebb', track_number: 2 })
			]);
			audioPlayer.current = { songId: currentSongId } as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await render();

			for (const trackTitle of ['Tide', 'Ebb']) {
				const track = requireButtonContainingText(target, trackTitle);
				expect(findElementByRoleAndName(track, 'img', RAIL_PLAYING_MARKER_LABEL) !== null).toBe(
					trackTitle === markedTrack
				);
			}
		}
	);

	it('summarizes a single take in the singular, with no pick suffix', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
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
});
