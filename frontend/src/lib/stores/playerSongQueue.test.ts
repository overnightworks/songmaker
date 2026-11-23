import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { SongItem } from '#lib/api/types.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { makeGeneration as makeGen, makeSong } from '#lib/test-utils/factories.ts';
import { genDefaults, makePlayback, queuedSongDefaults } from '#lib/test-utils/queue-scenarios.ts';
import { songList } from './libraryData';
import {
	jumpToQueueIndex,
	playNextSong,
	playTake,
	setShuffle,
	shuffleEnabled,
	toggleShuffle
} from './player';
import { playbackSource, queueContext } from './queue';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

vi.mock('#lib/api/client.ts', () => ({
	fetchLibraryPoolQueue: vi.fn(),
	fetchPlaylist: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null })
}));

vi.mock('#lib/api/songs.ts', () => ({
	recordSongListen: vi.fn().mockResolvedValue(undefined)
}));

beforeEach(() => {
	vi.spyOn(audioPlayer, 'load').mockImplementation((info) => {
		audioPlayer.current = info;
	});
	vi.spyOn(audioPlayer, 'preload').mockImplementation(() => {});
});

afterEach(() => {
	vi.clearAllMocks();
	vi.restoreAllMocks();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	songList.set([]);
	queueContext.set({ type: 'library' });
	setShuffle(false);
});

describe('a tap on a take row', () => {
	function versionedSong(): SongItem {
		const take = (id: string, versionNumber: number, generationNumber: number) =>
			makeGen({
				...genDefaults,
				id,
				version_id: `v${versionNumber}`,
				version_number: versionNumber,
				generation_number: generationNumber
			});
		return makeSong({
			...queuedSongDefaults(),
			generations: [
				take('g-v1', 1, 1),
				take('g-v2a', 2, 1),
				take('g-v2b', 2, 2),
				makeGen({
					...genDefaults,
					id: 'g-archived',
					version_id: 'v2',
					version_number: 2,
					is_archived: true
				}),
				take('g-v3', 3, 1)
			]
		});
	}

	function queuedGenerationIds(): string[] {
		const ctx = get(queueContext);
		return ctx.type === 'song' ? ctx.takes.map((take) => take.generation.id) : [];
	}

	// Spec: REQ-LISTENING-08 -- a tap on a take row plays that take and starts the song's queue on it.
	it('a take row plays the tapped take in a queue of its song', () => {
		const song = versionedSong();

		playTake(song.generations[2], song);

		expect(audioPlayer.current?.generation.id).toBe('g-v2b');
		expect(get(queueContext)).toEqual(expect.objectContaining({ type: 'song', songId: song.id }));
		expect(get(playbackSource)).toEqual({ kind: 'song', id: song.id, title: song.title });
	});

	it('a take archived after the queue was built is skipped when its turn comes', () => {
		const song = versionedSong();
		songList.set([song]);
		playTake(song.generations[1], song);
		songList.set([
			{
				...song,
				generations: song.generations.map((gen) =>
					gen.id === 'g-v2b' ? { ...gen, is_archived: true } : gen
				)
			}
		]);

		playNextSong();

		expect(audioPlayer.current?.generation.id).toBe('g-v1');
	});

	function withTakeArchived(song: SongItem, id: string): SongItem {
		return {
			...song,
			generations: song.generations.map((gen) =>
				gen.id === id ? { ...gen, is_archived: true } : gen
			)
		};
	}

	it('a take archived while it waits as the next one is put right at once', () => {
		const song = versionedSong();
		songList.set([song]);
		playTake(song.generations[4], song);

		songList.set([withTakeArchived(song, 'g-v2a')]);

		expect(vi.mocked(audioPlayer.preload).mock.lastCall?.[0]?.generation.id).toBe('g-v2b');
	});

	it('a take archived while it waits as the only next one is taken back', () => {
		const song = versionedSong();
		const pair = { ...song, generations: [song.generations[1], song.generations[2]] };
		songList.set([pair]);
		playTake(pair.generations[0], pair);
		const withdraw = vi.spyOn(audioPlayer, 'withdrawPreload').mockImplementation(() => {});

		songList.set([withTakeArchived(pair, 'g-v2b')]);

		expect(withdraw).toHaveBeenCalled();
	});

	it('a Queue row of a take archived since the queue was built plays nothing', () => {
		const song = versionedSong();
		songList.set([song]);
		playTake(song.generations[4], song);
		songList.set([withTakeArchived(song, 'g-v2b')]);
		vi.mocked(audioPlayer.load).mockClear();

		jumpToQueueIndex(2);

		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('toggling shuffle reorders the whole song queue and back, though the song list holds only part of its takes', async () => {
		const song = versionedSong();
		songList.set([{ ...song, generations: [song.generations[4]] }]);
		playTake(song.generations[4], song);
		vi.spyOn(Math, 'random').mockReturnValue(0);

		await toggleShuffle();
		const shuffledIds = queuedGenerationIds();
		await toggleShuffle();

		expect(shuffledIds).not.toEqual(['g-v3', 'g-v2a', 'g-v2b', 'g-v1']);
		expect([...shuffledIds].sort()).toEqual(['g-v1', 'g-v2a', 'g-v2b', 'g-v3']);
		expect(queuedGenerationIds()).toEqual(['g-v3', 'g-v2a', 'g-v2b', 'g-v1']);
	});

	it('a tap says play from here, so a leftover shuffle does not reorder the queue', () => {
		setShuffle(true);
		const song = versionedSong();

		playTake(song.generations[0], song);

		expect(get(shuffleEnabled)).toBe(false);
		expect(queuedGenerationIds()).toEqual(['g-v3', 'g-v2a', 'g-v2b', 'g-v1']);
	});

	it('a take that cannot play starts nothing', () => {
		const song = versionedSong();

		playTake(song.generations[3], song);

		expect(audioPlayer.load).not.toHaveBeenCalled();
	});

	it('toggles pause instead of restarting when the row take is already playing', () => {
		const gen = makeGen(genDefaults);
		const song = makeSong(queuedSongDefaults());
		audioPlayer.current = makePlayback(gen, song);
		audioPlayer.status = 'playing';
		const toggle = vi.spyOn(audioPlayer, 'toggle').mockImplementation(() => {});

		playTake(gen, song);

		expect(toggle).toHaveBeenCalledOnce();
		expect(audioPlayer.load).not.toHaveBeenCalled();
	});
});
