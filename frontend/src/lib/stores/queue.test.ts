import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import {
	makeAlbum,
	makeGeneration as makeGen,
	makePlaylistEntry,
	makeSong
} from '#lib/test-utils/factories.ts';
import { openCollection } from '#lib/stores/collection.ts';
import { albumList } from '#lib/stores/libraryData.ts';
import {
	genDefaults,
	makePlayback,
	playlistEntryDefaults,
	playlistQueue,
	queuedSongDefaults
} from '#lib/test-utils/queue-scenarios.ts';
import { groupTakes } from '#lib/stores/takeFolds.ts';
import {
	adjacentQueueTake,
	buildQueueViewModel,
	playbackSource,
	queueContext,
	songTakeQueue
} from '#lib/stores/queue.ts';

afterEach(() => {
	albumList.set([]);
	queueContext.set({ type: 'library' });
});

describe('playbackSource', () => {
	beforeEach(() => {
		albumList.set([makeAlbum({ created_at: '', title: 'Nightdrive' })]);
		openCollection.set({ kind: 'playlist', id: 'p9' });
	});

	it.each([
		[
			'an album queue names its album',
			{ type: 'album' as const, albumId: 'a1' },
			{ kind: 'album', id: 'a1', title: 'Nightdrive' }
		],
		[
			'a playlist queue names its playlist',
			{
				type: 'playlist' as const,
				playlist: { id: 'p1', title: 'Late Drives' },
				entries: [],
				index: 0
			},
			{ kind: 'playlist', id: 'p1', title: 'Late Drives' }
		],
		[
			'a song queue names its song',
			{ type: 'song' as const, songId: 's1', songTitle: 'Cold Harbour', takes: [], index: 0 },
			{ kind: 'song', id: 's1', title: 'Cold Harbour' }
		],
		['a library queue names no source', { type: 'library' as const }, null],
		[
			'an album queue whose album is not loaded names no source',
			{ type: 'album' as const, albumId: 'a-missing' },
			null
		]
	])('%s, whatever collection is open', (_name, ctx, expected) => {
		queueContext.set(ctx);
		expect(get(playbackSource)).toEqual(expected);
	});
});

