import {
	makePlaylistDetail as detail,
	makePlaylistEntry as entry
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

import type { PlaylistDetailItem, PlaylistEntryItem } from '#lib/api/types.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import {
	collectionActionLabel,
	LIBRARY_RETRY_LABEL,
	PLAYING_MARK_LABEL,
	playlistEntryOverflowLabel,
	songEditorOpenLabel,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_PAUSE_LABEL
} from '#lib/constants.ts';
import { setOpenCollection } from '#lib/stores/collection.ts';
import {
	closeNowPlaying,
	nowPlayingOpen,
	playStartNotice,
	queueContext,
	setShuffle,
	shuffleEnabled
} from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import {
	loadPlaylistDetail,
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
import { findElementByRoleAndName } from './shell/rail-test-fixtures';
import { accessibleName, getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { menuRow, menuRowLabels } from '#lib/test-utils/collection-menu.ts';
import { describeBackClosesOverlay, plannedHistoryIndex } from '#lib/test-utils/library-history.ts';
import playlistDetailViewSource from './PlaylistDetailView.svelte?raw';
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

describe('PlaylistDetailView header', () => {
	it('keeps the cover file input out of the visible layout', () => {
		expect(playlistDetailViewSource).toMatch(
			/\.cover-file-input\s*\{\s*position:\s*absolute;\s*width:\s*1px;\s*height:\s*1px;\s*overflow:\s*hidden;\s*clip:\s*rect\(0 0 0 0\);\s*white-space:\s*nowrap;/
		);
	});

	it('uploads and removes a playlist cover through the shared header actions', async () => {
		const customCover = {
			card: '/api/playlists/p1/cover?variant=card&v=custom.png',
			detail: '/api/playlists/p1/cover?variant=detail&v=custom.png'
		};
		vi.mocked(uploadPlaylistCover).mockResolvedValue({
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			cover: customCover,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		});
		vi.mocked(deletePlaylistCover).mockResolvedValue({
			id: 'p1',
			title: 'Night Drive',
			slug: 'night-drive',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			cover: null,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		});
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const upload = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(item) => item.textContent?.trim() === 'Upload…'
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
			(item) => item.textContent?.trim() === 'Remove cover'
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
			menuItem: 'Upload…',
			picksFile: true,
			failure: new NetworkError('/api/playlists/p1/cover', new TypeError('Failed to fetch')),
			toast: 'Cover upload failed'
		},
		{
			action: 'a cover upload',
			menuItem: 'Upload…',
			picksFile: true,
			failure: new ApiError(413, 'Cover is too large', '/api/playlists/p1/cover'),
			toast: 'Cover is too large'
		}
	])('toasts $toast when $action fails', async ({ menuItem, picksFile, failure, toast }) => {
		vi.mocked(addToast).mockReset();
		vi.mocked(uploadPlaylistCover).mockRejectedValue(failure);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

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

	it('uses the collection header with Play, its song count and a … menu, with no breadcrumb, shuffle or visible Share icon (#1354 rule 24)', async () => {
		const target = await renderTwoEntryPlaylist();
		const header = requireElement(target, '.collection-header');
		expect(header.querySelector('.play-circle')?.getAttribute('aria-label')).toBe(
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist')
		);
		expect(requireElement(header, '.header-count').textContent).toBe('2 songs');
		expect(header.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelector('nav')).toBeNull();
		expect(target.textContent).not.toContain('Playlists');
		expect(
			[...target.querySelectorAll('button')].filter((button) =>
				/shuffle/i.test(accessibleName(button))
			)
		).toEqual([]);
		expect(header.querySelector('.share-btn')).toBeNull();
		expect(target.textContent).toContain('Tide');
		expect(header.querySelector('.playlist-cover-initials')?.textContent).toBe('ND');
	});

	it('1859_R1: lists Share playlist, Upload…, Rename and Delete playlist in the menu, with no Save offline', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const menu = requireElement<HTMLElement>(document.body, '.menu-panel');
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Playlist · Night Drive');
		expect(menuRowLabels(menu)).toEqual(['Share playlist', 'Upload…', 'Rename', 'Delete playlist']);
	});
});

describe('PlaylistDetailView row take traits', () => {
	it('shows duration, version, and a pick star, since playlist rows are takes', async () => {
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [
					entry({
						song_title: 'Tide',
						album_title: 'Night Drive',
						mp3_path: 'tide.mp3',
						version_number: 2,
						audio_duration: 195,
						is_picked: true
					})
				]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(row.querySelector('.picked-star')).not.toBeNull();
		// #163/5: the separators are the formatter's, not the markup's — written
		// in the template, the one before the duration lost its leading space
		// and the row read "take 1· 3:15".
		expect(row.querySelector('.song-row-detail')?.textContent).toBe('Artist · v2 · take 1 · 3:15');
	});

	it('omits version and duration when the take does not carry them', async () => {
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [
					entry({
						song_title: 'Tide',
						album_title: 'Night Drive',
						mp3_path: 'tide.mp3',
						version_number: null,
						audio_duration: null
					})
				]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(row.querySelector('.picked-star')).toBeNull();
		const meta = row.querySelector('.song-row-detail')?.textContent ?? '';
		expect(meta).not.toContain('· v');
		expect(meta).toBe('Artist · take 1');
	});

	it('omits duration for a take with no measured length (audio_duration 0 or null)', async () => {
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [
					entry({
						song_title: 'Tide',
						album_title: 'Night Drive',
						mp3_path: 'tide.mp3',
						audio_duration: 0
					})
				]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		const meta = row.querySelector('.song-row-detail')?.textContent ?? '';
		expect(meta).not.toContain('0:00');
		expect(meta).toContain('v1');
	});
});

let openSongSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the playlist entry menu',
	render: async () => {
		vi.mocked(selectSong).mockImplementation(async () => {
			openSongSawHistoryAt = plannedHistoryIndex();
		});
		return renderTwoEntryPlaylist();
	},
	open: (target) => requireElement<HTMLButtonElement>(target, '.overflow-btn').click(),
	isShown: (target) => target.querySelector('.entry-overflow-menu') !== null,
	closeWays: [
		{ way: 'a tap outside', close: () => document.body.click() },
		{
			way: 'Escape',
			close: () =>
				document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		},
		{
			way: 'Escape from one of its items',
			close: (target) =>
				requireElement<HTMLButtonElement>(target, '.entry-overflow-item').dispatchEvent(
					new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
				)
		},
		{
			way: "tapping the entry's ✎",
			close: (target) => requireElement<HTMLButtonElement>(target, '.song-row-edit').click(),
			actionSawHistoryAt: () => openSongSawHistoryAt
		}
	]
});

async function renderPlaylist(entries: PlaylistEntryItem[]): Promise<HTMLElement> {
	openPlaylistDetail(
		detail({ ...populatedPlaylistDefaults(), entry_count: entries.length, entries })
	);
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(PlaylistDetailView, { target }));
	await tick();
	return target;
}

