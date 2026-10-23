import { describe, expect, it } from 'vitest';
import { makeAlbum, makeGeneration, makeSong } from '$lib/test-utils/factories';
import type { GenerationItem } from '$lib/api/types';
import type { AlbumSongsLoadStatus } from '$lib/stores/libraryData';
import {
	albumHasPlayableTake,
	albumRowOffersPlay,
	bestTake,
	queueHoldsOneTake,
	songHasPlayableTake,
	songPlayability,
	songTakesLoaded
} from './playable';

const playable = (overrides: Partial<GenerationItem> = {}) => makeGeneration(overrides);
const archived = () => makeGeneration({ is_archived: true });
const fileless = () => makeGeneration({ mp3_path: '' });

function songWith(generation_count: number, generations: GenerationItem[]) {
	return makeSong({ generation_count, generations });
}

type SongPlayability = ReturnType<typeof songPlayability>;

describe('1354_rule_11 song playability (defect:#1386)', () => {
	it.each<[string, SongPlayability, ReturnType<typeof songWith>]>([
		['loaded and all archived', 'none', songWith(2, [archived(), archived()])],
		['loaded with an empty file path', 'none', songWith(1, [fileless()])],
		[
			'loaded with one playable take among archived ones',
			'playable',
			songWith(2, [archived(), playable()])
		],
		['not loaded, with a count above 0', 'unknown', songWith(2, [playable()])],
		['without any take', 'none', songWith(0, [])]
	])('a song %s is %s', (_, expected, song) => {
		expect(songPlayability(song)).toBe(expected);
		expect(songHasPlayableTake(song)).toBe(expected !== 'none');
	});

	it('1354_rule_11: counts takes as loaded once as many are here as the song counts', () => {
		expect(songTakesLoaded(songWith(2, [playable()]))).toBe(false);
		expect(songTakesLoaded(songWith(2, [playable(), archived()]))).toBe(true);
	});

	it('1354_rule_11: picks the picked playable take, else the first playable one', () => {
		const first = playable({ id: 'first' });
		const picked = playable({ id: 'picked', is_picked: true });
		const archivedPick = makeGeneration({ id: 'old', is_picked: true, is_archived: true });

		expect(bestTake(songWith(3, [archivedPick, first, picked]))?.id).toBe('picked');
		expect(bestTake(songWith(2, [archivedPick, first]))?.id).toBe('first');
		expect(bestTake(songWith(1, [archived()]))).toBeUndefined();
	});
});

describe('1354_rule_11 album playability', () => {
	const none = songWith(1, [archived()]);
	const some = songWith(1, [playable()]);
	const unknown = songWith(1, []);
	const album = (has_playable_take: boolean) => makeAlbum({ has_playable_take });

	it.each([
		[
			'the server says true but complete songs hold nothing to hear',
			true,
			[none, none],
			true,
			false
		],
		['the server says true and no songs came', true, [], true, false],
		['the server says false but a loaded song is playable', false, [none, some], false, true],
		['songs are unknown, the server flag stands (true)', true, [none, unknown], true, true],
		['songs are unknown, the server flag stands (false)', false, [none, unknown], true, false],
		['the songs are a partial set, the server flag stands', true, [none], false, true]
	])('when %s', (_, serverFlag, songs, songsComplete, expected) => {
		expect(albumHasPlayableTake(album(serverFlag), songs, { songsComplete })).toBe(expected);
	});
});

describe('defect:#1550 album row play', () => {
	const album = makeAlbum({ id: 'album', has_playable_take: true });
	const silent = [songWith(1, [archived()])];

	it.each<[string, Readonly<Record<string, AlbumSongsLoadStatus>>, boolean]>([
		['songs never loaded, the server flag stands', {}, true],
		['songs still loading, the server flag stands', { album: 'loading' }, true],
		['songs settled with nothing to hear', { album: 'idle' }, false]
	])('when %s', (_, songLoads, expected) => {
		expect(albumRowOffersPlay(album, silent, songLoads)).toBe(expected);
	});
});

describe('1831_N1 the queue holds one take', () => {
	const song = () => songWith(1, [playable()]);
	it.each<[string, number, Parameters<typeof queueHoldsOneTake>[1], boolean]>([
		['non-album with one item', 1, null, true],
		['non-album with two items', 2, null, false],
		['album with one settled playable song', 1, { songs: [song()], load: 'idle' }, true],
		['album with many songs', 1, { songs: [song(), song()], load: 'idle' }, false],
		['album with an unsettled load', 1, { songs: [song()], load: 'loading' }, false],
		['album with a load never started', 1, { songs: [], load: undefined }, false],
		['empty queue', 0, null, false],
		['empty queue in an album', 0, { songs: [], load: 'idle' }, false]
	])('%s', (_name, queuedCount, album, expected) => {
		expect(queueHoldsOneTake(queuedCount, album)).toBe(expected);
	});
});
