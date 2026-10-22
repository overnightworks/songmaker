import { describe, expect, it } from 'vitest';

import {
	albumRoutePath,
	HOME_ROUTE_PATH,
	isPlaylistRoutePath,
	isSongRoutePath,
	legacySongRoutePath,
	LIBRARY_ROUTE_PATH,
	libraryRouteShape,
	pendingTakeRoutePath,
	playlistRoutePath,
	readLegacySongQuery,
	sharePagePath,
	songAlbumRoutePath,
	songRoutePath,
	standsOnHomePage,
	standsOnLibraryPage,
	standsOnPlaylistsPage,
	takeRoutePath
} from './addresses';

describe('library route addresses', () => {
	it.each([
		['album', () => albumRoutePath('an field'), '/album/an%20field'],
		['song', () => songRoutePath('an field', 'tide / turn'), '/album/an%20field/tide%20%2F%20turn'],
		['take', () => takeRoutePath('anfield', 'tide', 3), '/album/anfield/tide/take/3'],
		['playlist', () => playlistRoutePath('friday night'), '/playlist/friday%20night'],
		['shared album', () => sharePagePath('album', 'abc'), '/share/abc'],
		['shared song', () => sharePagePath('song', 'abc'), '/share/song/abc'],
		['shared playlist', () => sharePagePath('playlist', 'abc'), '/share/playlist/abc'],
		['shared take', () => sharePagePath('gen', 'a b'), '/share/gen/a%20b']
	])('builds a %s route', (_name, build, path) => {
		expect(build()).toBe(path);
	});

	it.each([
		['song', isSongRoutePath, '/album/anfield/tide', true],
		['song', isSongRoutePath, '/album/anfield/tide/take/3', true],
		['song', isSongRoutePath, '/album/anfield', false],
		['song', isSongRoutePath, '/album/anfield/', false],
		['song', isSongRoutePath, '/', false],
		['playlist', isPlaylistRoutePath, '/playlist/friday-night', true],
		['playlist', isPlaylistRoutePath, '/playlist/', false],
		['playlist', isPlaylistRoutePath, '/', false],
		['playlist', isPlaylistRoutePath, '/album/anfield', false]
	])('recognizes a %s route structurally', (_name, matches, pathname, expected) => {
		expect(matches(pathname)).toBe(expected);
	});

	it.each([
		['/album/anfield/tide', '/album/anfield'],
		['/album/anfield/tide/take/3', '/album/anfield'],
		['/album/an%20field/tide%20%2F%20turn', '/album/an%20field'],
		['/album/anfield', null],
		['/album/anfield/', null],
		['/playlist/friday-night', null],
		['/', null]
	])('1354_rule_32: finds the song’s album address for %s', (pathname, expected) => {
		expect(songAlbumRoutePath(pathname)).toBe(expected);
	});

	it.each([
		[HOME_ROUTE_PATH, 'home'],
		[LIBRARY_ROUTE_PATH, 'library'],
		['/library/', 'external'],
		['/library/anfield', 'external'],
		['/album/', 'external'],
		['/album/anfield', 'album'],
		['/album/anfield/tide', 'album-song'],
		['/album/anfield/tide/take/3', 'album-song-take'],
		['/album/anfield/tide/take/', 'album-song'],
		['/playlist/friday-night', 'playlist'],
		['/playlists', 'playlists'],
		['/playlists/friday-night', 'external'],
		['/settings/voices', 'external']
	])('1354_rule_31: classifies %s as %s', (pathname, shape) => {
		expect(libraryRouteShape(pathname)).toBe(shape);
	});

	it.each([
		...['/', '/library', '/playlists', '/album/anfield', '/settings'].map((pathname) => ({
			page: 'Home',
			stands: standsOnHomePage,
			pathname,
			expected: pathname === HOME_ROUTE_PATH
		})),
		{ page: 'Library', stands: standsOnLibraryPage, pathname: LIBRARY_ROUTE_PATH, expected: true },
		{ page: 'Library', stands: standsOnLibraryPage, pathname: '/library/', expected: false },
		{ page: 'Library', stands: standsOnLibraryPage, pathname: HOME_ROUTE_PATH, expected: false },
		{ page: 'Library', stands: standsOnLibraryPage, pathname: '/playlists', expected: false },
		{ page: 'Library', stands: standsOnLibraryPage, pathname: '/album/anfield', expected: false },
		{ page: 'Library', stands: standsOnLibraryPage, pathname: '/settings', expected: false },
		{ page: 'Playlists', stands: standsOnPlaylistsPage, pathname: '/playlists', expected: true },
		{
			page: 'Playlists',
			stands: standsOnPlaylistsPage,
			pathname: '/playlists/friday-night',
			expected: false
		},
		{
			page: 'Playlists',
			stands: standsOnPlaylistsPage,
			pathname: HOME_ROUTE_PATH,
			expected: false
		},
		{
			page: 'Playlists',
			stands: standsOnPlaylistsPage,
			pathname: LIBRARY_ROUTE_PATH,
			expected: false
		},
		{
			page: 'Playlists',
			stands: standsOnPlaylistsPage,
			pathname: '/playlist/friday-night',
			expected: false
		},
		{ page: 'Playlists', stands: standsOnPlaylistsPage, pathname: '/settings', expected: false }
	])(
		'1354_rule_40: standing on the $page page at $pathname is $expected',
		({ stands, pathname, expected }) => {
			expect(stands(pathname)).toBe(expected);
		}
	);

	it('1354_rule_31: classifies the legacy song query address by its path alone, as Home', () => {
		const { pathname } = new URL(legacySongRoutePath('s1', 'g1'), 'http://localhost');
		expect(libraryRouteShape(pathname)).toBe('home');
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
		['s1', 'g1', `${HOME_ROUTE_PATH}?song=s1&gen=g1`],
		['s1', null, `${HOME_ROUTE_PATH}?song=s1`]
	])('builds the legacy fallback route', (songId, generationId, path) => {
		expect(legacySongRoutePath(songId, generationId)).toBe(path);
	});

	it('appends a pending generation to a song route', () => {
		expect(pendingTakeRoutePath('/album/anfield/tide', 'g1')).toBe('/album/anfield/tide?gen=g1');
	});
});
