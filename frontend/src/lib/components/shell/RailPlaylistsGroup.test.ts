import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { RAIL_PLAYING_MARKER_LABEL } from '$lib/constants';
import { openCollection, setOpenCollection } from '$lib/stores/collection';
import {
	libraryFilter,
	librarySurface,
	resetLibraryContextForTests
} from '$lib/stores/libraryContext';
import { closeNowPlaying, nowPlayingOpen, nowPlayingPanel, queueContext } from '$lib/stores/player';
import { playlistList, resetPlaylists, selectedPlaylistDetail } from '$lib/stores/playlists';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import {
	buildPlaylist as playlist,
	buildPlaylistDetail as detail,
	buildPlaylistEntry as entry,
	createComponentMount,
	findElementByRoleAndName,
	requireButtonContainingText,
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

	it.each([
		{ currentEntryId: 'pe1', status: 'playing' as const, markedEntry: 'Tide' },
		{ currentEntryId: 'pe2', status: 'playing' as const, markedEntry: 'Ebb' },
		{ currentEntryId: 'pe2', status: 'paused' as const, markedEntry: null }
	])(
		'shows a playing marker only for the current playlist entry while playback is active',
		async ({ currentEntryId, status, markedEntry }) => {
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
				generation: {
					id: currentEntryId === 'pe1' ? 'g1' : 'g2',
					mp3_path: currentEntryId === 'pe1' ? 'tide.mp3' : 'ebb.mp3'
				}
			} as unknown as typeof audioPlayer.current;
			audioPlayer.status = status;

			const target = await render();

			const rows = target.querySelectorAll('.row-sub2 .row-title');
			expect(Array.from(rows).map((row) => row.textContent)).toEqual(['Tide', 'Ebb']);
			const active = target.querySelector('.row-sub2.row-active .row-title');
			expect(active?.textContent).toBe(currentEntryId === 'pe1' ? 'Tide' : 'Ebb');

			for (const entryTitle of ['Tide', 'Ebb']) {
				const entryRow = requireButtonContainingText(target, entryTitle);
				expect(findElementByRoleAndName(entryRow, 'img', RAIL_PLAYING_MARKER_LABEL) !== null).toBe(
					entryTitle === markedEntry
				);
			}
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
