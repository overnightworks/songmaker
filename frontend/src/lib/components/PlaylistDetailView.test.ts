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
import { queueContext, setShuffle, shuffleEnabled } from '$lib/stores/player';
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
import { selectSong } from '$lib/stores/navigation';
import { fetchPlaylist } from '$lib/api/client';

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
		entry_count: 1,
		is_shared: false,
		share_slug: null,
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
			entry_count: d.entry_count,
			is_shared: d.is_shared,
			share_slug: d.share_slug,
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
	vi.spyOn(audioPlayer, 'load').mockImplementation((playback) => {
		audioPlayer.current = playback;
	});
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetPlaylists();
	audioPlayer.current = null;
	queueContext.set({ type: 'library' });
	setShuffle(false);
	delete document.documentElement.dataset.pointer;
});

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

describe('PlaylistDetailView header', () => {
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
		expect(header.querySelector('.header-cover-initials')?.textContent).toBe('ND');
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
		expect(items).toEqual(['Save offline', 'Rename', 'Delete playlist']);
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
		expect(row.textContent).toContain('v2');
		expect(row.textContent).toContain('3:15');
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

	it('omits duration when the version has none, since audio_duration defaults to 0', async () => {
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

describe('PlaylistDetailView row actions', () => {
	it('plays a clicked row as part of this playlist, in playlist order', async () => {
		setShuffle(true);
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

		target.querySelectorAll<HTMLElement>('.entry-row')[1].click();
		await tick();

		const ctx = get(queueContext);
		if (ctx.type !== 'playlist') throw new Error('expected a playlist queue');
		expect(ctx.playlist).toEqual({ id: 'p1', title: 'Night Drive' });
		expect(ctx.entries.map((queued) => queued.id)).toEqual(['pe1', 'pe2']);
		expect(ctx.index).toBe(1);
		expect(get(shuffleEnabled)).toBe(false);
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

	it('names the row and its … menu after the song they act on', async () => {
		openPlaylistDetail(detail({ entries: [entry({ id: 'pe1', song_title: 'Tide' })] }));
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(PlaylistDetailView, { target }));
		await tick();

		const row = requireElement<HTMLElement>(target, '.entry-row');
		expect(row.getAttribute('aria-label')).toBe(collectionRowPlayLabel('Tide'));
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
			entry_count: item.entry_count,
			is_shared: false,
			share_slug: null,
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
