import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { PLAYING_MARK_LABEL } from '$lib/constants';
import { openCollection, setOpenCollection } from '$lib/stores/collection';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { closeNowPlaying, nowPlayingOpen, nowPlayingPanel, queueContext } from '$lib/stores/player';
import { playlistList, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { railTreeQuery } from '$lib/stores/librarySearch';
import {
	buildPlaylist as playlist,
	buildPlaylistDetail as detail,
	buildPlaylistEntry as entry,
	createComponentMount,
	findElementByRoleAndName,
	requireElement
} from './rail-test-fixtures';

vi.mock('$app/navigation', async () => (await import('./rail-test-fixtures')).railNavigationMock());
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());
vi.mock('$lib/api/library', async () =>
	(await import('./rail-test-fixtures')).railLibraryApiMock()
);
vi.mock('$lib/api/albums', async () => (await import('./rail-test-fixtures')).railAlbumsApiMock());
vi.mock('$lib/api/songs', async () => (await import('./rail-test-fixtures')).railSongsApiMock());
const fetchPlaylists = vi.fn().mockResolvedValue([]);
const fetchPlaylist = vi.fn();
vi.mock('$lib/api/client', async () => {
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
});

afterEach(async () => {
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	await cleanup();
	resetPlaylists();
	resetLibraryContextForTests();
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

	it('toggles the PLAYLISTS group without navigating when its label is clicked', async () => {
		librarySurface.set('detail');
		const target = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		requireElement<HTMLSpanElement>(toggle, '.group-title').click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(get(librarySurface)).toBe('detail');
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