async function renderTwoEntryPlaylist(): Promise<HTMLElement> {
	return renderPlaylist([
		entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' }),
		entry({
			album_title: 'Night Drive',
			mp3_path: 'tide.mp3',
			id: 'pe2',
			position: 1,
			generation_id: 'g2',
			song_title: 'Ebb'
		})
	]);
}

function expectQueueStartsAtSecondEntry(): void {
	const ctx = get(queueContext);
	if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
	expect(ctx.playlist).toEqual({ id: 'p1', title: 'Night Drive' });
	expect(ctx.entries.map((queued) => queued.id)).toEqual(['pe1', 'pe2']);
	expect(ctx.index).toBe(1);
	expect(get(shuffleEnabled)).toBe(false);
}

describe('PlaylistDetailView header play', () => {
	it('plays the playlist in order from the top from its play circle', async () => {
		setShuffle(true);
		const target = await renderTwoEntryPlaylist();

		requireElement<HTMLButtonElement>(target, '.collection-header .play-circle').click();
		await tick();

		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.entries.map((queued) => queued.id)).toEqual(['pe1', 'pe2']);
		expect(ctx.index).toBe(0);
		expect(get(shuffleEnabled)).toBe(false);
	});

	it('pauses the playlist from its circle while it plays, keeps its mark, and resumes on the next tap', async () => {
		const pause = vi.spyOn(audioPlayer, 'pause').mockImplementation(() => {
			audioPlayer.status = 'paused';
		});
		const resume = vi.spyOn(audioPlayer, 'play').mockImplementation(() => {
			audioPlayer.status = 'playing';
		});
		onTestFinished(() => {
			pause.mockRestore();
			resume.mockRestore();
		});
		const target = await renderTwoEntryPlaylist();
		const header = requireElement(target, '.collection-header');
		getByRoleButton(header, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist')).click();
		await tick();
		const queueBeforePause = get(queueContext);

		getByRoleButton(header, collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'playlist')).click();
		await tick();

		expect(audioPlayer.status).toBe('paused');
		expect(
			findElementByRoleAndName(target.querySelectorAll('.entry-row')[0], 'img', PLAYING_MARK_LABEL)
		).not.toBeNull();
		getByRoleButton(header, collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist')).click();
		await tick();

		expect(audioPlayer.status).toBe('playing');
		expect(
			getByRoleButton(header, collectionActionLabel(TRANSPORT_PAUSE_LABEL, 'playlist'))
		).not.toBeNull();
		expect(get(queueContext)).toBe(queueBeforePause);
	});

	it('dims play on an empty playlist, and a tap keeps the running queue', async () => {
		setShuffle(true);
		const running = { type: 'album' as const, albumId: 'a-running' };
		queueContext.set(running);
		const target = await renderPlaylist([]);
		const circle = getByRoleButton(
			requireElement(target, '.collection-header'),
			collectionActionLabel(TRANSPORT_PLAY_LABEL, 'playlist')
		);

		circle.click();
		await tick();

		expect(circle.disabled).toBe(true);
		expect(get(queueContext)).toBe(running);
		expect(get(playStartNotice)).toBe('idle');
		expect(get(shuffleEnabled)).toBe(true);
	});

	it.each([
		['loading', () => new Promise<PlaylistDetailItem>(() => {})],
		['error', () => Promise.reject(new ApiError(429, 'Too many requests', '/api/playlists/p2'))]
	] as const)(
		'starts nothing from the play circle while the newly opened playlist is %s',
		async (loadStatus, fetchNewPlaylist) => {
			const target = await renderTwoEntryPlaylist();
			addPlaylistToList({ id: 'p2', title: 'Party Mix', entry_count: 3 });
			vi.mocked(fetchPlaylist).mockImplementationOnce(fetchNewPlaylist);
			void loadPlaylistDetail('p2');
			await vi.waitFor(() => expect(get(playlistDetailLoad).status).toBe(loadStatus));
			await tick();

			requireElement<HTMLButtonElement>(target, '.collection-header .play-circle').click();
			await tick();

			expect(requireElement(target, '.collection-header').textContent).toContain('Party Mix');
			expect(audioPlayer.current).toBeNull();
			expect(get(queueContext)).toEqual({ type: 'library' });
			expect(get(playStartNotice)).toBe('idle');
		}
	);
});

