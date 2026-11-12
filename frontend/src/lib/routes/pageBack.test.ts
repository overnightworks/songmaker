import { describe, expect, it } from 'vitest';
import { makeAlbum, makePlaylist, makeSong } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';
import { backLabel, backTargetName, pageBackShown } from './pageBack';

const titles = {
	albums: [makeAlbum({ id: 'a1', title: 'Lanterns' })],
	playlists: [makePlaylist({ slug: 'night-drive', title: 'Night Drive' })],
	songs: [makeSong({ album_id: 'a1', slug: 'quiet-wind', title: 'Quiet Wind' })]
};

describe('1354_rule_25: shared page Back readers', () => {
	it.each([
		['/', words['places.home']],
		['/library', words['places.library']],
		['/playlists', words['places.playlists']],
		['/settings', words['places.settings']],
		['/album/a1', 'Lanterns'],
		['/playlist/night-drive', 'Night Drive'],
		['/album/a1/quiet-wind', 'Quiet Wind'],
		['/album/a1/quiet-wind/take/2', 'Quiet Wind'],
		['/album/missing', words['pageBack.album']],
		['/playlist/missing', words['pageBack.playlist']],
		['/album/missing/song/take/1', words['pageBack.song']],
		['/unknown', words['pageBack.previousPage']]
	])('names %s as %s', (pathname, name) => {
		expect(
			backTargetName({
				pathname: '/album/a1',
				below: `https://songmaker.test${pathname}`,
				shell: 'phone',
				titles
			})
		).toBe(name);
		expect(backLabel(name)).toBe(words['pageBack.backTo']({ page: name }));
	});

	it.each([
		{ pathname: '/', below: null, shell: 'phone', shown: false },
		{
			pathname: '/library',
			below: 'https://songmaker.test/album/a1',
			shell: 'phone',
			shown: false
		},
		{ pathname: '/playlists', below: 'https://songmaker.test/', shell: 'phone', shown: false },
		{ pathname: '/album/a1', below: null, shell: 'phone', shown: true },
		{ pathname: '/album/a1', below: null, shell: 'desktop', shown: false },
		{ pathname: '/library', below: 'https://songmaker.test/', shell: 'desktop', shown: true }
	] as const)('shows Back=$shown on $shell $pathname', ({ shown, ...context }) => {
		expect(pageBackShown(context)).toBe(shown);
	});

	it.each([
		['/album/a1', words['places.library']],
		['/playlist/night-drive', words['places.playlists']],
		['/settings/voices', words['places.settings']],
		['/settings', words['places.library']]
	])('names the cold fallback for %s as %s', (pathname, expected) => {
		expect(backTargetName({ pathname, below: null, titles, shell: 'phone' })).toBe(expected);
	});
});

describe('1354_rule_32: song Back names its destination', () => {
	it.each([
		{ pathname: '/album/a1/quiet-wind', below: null, name: 'Lanterns' },
		{ pathname: '/album/a1/quiet-wind/take/2', below: null, name: 'Lanterns' },
		{ pathname: '/album/missing/song', below: null, name: words['pageBack.album'] },
		{
			pathname: '/album/a1/quiet-wind',
			below: 'https://songmaker.test/',
			name: words['places.home']
		},
		{
			pathname: '/album/a1/quiet-wind',
			below: 'https://songmaker.test/playlist/night-drive',
			name: 'Night Drive'
		}
	])('names $pathname with $below below as $name', ({ name, ...standing }) => {
		expect(backTargetName({ ...standing, titles, shell: 'phone' })).toBe(name);
	});
});
