import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaylistDetailItem, PlaylistEntryItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import {
	collectionRowPlayLabel,
	LIBRARY_RETRY_LABEL,
	playlistEntryOverflowLabel
} from '$lib/constants';
import { setOpenCollection } from '$lib/stores/collection';
import {
	closeNowPlaying,
	nowPlayingOpen,
	nowPlayingPanel,
	queueContext,
	setShuffle,
	shuffleEnabled
} from '$lib/stores/player';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import {
	loadPlaylistDetail,
	playlistDetailLoad,
	playlistList,
	resetPlaylists,
	selectedPlaylistDetail
} from '$lib/stores/playlists';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
		uploadPlaylistCover: vi.fn(),
		deletePlaylistCover: vi.fn(),
		createQueueStreamSnapshot: vi.fn(),
		fetchPlaylist: vi.fn()
	};
});
vi.mock('$lib/api/queue-streams', () => ({
	pinQueueStream: vi.fn(),
	unpinQueueStream: vi.fn()
}));
vi.mock('$lib/services/offline', () => ({
	saveStream: vi.fn(),
	removeStream: vi.fn(),
	offlineStreamUrl: vi.fn(() => '/offline/stream/test'),
	rememberPlaylistOfflineStream: vi.fn(),
	forgetPlaylistOfflineStream: vi.fn(),
	loadSavedOfflinePlaylist: vi.fn().mockResolvedValue(null)
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn()
}));
vi.mock('$lib/stores/navigation', () => ({
	selectSong: vi.fn()
}));

import PlaylistDetailView from './PlaylistDetailView.svelte';
import playlistDetailViewSource from './PlaylistDetailView.svelte?raw';
import { selectSong } from '$lib/stores/navigation';
import { deletePlaylistCover, fetchPlaylist, uploadPlaylistCover } from '$lib/api/client';

const mounted: Array<ReturnType<typeof mount>> = [];

function entry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Tide',
		album_title: 'Night Drive',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'tide.mp3',
		seed: 1,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

function detail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [entry()],
		...overrides
	};
}

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
	openPlaylistDetail(detail());
	vi.mocked(selectSong).mockReset();
	setShuffle(false);
	queueContext.set({ type: 'library' });
	closeNowPlaying();
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
		audioPlayer.status = 'playing';
	});
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
	resetPlaylists();
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

	it('uses the collection header with a Play action and a … menu instead of a visible Share icon', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();
		const header = requireElement(target, '.collection-header');
		expect(header.querySelector('.play-btn')).not.toBeNull();
		expect(header.querySelector('.collection-menu')).not.toBeNull();
		expect(header.querySelector('.share-btn')).toBeNull();
		expect(target.textContent).toContain('Tide');
		expect(header.querySelector('.playlist-cover-initials')?.textContent).toBe('ND');
	});

	it('lists Share playlist, Save offline, Rename, and Delete playlist in the menu', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
		await tick();
		const menu = requireElement<HTMLElement>(document.body, '.menu-panel');
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Playlist · Night Drive');
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share playlist');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Upload…', 'Save offline', 'Rename', 'Delete playlist']);
	});
});

