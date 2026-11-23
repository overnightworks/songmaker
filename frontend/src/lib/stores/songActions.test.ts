import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { makeSong } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';

vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	renameSong: vi.fn(),
	deleteSong: vi.fn(),
	restoreSong: vi.fn(),
	shareSong: vi.fn(),
	unshareSong: vi.fn()
}));
vi.mock('#lib/stores/playlists.ts', () => ({ addSongToPlaylist: vi.fn() }));

import { deleteSong, renameSong, restoreSong, shareSong, unshareSong } from '#lib/api/client.ts';
import { resetLibraryDataForTests, songList } from '#lib/stores/libraryData.ts';
import { addSongToPlaylist } from '#lib/stores/playlists.ts';
import { toasts } from '#lib/stores/toast.ts';
import {
	addSongToPlaylistWithToast,
	deleteSongWithUndo,
	disableSongSharing,
	enableSongSharing,
	renameSongTo
} from './songActions';

const FIRST = makeSong({ id: 's1', title: 'First' });
const SECOND = makeSong({ id: 's2', title: 'Second', is_shared: true, share_slug: 'abc' });

function toastLines(): string[] {
	return get(toasts).map((toast) => toast.message);
}

beforeEach(() => {
	toasts.set([]);
	songList.set([FIRST, SECOND]);
});

afterEach(() => {
	resetLibraryDataForTests();
	vi.resetAllMocks();
});

describe('renaming a song', () => {
	it('writes the new title into the list for the named song only and says so', async () => {
		vi.mocked(renameSong).mockResolvedValue({ ...SECOND, title: 'Renamed' });

		await renameSongTo('s2', 'Renamed');

		expect(get(songList).map((song) => song.title)).toEqual(['First', 'Renamed']);
		expect(toastLines()).toEqual([words['songPage.renamed']]);
	});

	it('toasts the refusal and throws, so the title field stays open', async () => {
		vi.mocked(renameSong).mockRejectedValue(new Error('boom'));

		await expect(renameSongTo('s1', 'X')).rejects.toThrow('boom');

		expect(get(songList)[0].title).toBe('First');
		expect(toastLines()).toHaveLength(1);
	});
});

describe('sharing a song', () => {
	it('marks the named song shared with its link', async () => {
		vi.mocked(shareSong).mockResolvedValue({
			status: 'shared',
			share_url: 'https://example.test/share/xyz',
			share_slug: 'xyz',
			songs_without_playable_take: []
		});

		await enableSongSharing('s1');

		expect(get(songList)[0]).toMatchObject({ is_shared: true, share_slug: 'xyz' });
		expect(get(songList)[1].share_slug).toBe('abc');
	});

	it('clears the named song’s share', async () => {
		vi.mocked(unshareSong).mockResolvedValue(undefined);

		await disableSongSharing('s2');

		expect(get(songList)[1]).toMatchObject({ is_shared: false, share_slug: null });
	});
});

describe('adding a song to a playlist', () => {
	it('adds the named song and says so', async () => {
		vi.mocked(addSongToPlaylist).mockResolvedValue(undefined);

		await addSongToPlaylistWithToast('s1', 'p1');

		expect(addSongToPlaylist).toHaveBeenCalledWith('p1', 's1');
		expect(toastLines()).toEqual([words['songPage.addedToPlaylist']]);
	});

	it('says so and throws nothing when it is refused', async () => {
		vi.mocked(addSongToPlaylist).mockRejectedValue(new Error('boom'));

		await addSongToPlaylistWithToast('s1', 'p1');

		expect(toastLines()).toHaveLength(1);
	});
});

describe('deleting a song with undo', () => {
	it('removes the song, runs the caller’s follow-up and offers Undo', async () => {
		vi.mocked(deleteSong).mockResolvedValue(undefined);
		const ondeleted = vi.fn();

		await deleteSongWithUndo('s1', ondeleted);

		expect(get(songList).map((song) => song.id)).toEqual(['s2']);
		expect(ondeleted).toHaveBeenCalledOnce();
		expect(get(toasts)[0].action?.label).toBe(words['songPage.undo']);
	});

	it('brings the song back when Undo is taken', async () => {
		vi.mocked(deleteSong).mockResolvedValue(undefined);
		vi.mocked(restoreSong).mockResolvedValue(FIRST);
		await deleteSongWithUndo('s1');

		await get(toasts)[0].action?.handler();

		expect(get(songList).map((song) => song.id)).toContain('s1');
		expect(toastLines()).toContain(words['songPage.restored']);
	});

	it('keeps the song and runs no follow-up when the delete is refused', async () => {
		vi.mocked(deleteSong).mockRejectedValue(new Error('boom'));
		const ondeleted = vi.fn();

		await deleteSongWithUndo('s1', ondeleted);

		expect(get(songList)).toHaveLength(2);
		expect(ondeleted).not.toHaveBeenCalled();
		expect(toastLines()).toHaveLength(1);
	});
});
