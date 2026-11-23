import PlaylistDetailView from './PlaylistDetailView.svelte';
import {
	createComponentMount,
	openCollectionMenu,
	requireElement
} from './shell/rail-test-fixtures';
import { openPlaylistDetail, populatedPlaylistDefaults } from '#lib/test-utils/playlist-detail.ts';
import { words } from '#lib/words/en.ts';
import { makePlaylistDetail as detail } from '#lib/test-utils/factories.ts';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { closeNowPlaying, setShuffle } from '#lib/stores/player.ts';
import { queueContext } from '#lib/stores/queue.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
		addPlaylistToPlaylist: vi.fn(),
		fetchPlaylists: vi.fn(),
		uploadPlaylistCover: vi.fn(),
		deletePlaylistCover: vi.fn(),
		fetchPlaylist: vi.fn()
	};
});
vi.mock('#lib/stores/toast.ts', () => ({
	addToast: vi.fn()
}));
vi.mock('#lib/stores/navigation.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/navigation.ts')>()),
	selectSong: vi.fn()
}));

import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { selectSong } from '#lib/stores/navigation.ts';
import {
	addPlaylistToPlaylist,
	deletePlaylistCover,
	fetchPlaylist,
	fetchPlaylists,
	uploadPlaylistCover
} from '#lib/api/client.ts';
import { playlistList } from '#lib/stores/playlists.ts';
import { makePlaylist } from '#lib/test-utils/factories.ts';
import { addToast } from '#lib/stores/toast.ts';

const { render: mountPlaylistView, cleanup } = createComponentMount(PlaylistDetailView);

async function openCoverRows(target: HTMLElement): Promise<void> {
	menuRow(await openCollectionMenu(target), words['collectionMenu.cover']).click();
	await tick();
}

beforeEach(() => {
	vi.mocked(fetchPlaylist).mockReset();
	openPlaylistDetail(detail(populatedPlaylistDefaults()));
	vi.mocked(selectSong).mockReset();
	setShuffle(false);
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
		audioPlayer.status = 'playing';
	});
	vi.spyOn(audioPlayer, 'preload').mockImplementation(() => {});
	// jsdom leaves the player without a media element, so its own play/pause are
	// no-ops and a stopped take would look exactly like a running one. These
	// stubs move the status the way a real element does, so what a click did to
	// playback is readable as state instead of as a spied call.
	vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {
		audioPlayer.status = audioPlayer.status === 'playing' ? 'paused' : 'playing';
	});
});

afterEach(async () => {
	await cleanup();
	resetPlaylistsForTests();
	audioPlayer.current = null;
	queueContext.set({ type: 'library' });
	setShuffle(false);
	closeNowPlaying();
	audioPlayer.status = 'idle';
	delete document.documentElement.dataset.pointer;
});