describe('PlaylistDetailView row take traits', () => {
	it('shows duration, version, and a pick star, since playlist rows are takes', async () => {
		openPlaylistDetail(
			detail({
				entries: [entry({ version_number: 2, audio_duration: 195, is_picked: true })]
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
		expect(row.querySelector('.entry-meta')?.textContent).toBe('Artist · v2 · take 1 · 3:15');
	});

	it('omits version and duration when the take does not carry them', async () => {
		openPlaylistDetail(
			detail({
				entries: [entry({ version_number: null, audio_duration: null, is_picked: false })]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(row.querySelector('.picked-star')).toBeNull();
		const meta = row.querySelector('.entry-meta')?.textContent ?? '';
		expect(meta).not.toContain('· v');
		expect(meta).toBe('Artist · take 1');
	});

	it('omits duration for a take with no measured length (audio_duration 0 or null)', async () => {
		openPlaylistDetail(
			detail({
				entries: [entry({ version_number: 1, audio_duration: 0, is_picked: false })]
			})
		);
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		const meta = row.querySelector('.entry-meta')?.textContent ?? '';
		expect(meta).not.toContain('0:00');
		expect(meta).toContain('v1');
	});
});

describe('PlaylistDetailView row overflow menu', () => {
	it('offers Open song in editor for a take', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		requireElement<HTMLButtonElement>(target, '.overflow-btn').click();
		await tick();

		const menu = requireElement<HTMLElement>(target, '.entry-overflow-menu');
		expect(
			Array.from(menu.querySelectorAll('.entry-overflow-item')).map((el) => el.textContent?.trim())
		).toContain('Open song in editor');
	});

	it("opens the take's song in the editor and closes the menu", async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		requireElement<HTMLButtonElement>(target, '.overflow-btn').click();
		await tick();
		requireElement<HTMLButtonElement>(target, '.entry-overflow-item').click();
		await tick();

		expect(selectSong).toHaveBeenCalledWith('s1');
		expect(target.querySelector('.entry-overflow-menu')).toBeNull();
	});
});

async function renderTwoEntryPlaylist(): Promise<HTMLElement> {
	openPlaylistDetail(
		detail({
			entry_count: 2,
			entries: [
				entry({ id: 'pe1', position: 0, song_title: 'Tide' }),
				entry({ id: 'pe2', position: 1, generation_id: 'g2', song_title: 'Ebb' })
			]
		})
	);
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(PlaylistDetailView, { target }));
	await tick();
	return target;
}

function expectQueueStartsAtSecondEntry(): void {
	const ctx = get(queueContext);
	if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
	expect(ctx.playlist).toEqual({ id: 'p1', title: 'Night Drive' });
	expect(ctx.entries.map((queued) => queued.id)).toEqual(['pe1', 'pe2']);
	expect(ctx.index).toBe(1);
	expect(get(shuffleEnabled)).toBe(false);
}

describe('PlaylistDetailView row actions', () => {
	it('plays a clicked row as part of this playlist and shows the take in Now Playing', async () => {
		setShuffle(true);
		const target = await renderTwoEntryPlaylist();

		target.querySelectorAll<HTMLElement>('.entry-row .entry-info')[1].click();
		await tick();

		expectQueueStartsAtSecondEntry();
		expect(get(nowPlayingOpen)).toBe(true);
		expect(get(nowPlayingPanel)).toBe('take');
	});

	it('plays and nothing more from the row play button', async () => {
		setShuffle(true);
		const target = await renderTwoEntryPlaylist();

		target.querySelectorAll<HTMLElement>('.entry-row .entry-play')[1].click();
		await tick();

		expectQueueStartsAtSecondEntry();
		expect(get(nowPlayingOpen)).toBe(false);
	});

	it('never pauses the take its row body is clicked on while that take plays', async () => {
		const target = await renderTwoEntryPlaylist();
		const row = target.querySelectorAll<HTMLElement>('.entry-row')[1];
		requireElement<HTMLButtonElement>(row, '.entry-info').click();
		await tick();
		closeNowPlaying();

		requireElement<HTMLButtonElement>(row, '.entry-info').click();
		await tick();

		expect(audioPlayer.status).toBe('playing');
		expect(get(nowPlayingOpen)).toBe(true);
	});

	it('pauses the playing entry from its play button instead of restarting it', async () => {
		const target = await renderTwoEntryPlaylist();

		const play = target.querySelectorAll<HTMLElement>('.entry-row .entry-play')[1];
		play.click();
		await tick();
		vi.mocked(audioPlayer.load).mockClear();
		play.click();
		await tick();

		expect(audioPlayer.status).toBe('paused');
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('moves Move up/down and Remove into the … menu instead of inline, keeping only Play and … inline', async () => {
		document.documentElement.dataset.pointer = 'coarse';
		openPlaylistDetail(
			detail({
				entries: [entry({ id: 'pe1', song_title: 'Tide' }), entry({ id: 'pe2', song_title: 'Ebb' })]
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
		expect(items).toEqual(['Open song in editor', 'Move up', 'Remove from playlist']);
	});

	it('names the row play button and its … menu after the song they act on', async () => {
		openPlaylistDetail(detail({ entries: [entry({ id: 'pe1', song_title: 'Tide' })] }));
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(requireElement(row, '.entry-play').getAttribute('aria-label')).toBe(
			collectionRowPlayLabel('Tide')
		);
		expect(requireElement(row, '.entry-info').textContent).toContain('Tide');
		expect(requireElement(row, '.overflow-btn').getAttribute('aria-label')).toBe(
			playlistEntryOverflowLabel('Tide')
		);
	});

	it('keeps reorder and remove in the … menu on a fine pointer too', async () => {
		// #141/7: one place per row for these actions at every width, so the
		// row itself never grows a second, width-dependent action set.
		document.documentElement.dataset.pointer = 'fine';
		openPlaylistDetail(
			detail({
				entries: [entry({ id: 'pe1', song_title: 'Tide' }), entry({ id: 'pe2', song_title: 'Ebb' })]
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
		).toEqual(['Open song in editor', 'Move up', 'Remove from playlist']);
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
				id: 'p2',
				title: 'Party Mix',
				entries: [entry({ id: 'pe2', song_title: 'Solstice' })]
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
		selectedPlaylistDetail.set(detail({ id: 'p9', title: 'Shared Mix' }));
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
});
