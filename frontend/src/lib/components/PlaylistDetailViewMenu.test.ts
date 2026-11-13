import { words } from '#lib/words/en.ts';
import {
	makePlaylistDetail as detail,
	makePlaylistEntry as entry
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaylistDetailItem } from '#lib/api/types.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { setOpenCollection } from '#lib/stores/collection.ts';
import { closeNowPlaying, queueContext, setShuffle } from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import {
	playlistDetailLoad,
	playlistList,
	resetPlaylistsForTests,
	selectedPlaylistDetail
} from '#lib/stores/playlists.ts';

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
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

import PlaylistDetailView from './PlaylistDetailView.svelte';
import { menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { selectSong } from '#lib/stores/navigation.ts';
import { deletePlaylistCover, fetchPlaylist, uploadPlaylistCover } from '#lib/api/client.ts';
import { addToast } from '#lib/stores/toast.ts';

function populatedPlaylistDefaults(): Partial<PlaylistDetailItem> {
	return {
		share_slug: null,
		entries: [entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' })]
	};
}

const mounted: Array<ReturnType<typeof mount>> = [];

// The header prefers the lightweight playlist in playlistList and falls
// back to the detail once it matches the open id (see PlaylistDetailView.
// svelte) — this seeds both, the way navigation.openPlaylist does, so tests
// exercise the common (list populated) path. Tests for the fallback path
// seed only the detail.
function openPlaylistDetail(d: PlaylistDetailItem): void {
	playlistList.set([
		{
			id: d.id,
			title: d.title,
			slug: d.slug,
			entry_count: d.entry_count,
			is_shared: d.is_shared,
			share_slug: d.share_slug,
			cover: d.cover,
			album_covers: d.album_covers,
			created_at: d.created_at
		}
	]);
	setOpenCollection({ kind: 'playlist', id: d.id });
	selectedPlaylistDetail.set(d);
	playlistDetailLoad.set({ status: 'ready', error: null });
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
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetPlaylistsForTests();
	audioPlayer.current = null;
	queueContext.set({ type: 'library' });
	setShuffle(false);
	closeNowPlaying();
	audioPlayer.status = 'idle';
	delete document.documentElement.dataset.pointer;
});

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

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

		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const upload = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(item) => item.textContent?.trim() === words['collectionMenu.upload']
		);
		upload?.click();
		const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
		const file = new File(['cover'], 'cover.png', { type: 'image/png' });
		Object.defineProperty(input, 'files', { configurable: true, value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await vi.waitFor(() => expect(uploadPlaylistCover).toHaveBeenCalledWith('p1', file));
		await tick();
		expect(target.querySelector('.header-cover img')?.getAttribute('src')).toBe(customCover.detail);

		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const remove = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(item) => item.textContent?.trim() === words['collectionMenu.removeCover']
		);
		remove?.click();
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
			toast: 'Cover upload failed'
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

		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		Array.from(document.body.querySelectorAll<HTMLButtonElement>('.menu-item'))
			.find((item) => item.textContent?.trim() === menuItem)
			?.click();
		if (picksFile) {
			const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
			const file = new File(['cover'], 'cover.png', { type: 'image/png' });
			Object.defineProperty(input, 'files', { configurable: true, value: [file] });
			input.dispatchEvent(new Event('change', { bubbles: true }));
		}

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
	});

	it('1859_R1: lists Share playlist, Upload…, Rename and Delete playlist in the menu, with no Save offline', async () => {
		const target = await mountPlaylistView();
		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const menu = requireElement<HTMLElement>(document.body, '.menu-panel');
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Playlist · Night Drive');
		expect(menuRowLabels(menu)).toEqual([
			words['collectionMenu.playlistShare'],
			words['collectionMenu.upload'],
			words['collectionMenu.rename'],
			words['collectionMenu.playlistDelete']
		]);
	});
});

async function mountPlaylistView(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(PlaylistDetailView, { target }));
	await tick();
	return target;
}
