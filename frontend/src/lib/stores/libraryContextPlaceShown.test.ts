import { describe, expect, it } from 'vitest';
import { placeShown } from './libraryContext';

const places = ['home', 'library', 'playlists'] as const;
const surfaces = ['home', 'browse', 'playlists', 'detail'] as const;
const addresses = [
	{ pathname: '/', currentPlace: 'home', surface: 'home' },
	{ pathname: '/library', currentPlace: 'library', surface: 'browse' },
	{ pathname: '/playlists', currentPlace: 'playlists', surface: 'playlists' },
	{ pathname: '/settings', currentPlace: null, surface: null },
	{ pathname: '/album/a1', currentPlace: null, surface: null },
	{ pathname: '/playlist/p1', currentPlace: null, surface: null }
] as const;

const cases = addresses.flatMap((address) =>
	surfaces.flatMap((surface) =>
		[null, 'song-1'].map((songId) => ({
			pathname: address.pathname,
			surface,
			songId,
			expected: songId === null && surface === address.surface ? address.currentPlace : null
		}))
	)
);

describe('placeShown', () => {
	it.each(cases)(
		'1354_rule_40: current place at $pathname with $surface and song $songId is $expected',
		({ pathname, surface, songId, expected }) => {
			expect(places.filter((place) => placeShown(place, surface, songId, pathname))).toEqual(
				expected === null ? [] : [expected]
			);
		}
	);
});
