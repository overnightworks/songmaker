import { describe, expect, it } from 'vitest';
import {
	collectionSubtitle,
	fromSharedAlbum,
	fromSharedGeneration,
	fromSharedPlaylist,
	fromSharedSong,
	playableTracks,
	trackPlaybackInfo,
	type SharedTrack
} from './sharedCollection';

describe('fromSharedAlbum', () => {
	it('maps an album payload to a collection view with one track per song', () => {
		const view = fromSharedAlbum({
			title: 'Neon Static',
			artist: 'Artist',
			subtitle: '',
			year: '2026',
			cover: { card: '/cover-card.jpg', detail: '/cover-detail.jpg' },
			songs: [
				{ id: 's1', title: 'First', track_number: 1, audio_url: '/audio/first.mp3' },
				{ id: 's2', title: 'Second', track_number: 2, audio_url: null }
			]
		});

		expect(view.kind).toBe('album');
		expect(view.title).toBe('Neon Static');
		expect(view.artist).toBe('Artist');
		expect(view.year).toBe('2026');
		expect(view.cover).toEqual({ card: '/cover-card.jpg', detail: '/cover-detail.jpg' });
		expect(view.tracks).toEqual([
			{ key: 's1', title: 'First', subtitle: null, audioUrl: '/audio/first.mp3' },
			{ key: 's2', title: 'Second', subtitle: null, audioUrl: null }
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
	it('maps a playlist payload to a collection view carrying per-entry artist', () => {
		const view = fromSharedPlaylist({
			title: 'Late Night Mix',
			entries: [
				{
					entry_id: 'e1',
					song_title: 'First',
					artist: 'Artist One',
					generation_number: 1,
					audio_url: '/audio/first.mp3'
				},
				{
					entry_id: 'e2',
					song_title: 'Second',
					artist: 'Artist Two',
					generation_number: 2,
					audio_url: null
				}
			]
		});

		expect(view.kind).toBe('playlist');
		expect(view.title).toBe('Late Night Mix');
		expect(view.tracks).toEqual([
			{ key: 'e1', title: 'First', subtitle: 'Artist One', audioUrl: '/audio/first.mp3' },
			{ key: 'e2', title: 'Second', subtitle: 'Artist Two', audioUrl: null }
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
			cover: { card: '/c.jpg', detail: '/d.jpg' }
		});

		expect(view.kind).toBe('song');
		expect(view.albumTitle).toBe('Album');
		expect(view.tracks).toEqual([
			{ key: 'single', title: 'Solo Track', subtitle: null, audioUrl: '/audio/solo.mp3' }
		]);
	});

	it('produces a one-track collection for a shared take, carrying the take number and seed', () => {
		const view = fromSharedGeneration({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			generation_number: 3,
			seed: 42,
			audio_url: '/audio/take3.mp3'
		});

		expect(view.kind).toBe('take');
		expect(view.takeNumber).toBe(3);
		expect(view.seed).toBe(42);
		expect(view.tracks).toEqual([
			{ key: 'single', title: 'Solo Track', subtitle: null, audioUrl: '/audio/take3.mp3' }
		]);
	});

	it('normalizes an empty album_title to null', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: '',
			audio_url: null
		});
		expect(view.albumTitle).toBeNull();
	});
});

describe('playableTracks', () => {
	const tracks: SharedTrack[] = [
		{ key: 's1', title: 'First', subtitle: null, audioUrl: '/audio/first.mp3' },
		{ key: 's2', title: 'Second (unpicked)', subtitle: null, audioUrl: null },
		{ key: 's3', title: 'Third', subtitle: null, audioUrl: '/audio/third.mp3' }
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
			songs: [{ id: 's1', title: 'First', track_number: 1, audio_url: '/audio/first.mp3' }]
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.songId).toBe('s1');
		expect(info.songTitle).toBe('First');
		expect(info.artist).toBe('Artist');
		expect(info.albumTitle).toBe('Neon Static');
		expect(info.generation.id).toBe('s1');
		expect(info.lyrics).toBeNull();
	});

	it('uses the entry artist for a playlist track', () => {
		const view = fromSharedPlaylist({
			title: 'Late Night Mix',
			entries: [
				{
					entry_id: 'e1',
					song_title: 'First',
					artist: 'Artist One',
					generation_number: 1,
					audio_url: '/audio/first.mp3'
				}
			]
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.artist).toBe('Artist One');
		expect(info.albumTitle).toBe('');
	});

	it('uses the collection album_title for a song or take track', () => {
		const view = fromSharedSong({
			title: 'Solo Track',
			artist: 'Artist',
			album_title: 'Album',
			audio_url: '/audio/solo.mp3'
		});
		const info = trackPlaybackInfo(view, view.tracks[0]);

		expect(info.artist).toBe('Artist');
		expect(info.albumTitle).toBe('Album');
	});
});

describe('collectionSubtitle', () => {
	it('shows artist and year for an album', () => {
		const view = fromSharedAlbum({
			title: 'Album',
			artist: 'Artist',
			subtitle: '',
			year: '2026',
			songs: []
		});
		expect(collectionSubtitle(view)).toBe('Artist · 2026');
	});

	it('shows the track count for a playlist', () => {
		const view = fromSharedPlaylist({
			title: 'Mix',
			entries: [
				{
					entry_id: 'e1',
					song_title: 'First',
					artist: 'Artist',
					generation_number: 1,
					audio_url: '/a.mp3'
				},
				{
					entry_id: 'e2',
					song_title: 'Second',
					artist: 'Artist',
					generation_number: 1,
					audio_url: '/b.mp3'
				}
			]
		});
		expect(collectionSubtitle(view)).toBe('2 tracks');
	});

	it('shows artist and album for a song', () => {
		const view = fromSharedSong({
			title: 'Solo',
			artist: 'Artist',
			album_title: 'Album',
			audio_url: '/a.mp3'
		});
		expect(collectionSubtitle(view)).toBe('Artist · Album');
	});

	it('shows artist, album, and take number for a take', () => {
		const view = fromSharedGeneration({
			title: 'Solo',
			artist: 'Artist',
			album_title: 'Album',
			generation_number: 3,
			seed: null,
			audio_url: '/a.mp3'
		});
		expect(collectionSubtitle(view)).toBe('Artist · Album · take 3');
	});
});
