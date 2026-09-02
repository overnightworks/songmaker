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

	it('opens the library grid on the Albums tab when the LIBRARY title is clicked', async () => {
		librarySurface.set('detail');
		libraryFilter.set('playlists');
		const target = await render();
		const titleButton = requireElement<HTMLButtonElement>(target, 'button.group-title');
		titleButton.click();
		await vi.waitFor(() => expect(get(libraryFilter)).toBe('albums'));
		expect(get(librarySurface)).toBe('browse');
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

	it('pre-expands the open album and marks its selected track, in track order', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		selectedSongId.set('s2');
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');

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

	it('toggles a closed album open on click, loading its songs on demand', async () => {
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
		const albumToggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		albumToggles[1]?.click();
		await tick();
		expect(albumToggles[1]?.getAttribute('aria-expanded')).toBe('true');
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
		const toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('toggles the row open without navigating when the chevron is clicked', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom' })]);
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, '.album-disclose');

		toggle.click();
		await tick();
		await Promise.resolve();

		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(get(openCollection)).toBeNull();
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
		let toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[0]?.getAttribute('aria-expanded')).toBe('true');

		labels[1]?.click();
		await tick();
		await Promise.resolve();
		toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[0]?.getAttribute('aria-expanded')).toBe('false');
		expect(toggles[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('closes the previously open album when a different album is opened by its chevron', async () => {
		albumList.set([
			album({ id: 'a1', title: 'Nachtstrom' }),
			album({ id: 'a2', title: 'Anfield' })
		]);
		const target = await render();
		let toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		toggles[0]?.click();
		await tick();
		toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[0]?.getAttribute('aria-expanded')).toBe('true');

		toggles[1]?.click();
		await tick();
		toggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		expect(toggles[0]?.getAttribute('aria-expanded')).toBe('false');
		expect(toggles[1]?.getAttribute('aria-expanded')).toBe('true');
	});

	it('does not refetch an album on a second expand once its songs are loaded', async () => {
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
		const albumToggles = target.querySelectorAll<HTMLButtonElement>('.album-disclose');
		albumToggles[1]?.click();
		await tick();
		await vi.waitFor(() => expect(target.textContent).toContain('Kickoff'));
		expect(fetchSongs).toHaveBeenCalledTimes(1);

		albumToggles[1]?.click();
		await tick();
		albumToggles[1]?.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});

	it('refetches a genuinely empty album on every expand -- song_count is not trusted to stay accurate', async () => {
		albumList.set([album({ id: 'a1', title: 'Nachtstrom', song_count: 0 })]);
		songList.set([]);
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');

		albumToggle.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(1);

		albumToggle.click();
		await tick();
		albumToggle.click();
		await tick();
		expect(fetchSongs).toHaveBeenCalledTimes(2);
	});

	it('lets a viewer collapse the open album even while it stays the open collection', async () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		const target = await render();
		const albumToggle = requireElement<HTMLButtonElement>(target, '.album-disclose');
		expect(albumToggle.getAttribute('aria-expanded')).toBe('true');

		albumToggle.click();
		await tick();
		expect(albumToggle.getAttribute('aria-expanded')).toBe('false');
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
