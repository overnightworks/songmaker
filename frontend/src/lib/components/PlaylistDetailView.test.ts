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

import PlaylistDetailView from './PlaylistDetailView.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

function entry(): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Tide',
		album_title: 'Night Drive',
		artist: 'Artist',
		generation_number: 1,
		mp3_path: 'tide.mp3',
		seed: 1,
		model_mode: 'sft',
		lyrics: null
	};
}

function detail(): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [entry()]
	};
}

beforeEach(() => {
	selectedPlaylistDetail.set(detail());
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
