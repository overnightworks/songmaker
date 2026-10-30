import { describe, expect, it } from 'vitest';
import type { WhisperCue } from '#lib/api/types.ts';
import {
	fromSharedAlbum,
	fromSharedGeneration,
	fromSharedPlaylist,
	fromSharedSong,
	playableTracks,
	trackPlaybackInfo,
	type SharedTrack
} from './sharedCollection';

// The media half every share payload carries for its take. Defaults to the
// "no pick" shape so each test spells out only the fields it is about.
function media(
	overrides: {
		generation_id?: string | null;
		audio_duration?: number | null;
		lyrics?: string | null;
		whisper_cues?: WhisperCue[] | null;
	} = {}
) {
	return {
		generation_id: null,
		audio_duration: null,
		lyrics: null,
		whisper_cues: null,
		...overrides
	};
}

function track(overrides: Partial<SharedTrack> & { key: string; title: string }): SharedTrack {
	return {
		subtitle: null,
		albumTitle: null,
		audioUrl: null,
		durationSec: null,
		lyrics: null,
		cues: null,
		cover: null,
		...overrides
	};
}

const CUES: WhisperCue[] = [
	{ start: 0, end: 2, text: 'the lantern hums', words: [{ start: 0, end: 1, text: 'the' }] }
];

describe('fromSharedAlbum', () => {
	it('maps an album payload to a collection view with one track per song', () => {
		const view = fromSharedAlbum({
			title: 'Neon Static',
			artist: 'Artist',
			subtitle: '',
			year: '2026',
			cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' },
			songs: [
				{
					id: 's1',
					title: 'First',
					track_number: 1,
					audio_url: '/audio/first.mp3',
					...media({
						generation_id: 'g1',
						audio_duration: 128,
						lyrics: 'verse one',
						whisper_cues: CUES
					})
				},
				{ id: 's2', title: 'Second', track_number: 2, audio_url: null, ...media() }
			]
		});

		expect(view.kind).toBe('album');
		expect(view.title).toBe('Neon Static');
		expect(view.artist).toBe('Artist');
		expect(view.year).toBe('2026');
		expect(view.cover).toEqual({ card: '/cover-card.jpg', detail: '/cover-detail.jpg' });
		expect(view.tracks).toEqual([
			track({
				key: 's1',
				title: 'First',
				audioUrl: '/audio/first.mp3',
				durationSec: 128,
				lyrics: 'verse one',
				cues: CUES
			}),
			track({ key: 's2', title: 'Second' })
		]);
	});

	it('normalizes an empty year to null', () => {
		const view = fromSharedAlbum({
			title: 'Album',
			artist: 'Artist',
			subtitle: '',
			year: '',
			songs: []
		});
		expect(view.year).toBeNull();
	});
});

describe('fromSharedPlaylist', () => {
	it('1374_rule_5 maps each playlist entry album separately from its artist', () => {
		const view = fromSharedPlaylist({
			title: 'Late Night Mix',
			cover: {
				card: '/shared/playlist/mix/cover?variant=card&v=uploaded.png',
				detail: '/shared/playlist/mix/cover?variant=detail&v=uploaded.png'
			},
			album_covers: [
				{
					card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
					detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
				}
			],
			entries: [
				{
					entry_id: 'e1',
					song_title: 'First',
					album_title: 'Album One',
					artist: 'Artist One',
					generation_number: 1,
					audio_url: '/audio/first.mp3',
					album_cover: {
						card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
						detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
					},
					...media({ audio_duration: 95, lyrics: 'verse one', whisper_cues: CUES })
				},
				{
					entry_id: 'e2',
					song_title: 'Second',
					album_title: 'Album Two',
					artist: 'Artist Two',
					generation_number: 2,
					audio_url: null,
					...media()
				}
			]
		});

		expect(view.kind).toBe('playlist');
		expect(view.title).toBe('Late Night Mix');
		expect(view.cover).toEqual({
			card: '/shared/playlist/mix/cover?variant=card&v=uploaded.png',
			detail: '/shared/playlist/mix/cover?variant=detail&v=uploaded.png'
		});
		expect(view.playlistCovers).toEqual([
			{
				card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
				detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
			}
		]);
		expect(view.tracks).toEqual([
			track({
				key: 'e1',
				title: 'First',
				subtitle: 'Artist One',
				albumTitle: 'Album One',
				audioUrl: '/audio/first.mp3',
				durationSec: 95,
				lyrics: 'verse one',
				cues: CUES,
				cover: {
					card: '/shared/playlist/mix/album-cover/a1?variant=card&v=album.png',
					detail: '/shared/playlist/mix/album-cover/a1?variant=detail&v=album.png'
				}
			}),
			track({ key: 'e2', title: 'Second', subtitle: 'Artist Two', albumTitle: 'Album Two' })
		]);
	});
});

