import { describe, expect, it } from 'vitest';
import {
	filterMentionItems,
	mentionQueryAtCursor,
	replaceMentionToken
} from './mentions';
import type { SongItem, VersionItem } from '$lib/api/types';

const songs = [
	{ id: 's1', title: 'Thunder', album_id: 'a1', album_title: 'Rock' },
	{ id: 's2', title: 'Rain', album_id: 'a1', album_title: 'Rock' },
	{ id: 's3', title: 'Storm', album_id: 'a2', album_title: 'Other' }
] as SongItem[];

const versions = [
	{ id: 'v1', version_number: 1 },
	{ id: 'v2', version_number: 2 }
] as VersionItem[];

describe('mention picker', () => {
	it('reads the @-token at the cursor', () => {
		expect(mentionQueryAtCursor('see @ra', 7)).toEqual({ query: 'ra', atIndex: 4 });
		expect(mentionQueryAtCursor('no mention', 4)).toBeNull();
	});

	it('replaces only the active token', () => {
		expect(replaceMentionToken('see @ra', 7, '@Rain ')).toBe('see @Rain ');
	});

	it('lists album, matching versions, and other songs once', () => {
		const items = filterMentionItems({
			query: '',
			albumMentioned: false,
			currentAlbumId: 'a1',
			currentSongId: 's1',
			versions,
			allSongs: songs,
			mentionedSongIds: ['s3'],
			mentionedVersionIds: []
		});
		expect(items.some((item) => item.type === 'album')).toBe(true);
		expect(items.filter((item) => item.type === 'song').map((item) => item.item.id)).toEqual([
			's2'
		]);
	});

	it('filters versions by @v prefix and skips already selected ones', () => {
		const items = filterMentionItems({
			query: 'v2',
			albumMentioned: true,
			currentAlbumId: 'a1',
			currentSongId: 's1',
			versions,
			allSongs: songs,
			mentionedSongIds: [],
			mentionedVersionIds: ['v1']
		});
		const versionIds = items
			.filter((item) => item.type === 'version')
			.map((item) => item.item.id);
		expect(versionIds).toEqual(['v2']);
	});

	it('returns no matches for an unknown query', () => {
		const items = filterMentionItems({
			query: 'zzzz',
			albumMentioned: true,
			currentAlbumId: 'a1',
			currentSongId: 's1',
			versions,
			allSongs: songs,
			mentionedSongIds: [],
			mentionedVersionIds: []
		});
		expect(items).toEqual([]);
	});
});
