import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaylistDetailItem, PlaylistEntryItem } from '$lib/api/types';
import { selectedPlaylistDetail } from '$lib/stores/playlists';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		sharePlaylist: vi.fn(),
		unsharePlaylist: vi.fn(),
		createQueueStreamSnapshot: vi.fn()
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

beforeEach(() => {
	selectedPlaylistDetail.set(detail());
	vi.mocked(selectSong).mockReset();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	selectedPlaylistDetail.set(null);
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
		selectedPlaylistDetail.set(
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
		selectedPlaylistDetail.set(
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
		expect(meta).toBe('Artist · Gen #1');
	});

	it('omits duration when the version has none, since audio_duration defaults to 0', async () => {
		selectedPlaylistDetail.set(
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
		expect(menu.textContent?.trim()).toBe('Open song in editor');
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
