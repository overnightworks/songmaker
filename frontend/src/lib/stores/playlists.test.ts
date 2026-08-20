import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { fetchPlaylist } from '$lib/api/client';
import type { PlaylistDetailItem } from '$lib/api/types';
import {
	deselectPlaylist,
	loadPlaylistDetail,
	selectedPlaylistDetail,
	selectedPlaylistId
} from './playlists';

vi.mock('$lib/api/client', () => ({
	fetchPlaylists: vi.fn(),
	fetchPlaylist: vi.fn(),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn()
}));

function makeDetail(id: string): PlaylistDetailItem {
	return {
		id,
		title: id,
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '',
		entries: []
	};
}

beforeEach(() => {
	deselectPlaylist();
});

afterEach(() => {
	vi.restoreAllMocks();
});

describe('loadPlaylistDetail', () => {
	it('does not let a slow first load overwrite a later selection', async () => {
		let resolveA: ((value: PlaylistDetailItem) => void) | undefined;
		vi.mocked(fetchPlaylist).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveA = resolve;
				})
		);
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('b'));

		const first = loadPlaylistDetail('a');
		const second = loadPlaylistDetail('b');
		await second;
		resolveA?.(makeDetail('a'));
		await first;

		expect(get(selectedPlaylistId)).toBe('b');
		expect(get(selectedPlaylistDetail)?.id).toBe('b');
	});
});