describe('buildQueueViewModel', () => {
	it('uses the native queue position when no playback is current', () => {
		const first = makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()));
		const second = makePlayback(
			makeGen({ ...genDefaults, id: 'g2' }),
			makeSong({ ...queuedSongDefaults(), id: 's2' })
		);

		const vm = buildQueueViewModel({ type: 'library', takes: [first, second], index: 1 }, null);

		expect(vm.currentIndex).toBe(1);
		expect(vm.upNext?.generationId).toBe('g1');
	});

	it('classic-mode contexts without takes render current only, with no up next', () => {
		const vm = buildQueueViewModel(
			{ type: 'library' },
			makePlayback(makeGen(genDefaults), makeSong(queuedSongDefaults()))
		);
		expect(vm.items).toEqual([]);
		expect(vm.currentIndex).toBe(-1);
		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a native library/album queue', () => {
		const songs = [makeSong(queuedSongDefaults()), makeSong({ ...queuedSongDefaults(), id: 's2' })];
		const current = makePlayback(
			makeGen({ ...genDefaults, version_number: 3, generation_number: 2, audio_duration_sec: 200 }),
			songs[0]
		);
		const next = makePlayback(makeGen({ ...genDefaults, id: 'g2' }), songs[1]);
		const ctx = { type: 'library' as const, takes: [current, next], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.items.map((item) => item.generationId)).toEqual(['g1', 'g2']);
		expect(vm.items[0]?.durationSec).toBe(200);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 3, generationNumber: 2 }));
		expect(vm.currentIndex).toBe(0);
		expect(vm.upNext).toEqual(expect.objectContaining({ generationId: 'g2' }));
	});

	it("reads only a native row's own measured duration, never the song's requested one", () => {
		// A song requested with "auto" (0) duration is the exact shape that
		// used to leak a false 0:00 through the song-level fallback (#258).
		const song = makeSong({ ...queuedSongDefaults(), audio_duration: 0 });
		const ownDuration = makePlayback(makeGen({ ...genDefaults, audio_duration_sec: 141 }), song);
		const unmeasured = makePlayback(makeGen({ ...genDefaults, id: 'g2' }), song);
		const ctx = { type: 'library' as const, takes: [ownDuration, unmeasured], index: 0 };

		const vm = buildQueueViewModel(ctx, ownDuration);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('shows a native row\'s own measured length, not the "auto" (0) duration it was requested with', () => {
		const song = makeSong({ ...queuedSongDefaults(), audio_duration: 200 });
		const requestedAuto = makePlayback(
			makeGen({
				...genDefaults,
				generation_params: { audio_duration: 0 },
				audio_duration_sec: 188
			}),
			song
		);
		const ctx = { type: 'library' as const, takes: [requestedAuto], index: 0 };

		const vm = buildQueueViewModel(ctx, requestedAuto);

		expect(vm.items.map((item) => item.durationSec)).toEqual([188]);
	});

	it("reads a playlist row's own measured duration, showing none for an unmeasured entry", () => {
		const entries = [
			makePlaylistEntry({ ...playlistEntryDefaults, id: 'e1', audio_duration: 141 }),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e2',
				generation_id: 'g2',
				audio_duration: null
			})
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.items.map((item) => item.durationSec)).toEqual([141, null]);
	});

	it('carries no version number for a native take with no version (library pool)', () => {
		const song = makeSong(queuedSongDefaults());
		const current = makePlayback(
			makeGen({ ...genDefaults, version_number: null, generation_number: 5 }),
			song
		);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.items[0]).toEqual(
			expect.objectContaining({ versionNumber: null, generationNumber: 5 })
		);
	});

	it('has no up next for a single-item native queue', () => {
		const song = makeSong(queuedSongDefaults());
		const current = makePlayback(makeGen(genDefaults), song);
		const ctx = { type: 'library' as const, takes: [current], index: 0 };

		const vm = buildQueueViewModel(ctx, current);

		expect(vm.upNext).toBeNull();
	});

	it('exposes the current item and up next for a playlist queue', () => {
		const entries = [
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e1',
				song_title: 'First',
				version_number: 4
			}),
			makePlaylistEntry({
				...playlistEntryDefaults,
				id: 'e2',
				generation_id: 'g2',
				song_title: 'Second'
			})
		];
		const ctx = playlistQueue(entries, 0);

		const vm = buildQueueViewModel(ctx, null);

		expect(vm.currentIndex).toBe(0);
		expect(vm.items[0]).toEqual(expect.objectContaining({ versionNumber: 4, generationNumber: 1 }));
		expect(vm.upNext).toEqual(expect.objectContaining({ generationId: 'g2' }));
	});
});

describe('songTakeQueue', () => {
	function take(id: string, versionNumber: number | null, overrides = {}) {
		return makeGen({
			...genDefaults,
			id,
			version_id: versionNumber === null ? null : `v${versionNumber}`,
			version_number: versionNumber,
			...overrides
		});
	}

	const song = makeSong({
		...queuedSongDefaults(),
		generations: [
			take('g-v1', 1),
			take('g-imported', null),
			take('g-v3a', 3),
			take('g-archived', 3, { is_archived: true }),
			take('g-v2', 2),
			take('g-v3b', 3)
		]
	});

	// Spec: REQ-LISTENING-08 -- the song's takes follow in the order the take list shows them.
	it("holds the playable takes in the take list's order, the tapped one in play", () => {
		const shown = groupTakes(song.generations, 3);
		const listOrder = [shown.current, ...shown.earlier]
			.flatMap((group) => group?.generations ?? [])
			.filter((gen) => !gen.is_archived)
			.map((gen) => gen.id);

		const queue = songTakeQueue(song, 'g-v2');

		expect(queue?.takes.map((queued) => queued.generation.id)).toEqual(listOrder);
		expect(queue && queue.takes[queue.index].generation.id).toBe('g-v2');
	});

	it('wraps from the last take to the first and names the song once', () => {
		const queue = songTakeQueue(song, 'g-imported');
		if (!queue) throw new Error('Expected a queue');

		const next = adjacentQueueTake(queue, queue.takes[queue.index]);

		expect(next.kind === 'take' && next.take.generation.id).toBe('g-v3a');
		expect(buildQueueViewModel(queue, null).again).toBe(song.title);
	});

	it.each(['g-archived', 'g-absent'])('is nothing for the unplayable or absent take %s', (id) => {
		expect(songTakeQueue(song, id)).toBeNull();
	});
});