describe('PlaylistDetailView row actions', () => {
	it('plays a clicked row as part of this playlist and stays on the playlist page', async () => {
		setShuffle(true);
		const target = await renderTwoEntryPlaylist();

		target.querySelectorAll<HTMLElement>('.entry-row .song-row-body')[1].click();
		await tick();

		expectQueueStartsAtSecondEntry();
		expect(get(nowPlayingOpen)).toBe(false);
	});

	it('never pauses the take its row body is clicked on while that take plays', async () => {
		const target = await renderTwoEntryPlaylist();
		const row = target.querySelectorAll<HTMLElement>('.entry-row')[1];
		requireElement<HTMLButtonElement>(row, '.song-row-body').click();
		await tick();

		requireElement<HTMLButtonElement>(row, '.song-row-body').click();
		await tick();

		expect(audioPlayer.status).toBe('playing');
		expect(get(nowPlayingOpen)).toBe(false);
	});

	it.each(['playing', 'paused'] as const)(
		'marks the row the transport holds while %s, and only that row',
		async (status) => {
			const target = await renderTwoEntryPlaylist();
			const [tide, ebb] = target.querySelectorAll<HTMLElement>('.entry-row');
			requireElement<HTMLButtonElement>(ebb, '.song-row-body').click();
			await tick();
			audioPlayer.status = status;
			await tick();

			expect(findElementByRoleAndName(ebb, 'img', PLAYING_MARK_LABEL)).not.toBeNull();
			expect(requireElement(ebb, '.song-row').classList.contains('current')).toBe(true);
			expect(findElementByRoleAndName(tide, 'img', PLAYING_MARK_LABEL)).toBeNull();
			expect(requireElement(tide, '.song-row').classList.contains('current')).toBe(false);
		}
	);

	it('marks only the entry that plays when the playlist holds one take twice', async () => {
		const tide = entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' });
		const target = await renderPlaylist([tide, entry({ ...tide, id: 'pe2', position: 1 })]);
		const rows = Array.from(target.querySelectorAll<HTMLElement>('.entry-row'));
		const marks = (): boolean[] =>
			rows.map((row) => findElementByRoleAndName(row, 'img', PLAYING_MARK_LABEL) !== null);

		requireElement<HTMLButtonElement>(rows[1], '.song-row-body').click();
		await tick();
		expect(marks()).toEqual([false, true]);

		requireElement<HTMLButtonElement>(rows[0], '.song-row-body').click();
		await tick();
		expect(marks()).toEqual([true, false]);
	});

	it('moves Move up/down and Remove into the … menu instead of inline, keeping only the row and … inline', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [
					entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' }),
					entry({ album_title: 'Night Drive', mp3_path: 'tide.mp3', id: 'pe2', song_title: 'Ebb' })
				]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		expect(target.querySelector('.move-btn')).toBeNull();
		expect(target.querySelector('.remove-btn')).toBeNull();

		const rows = target.querySelectorAll<HTMLElement>('.entry-row');
		const secondRowOverflow = requireElement<HTMLButtonElement>(rows[1], '.overflow-btn');
		secondRowOverflow.click();
		await tick();

		const menu = requireElement<HTMLElement>(document.body, '.entry-overflow-menu');
		const items = Array.from(menu.querySelectorAll('.entry-overflow-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Move up', 'Remove from playlist']);
	});

	it('carries no play glyph: the row plays, and its ✎ and … menu are named after the song', async () => {
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' })]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(Array.from(row.querySelectorAll('button')).map((button) => button.className)).toEqual([
			expect.stringContaining('song-row-body'),
			expect.stringContaining('song-row-edit'),
			expect.stringContaining('overflow-btn')
		]);
		expect(requireElement(row, '.song-row-body').textContent).toContain('Tide');
		expect(accessibleName(requireElement(row, '.song-row-edit'))).toBe(songEditorOpenLabel('Tide'));
		expect(requireElement(row, '.overflow-btn').getAttribute('aria-label')).toBe(
			playlistEntryOverflowLabel('Tide')
		);
	});

	it("opens the take's song in the editor from its ✎, without playing it", async () => {
		const target = await renderTwoEntryPlaylist();

		getByRoleButton(
			target.querySelectorAll<HTMLElement>('.entry-row')[1],
			songEditorOpenLabel('Ebb')
		).click();
		await tick();

		expect(selectSong).toHaveBeenCalledExactlyOnceWith('s1');
		expect(audioPlayer.current).toBeNull();
	});

	it('keeps reorder and remove in the … menu on a fine pointer too', async () => {
		// #141/7: one place per row for these actions at every width, so the
		// row itself never grows a second, width-dependent action set.
		document.documentElement.dataset.pointer = 'fine';
		openPlaylistDetail(
			detail({
				...populatedPlaylistDefaults(),
				entries: [
					entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' }),
					entry({ album_title: 'Night Drive', mp3_path: 'tide.mp3', id: 'pe2', song_title: 'Ebb' })
				]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		expect(target.querySelector('.move-btn')).toBeNull();
		expect(target.querySelector('.remove-btn')).toBeNull();

		const rows = target.querySelectorAll<HTMLElement>('.entry-row');
		requireElement<HTMLButtonElement>(rows[1], '.overflow-btn').click();
		await tick();
		const menu = requireElement<HTMLElement>(target, '.entry-overflow-menu');
		expect(
			Array.from(menu.querySelectorAll('.entry-overflow-item')).map((el) => el.textContent?.trim())
		).toEqual(['Move up', 'Remove from playlist']);
	});
});

function addPlaylistToList(item: { id: string; title: string; entry_count: number }): void {
	playlistList.set([
		...get(playlistList),
		{
			id: item.id,
			title: item.title,
			slug: item.title.toLowerCase().replace(/\s+/g, '-'),
			entry_count: item.entry_count,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
}

describe('PlaylistDetailView load failure (#139)', () => {
	it('shows an inline error with Retry and never the previous playlist rows on a rate-limited reopen', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();
		expect(target.querySelector('.entry-row')).not.toBeNull();

		addPlaylistToList({ id: 'p2', title: 'Party Mix', entry_count: 3 });
		vi.mocked(fetchPlaylist).mockRejectedValueOnce(
			new ApiError(429, 'Too many requests', '/api/playlists/p2')
		);
		await loadPlaylistDetail('p2');
		await tick();

		const header = requireElement(target, '.collection-header');
		expect(header.textContent).toContain('Party Mix');
		expect(target.querySelector('.entry-row')).toBeNull();
		expect(requireElement(target, '[role="alert"]').textContent).toBe('Too many requests');
		expect(requireElement<HTMLButtonElement>(target, '.retry-btn').textContent).toBe(
			LIBRARY_RETRY_LABEL
		);
	});

	it('reloads the playlist detail when Retry is clicked', async () => {
		addPlaylistToList({ id: 'p2', title: 'Party Mix', entry_count: 1 });
		vi.mocked(fetchPlaylist).mockRejectedValueOnce(
			new ApiError(429, 'Too many requests', '/api/playlists/p2')
		);
		await loadPlaylistDetail('p2');

		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.retry-btn');

		vi.mocked(fetchPlaylist).mockResolvedValueOnce(
			detail({
				...populatedPlaylistDefaults(),
				id: 'p2',
				title: 'Party Mix',
				entries: [
					entry({
						album_title: 'Night Drive',
						mp3_path: 'tide.mp3',
						id: 'pe2',
						song_title: 'Solstice'
					})
				]
			})
		);
		requireElement<HTMLButtonElement>(target, '.retry-btn').click();
		for (let i = 0; i < 5; i += 1) {
			await Promise.resolve();
		}
		await tick();

		expect(target.querySelector('.retry-btn')).toBeNull();
		expect(target.textContent).toContain('Solstice');
	});
});

describe('PlaylistDetailView with an empty playlistList (#139)', () => {
	it('falls back to the detail for the header when the playlist is not in playlistList', async () => {
		// Reachable from the Shares inventory, a deep link, or mobile without
		// the Rail ever mounting ensurePlaylistsLoaded().
		playlistList.set([]);
		setOpenCollection({ kind: 'playlist', id: 'p9' });
		selectedPlaylistDetail.set(
			detail({ ...populatedPlaylistDefaults(), id: 'p9', title: 'Shared Mix' })
		);
		playlistDetailLoad.set({ status: 'ready', error: null });

		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		expect(requireElement(target, '.collection-header').textContent).toContain('Shared Mix');
		expect(target.querySelector('.entry-row')).not.toBeNull();
	});

	it('shows a loading placeholder instead of nothing while the detail is still in flight', async () => {
		playlistList.set([]);
		setOpenCollection({ kind: 'playlist', id: 'p9' });
		selectedPlaylistDetail.set(null);
		playlistDetailLoad.set({ status: 'loading', error: null });

		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		expect(requireElement(target, '[role="status"]').textContent).toBe('Loading playlist…');
	});

	it('offline, shows neither a failure nor a spinner text under the strip', async () => {
		playlistList.set([]);
		setOpenCollection({ kind: 'playlist', id: 'p9' });
		selectedPlaylistDetail.set(null);
		playlistDetailLoad.set({ status: 'unreachable', error: null });

		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		expect(target.querySelector('[role="status"], [role="alert"], .retry-btn')).toBeNull();
	});
});

describe('PlaylistDetailView says song, never track', () => {
	it('defect:#1529 an empty playlist says No songs in this playlist yet.', async () => {
		const target = await renderPlaylist([]);

		expect(requireElement(target, '.empty-tab').textContent).toBe('No songs in this playlist yet.');
	});

	it.each([
		{ songs: 1, counted: '1 song' },
		{ songs: 2, counted: '2 songs' }
	])('defect:#1529 Delete playlist counts $counted', async ({ songs, counted }) => {
		const target = await renderPlaylist(
			Array.from({ length: songs }, (_, position) =>
				entry({ id: `pe${position}`, position, song_title: `Song ${position}` })
			)
		);

		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		menuRow(requireElement(document.body, '.menu-panel'), 'Delete playlist').click();
		await tick();

		expect(requireElement(document.body, '[role="dialog"] ul').textContent).toBe(counted);
	});
});