describe('fromSharedSong and fromSharedGeneration', () => {
	it('produces a one-track collection for a shared song', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			audio_url: '/audio/solo.mp3',
			cover: { card: '/c.jpg', detail: '/d.jpg' },
			album_cover: { card: '/album-c.jpg', detail: '/album-d.jpg' },
			...media({ audio_duration: 210, lyrics: 'solo lyrics', whisper_cues: CUES })
		});

		expect(view.kind).toBe('song');
		expect(view.albumTitle).toBe('Album');
		expect(view.cover).toEqual({ card: '/album-c.jpg', detail: '/album-d.jpg' });
		expect(view.tracks).toEqual([
			track({
				key: 'single',
				title: 'Solo Track',
				audioUrl: '/audio/solo.mp3',
				durationSec: 210,
				lyrics: 'solo lyrics',
				cues: CUES
			})
		]);
	});

	it('does not use a song cover as the shared album cover', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			audio_url: null,
			cover: { card: '/song-c.jpg', detail: '/song-d.jpg' },
			...media()
		});

		expect(view.cover).toBeNull();
	});

	it('produces a one-track collection for a shared take', () => {
		const view = fromSharedGeneration({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			generation_number: 3,
			album_cover: { card: '/album-c.jpg', detail: '/album-d.jpg' },
			audio_url: '/audio/take3.mp3',
			...media({ audio_duration: 187, lyrics: 'take lyrics', whisper_cues: CUES })
		});

		expect(view.kind).toBe('take');
		expect(view.cover).toEqual({ card: '/album-c.jpg', detail: '/album-d.jpg' });
		expect(view.tracks).toEqual([
			track({
				key: 'single',
				title: 'Solo Track',
				audioUrl: '/audio/take3.mp3',
				durationSec: 187,
				lyrics: 'take lyrics',
				cues: CUES
			})
		]);
	});

	it('normalizes an empty album_title to null', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: '',
			audio_url: null,
			...media()
		});
		expect(view.albumTitle).toBeNull();
	});
});

describe('playableTracks', () => {
	const tracks: SharedTrack[] = [
		track({ key: 's1', title: 'First', audioUrl: '/audio/first.mp3' }),
		track({ key: 's2', title: 'Second (unpicked)' }),
		track({ key: 's3', title: 'Third', audioUrl: '/audio/third.mp3' })
	];

	it('drops tracks whose audio_url is null instead of showing a disabled row', () => {
		expect(playableTracks(tracks).map((t) => t.key)).toEqual(['s1', 's3']);
	});

	it('returns an empty list for an all-unpicked collection', () => {
		expect(playableTracks([tracks[1]])).toEqual([]);
	});
});

describe('trackPlaybackInfo', () => {
	it('uses the collection title as the album for an album track', () => {
		const view = fromSharedAlbum({
			title: 'Neon Static',
			artist: 'Artist',
			subtitle: '',
			year: '',
			songs: [
				{
					id: 's1',
					title: 'First',
					track_number: 1,
					audio_url: '/audio/first.mp3',
					...media()
				}
			]
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.songId).toBe('s1');
		expect(info.songTitle).toBe('First');
		expect(info.artist).toBe('Artist');
		expect(info.albumTitle).toBe('Neon Static');
		expect(info.generation.id).toBe('s1');
		expect(info.lyrics).toBeNull();
	});

	it('carries the shared take lyrics and cues so Now Playing can follow along', () => {
		const view = fromSharedGeneration({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			generation_number: 3,
			audio_url: '/audio/take3.mp3',
			...media({ lyrics: 'the lantern hums', whisper_cues: CUES })
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.lyrics).toBe('the lantern hums');
		expect(info.generation.whisper_cues).toEqual(CUES);
		expect(info.generation.version_lyrics).toBe('the lantern hums');
	});

	it('1374_rule_5 uses the entry artist and album for classic playlist playback', () => {
		const view = fromSharedPlaylist({
			title: 'Late Night Mix',
			album_covers: [],
			entries: [
				{
					entry_id: 'e1',
					song_title: 'First',
					album_title: 'Album One',
					artist: 'Artist One',
					generation_number: 1,
					audio_url: '/audio/first.mp3',
					...media()
				}
			]
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.artist).toBe('Artist One');
		expect(info.albumTitle).toBe('Album One');
	});

	it('uses the collection album_title for a song or take track', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			audio_url: '/audio/solo.mp3',
			...media()
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.artist).toBe('Artist');
		expect(info.albumTitle).toBe('Album');
	});
});