describe('PlaylistDetailView menu', () => {
	it('uploads and removes a playlist cover through the shared header actions', async () => {
		const customCover = {
			card: '/api/playlists/p1/cover?variant=card&v=custom.png',
			detail: '/api/playlists/p1/cover?variant=detail&v=custom.png'
		};
		const playlistWithCover = {
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			cover: customCover,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		};
		vi.mocked(uploadPlaylistCover).mockResolvedValue(playlistWithCover);
		vi.mocked(deletePlaylistCover).mockResolvedValue({ ...playlistWithCover, cover: null });
		const target = await mountPlaylistView();

		await openCoverRows(target);
		menuRow(document.body, words['collectionMenu.upload']).click();
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		const file = new File(['cover'], 'cover.png', { type: 'image/png' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadPlaylistCover).toHaveBeenCalledWith('p1', file));
		await tick();
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(customCover.detail);

		await openCoverRows(target);
		menuRow(document.body, words['collectionMenu.removeCover']).click();
		await vi.waitFor(() => expect(deletePlaylistCover).toHaveBeenCalledWith('p1'));
		await tick();
		expect(target.querySelector('.header-cover img')).toBeNull();
		expect(target.querySelectorAll('.header-cover .playlist-cover-cell')).toHaveLength(4);
	});

	it.each([
		{
			action: 'a cover upload',
			menuItem: words['collectionMenu.upload'],
			picksFile: true,
			failure: new NetworkError('/api/playlists/p1/cover', new TypeError('Failed to fetch')),
			toast: words['playlistPage.coverSaveFailed']
		},
		{
			action: 'a cover upload',
			menuItem: words['collectionMenu.upload'],
			picksFile: true,
			failure: new ApiError(413, 'Cover is too large', '/api/playlists/p1/cover'),
			toast: 'Cover is too large'
		}
	])('toasts $toast when $action fails', async ({ menuItem, picksFile, failure, toast }) => {
		vi.mocked(addToast).mockReset();
		vi.mocked(uploadPlaylistCover).mockRejectedValue(failure);
		const target = await mountPlaylistView();

		await openCoverRows(target);
		menuRow(document.body, menuItem).click();
		if (picksFile) {
			const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
			const file = new File(['cover'], 'cover.png', { type: 'image/png' });
			Object.defineProperty(input, 'files', { configurable: true, value: [file] });
			input.dispatchEvent(new Event('change', { bubbles: true }));
		}

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
	});

	it('playlist_rule_1: lists Rename, Cover, Add to…, Share and Delete in the menu, with no Save offline', async () => {
		const menu = await openCollectionMenu(await mountPlaylistView());
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Playlist · Night Drive');
		expect(menuRowLabels(menu)).toEqual([
			words['collectionMenu.rename'],
			words['collectionMenu.cover'],
			words['collectionMenu.addTo'],
			words['collectionMenu.playlistShare'],
			words['collectionMenu.playlistDelete']
		]);
	});

	describe('playlist_rule_1: Add to…', () => {
		async function openPicker(target: HTMLElement): Promise<HTMLElement> {
			const menu = await openCollectionMenu(target);
			menuRow(menu, words['collectionMenu.addTo']).click();
			await tick();
			return menu;
		}

		beforeEach(() => {
			vi.mocked(addToast).mockReset();
			playlistList.update((lists) => [
				...lists,
				makePlaylist({ id: 'p-run', title: 'Morning Run', entry_count: 2 })
			]);
			vi.mocked(fetchPlaylists).mockResolvedValue(get(playlistList));
		});

		it('offers the other playlists and New playlist, not the open one', async () => {
			const menu = await openPicker(await mountPlaylistView());

			expect(
				Array.from(
					menu.querySelectorAll('.menu-picker-row .ap-title'),
					(title) => title.textContent
				)
			).toEqual(['Morning Run']);
			expect(menu.querySelector('.ap-input')).not.toBeNull();
		});

		it('adds the open playlist to the chosen one and tells what was added', async () => {
			vi.mocked(addPlaylistToPlaylist).mockResolvedValue({ added_count: 1, skipped: [] });
			const target = await mountPlaylistView();
			await openPicker(target);

			requireElement<HTMLButtonElement>(document.body, '.menu-picker-row').click();

			await vi.waitFor(() => expect(addPlaylistToPlaylist).toHaveBeenCalledWith('p-run', 'p1'));
			await vi.waitFor(() =>
				expect(addToast).toHaveBeenCalledWith(words['playlistPage.addedToPlaylist'], 'success')
			);
			expect(document.body.querySelector('.menu-panel')).toBeNull();
		});

		it('counts the skipped entries in the toast', async () => {
			vi.mocked(addPlaylistToPlaylist).mockResolvedValue({
				added_count: 1,
				skipped: [{ song_id: 's2', title: 'Gone', reason: 'missing_audio' }]
			});
			await openPicker(await mountPlaylistView());

			requireElement<HTMLButtonElement>(document.body, '.menu-picker-row').click();

			await vi.waitFor(() =>
				expect(addToast).toHaveBeenCalledWith(
					words['playlistPage.addedSkipped']({ added: '1', skipped: '1' }),
					'info'
				)
			);
		});

		it('toasts the failure when the add is refused', async () => {
			vi.mocked(addPlaylistToPlaylist).mockRejectedValue(
				new ApiError(404, 'Playlist not found', '/api/playlists/p-run/entries/playlist')
			);
			await openPicker(await mountPlaylistView());

			requireElement<HTMLButtonElement>(document.body, '.menu-picker-row').click();

			await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith('Playlist not found', 'error'));
		});
	});
});
