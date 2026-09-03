import { describe, expect, it } from 'vitest';

import {
	albumRoutePath,
	isAlbumRoutePath,
	isPlaylistRoutePath,
	isSongRoutePath,
	isTakeRoutePath,
	legacySongRoutePath,
	libraryRouteShape,
	pendingTakeRoutePath,
	playlistRoutePath,
	readLegacySongQuery,
	songRoutePath,
	takeRoutePath
} from './addresses';

describe('library route addresses', () => {
	it.each([
		['album', () => albumRoutePath('an field'), '/album/an%20field'],
		['song', () => songRoutePath('an field', 'tide / turn'), '/album/an%20field/tide%20%2F%20turn'],
		['take', () => takeRoutePath('anfield', 'tide', 3), '/album/anfield/tide/take/3'],
		['playlist', () => playlistRoutePath('friday night'), '/playlist/friday%20night']
	])('builds a %s route', (_name, build, path) => {
		expect(build()).toBe(path);
	});

	it.each([
		['album', isAlbumRoutePath, '/album/anfield', true],
		['album', isAlbumRoutePath, '/album/anfield/tide', true],
		['album', isAlbumRoutePath, '/album/anfield/tide/take/3', true],
		['album', isAlbumRoutePath, '/album/', false],
		['album', isAlbumRoutePath, '/', false],
		['album', isAlbumRoutePath, '/settings/voices', false],
		['song', isSongRoutePath, '/album/anfield/tide', true],
		['song', isSongRoutePath, '/album/anfield/tide/take/3', true],
		['song', isSongRoutePath, '/album/anfield', false],
		['song', isSongRoutePath, '/album/anfield/', false],
		['song', isSongRoutePath, '/', false],
		['take', isTakeRoutePath, '/album/anfield/tide/take/3', true],
		['take', isTakeRoutePath, '/album/anfield/tide/take/', false],
		['take', isTakeRoutePath, '/album/anfield/tide', false],
		['take', isTakeRoutePath, '/album/anfield', false],
		['take', isTakeRoutePath, '/', false],
		['playlist', isPlaylistRoutePath, '/playlist/friday-night', true],
		['playlist', isPlaylistRoutePath, '/playlist/', false],
		['playlist', isPlaylistRoutePath, '/', false],
		['playlist', isPlaylistRoutePath, '/album/anfield', false]
	])('recognizes a %s route structurally', (_name, matches, pathname, expected) => {
		expect(matches(pathname)).toBe(expected);
	});

	it.each([
		['/', 'root'],
		['/album/anfield', 'album'],
		['/album/anfield/tide', 'album-song'],
		['/album/anfield/tide/take/3', 'album-song-take'],
		['/playlist/friday-night', 'playlist'],
		['/settings/voices', 'external']
	])('classifies %s as %s', (pathname, shape) => {
		expect(libraryRouteShape(pathname)).toBe(shape);
	});
});

describe('legacy song query addresses', () => {
	it.each([
		['song and generation', 'song=s1&gen=g1', { songId: 's1', generationId: 'g1' }],
		['song only', 'song=s1', { songId: 's1', generationId: null }],
		['generation only', 'gen=g1', { songId: null, generationId: 'g1' }]
	])('reads %s', (_name, query, expected) => {
		expect(readLegacySongQuery(new URLSearchParams(query))).toEqual(expected);
	});

	it.each([
		['s1', 'g1', '/?song=s1&gen=g1'],
		['s1', null, '/?song=s1']
	])('builds the legacy fallback route', (songId, generationId, path) => {
		expect(legacySongRoutePath(songId, generationId)).toBe(path);
	});

	it('appends a pending generation to a song route', () => {
		expect(pendingTakeRoutePath('/album/anfield/tide', 'g1')).toBe('/album/anfield/tide?gen=g1');
	});
});
