// A mocked shared album for the share-album-player flows: the real seeded
// album is three songs of three seconds, too short to hold a state still and
// too few to scroll. The mock serves a long, rangeable audio for every song
// and refuses the stream manifest, so each song plays from its own address.

import { readFileSync } from 'node:fs';
import { expect, type Locator, type Page } from '@playwright/test';
import { BASE_URL, TAKE_FIXTURE } from './seed';

const AUDIO_FRAME_SYNC = Buffer.from([0xff, 0xf3, 0x40]);
const COPIES_OF_THE_TAKE = 40;
const MOCK_SONG_SECONDS = 120;
const AUDIO_TYPE = 'audio/mpeg';

export const MOCK_SLUG = 'mock-album';
export const MOCK_ALBUM_TITLE = 'Mocked Long Album';
export const MOCK_ARTIST = 'Mock Artist';
export const MOCK_UNPLAYABLE_TITLE = 'Hidden Draft';
export const MOCK_STREAM_REFUSAL = { path: `/shared/${MOCK_SLUG}/stream`, statuses: [404] };
export const MOCK_URL = `${BASE_URL}/share/${MOCK_SLUG}`;

export interface MockSong {
	title: string;
	lyrics: string | null;
	playable: boolean;
}

export function mockSongTitle(position: number): string {
	return `Mock Song ${position}`;
}

export function mockSongLyrics(position: number): string {
	return `Words of mock song ${position}`;
}

export function mockSongs(count: number): MockSong[] {
	return Array.from({ length: count }, (_, index) => ({
		title: mockSongTitle(index + 1),
		lyrics: mockSongLyrics(index + 1),
		playable: true
	}));
}

// The take's leading Info frame states three seconds; dropping everything
// before its first audio frame lets the repeated frames play for as long as
// they run.
function longAudio(): Buffer {
	const take = readFileSync(TAKE_FIXTURE);
	const firstAudioFrame = take.indexOf(AUDIO_FRAME_SYNC);
	return Buffer.concat(Array(COPIES_OF_THE_TAKE).fill(take.subarray(firstAudioFrame)));
}

function albumPayload(songs: MockSong[], artist: string) {
	return {
		title: MOCK_ALBUM_TITLE,
		artist,
		subtitle: '',
		year: '',
		cover: null,
		songs: songs.map((song, index) => ({
			id: `mock-song-${index + 1}`,
			title: song.title,
			track_number: index + 1,
			audio_url: song.playable ? `/shared/${MOCK_SLUG}/audio/${index + 1}` : null,
			generation_id: `mock-gen-${index + 1}`,
			audio_duration: song.playable ? MOCK_SONG_SECONDS : null,
			lyrics: song.lyrics,
			whisper_cues: null
		}))
	};
}

export async function mockSharedAlbum(
	page: Page,
	songs: MockSong[],
	artist = MOCK_ARTIST
): Promise<void> {
	const audio = longAudio();
	await page.route(`**/shared/${MOCK_SLUG}`, (route) =>
		route.fulfill({ json: albumPayload(songs, artist) })
	);
	await page.route(`**/shared/${MOCK_SLUG}/stream`, (route) =>
		route.fulfill({ status: 404, json: { detail: 'Stream unavailable' } })
	);
	await page.route(`**/shared/${MOCK_SLUG}/audio/*`, (route) => {
		const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()['range'] ?? '');
		const start = range ? Number(range[1]) : 0;
		const end = range?.[2] ? Number(range[2]) : audio.length - 1;
		return route.fulfill({
			status: range ? 206 : 200,
			contentType: AUDIO_TYPE,
			headers: {
				'accept-ranges': 'bytes',
				...(range && { 'content-range': `bytes ${start}-${end}/${audio.length}` })
			},
			body: audio.subarray(start, end + 1)
		});
	});
}

export function control(page: Page, name: string): Locator {
	return page.locator('.now-playing.page').getByRole('button', { name, exact: true });
}

export async function openMockSharedAlbum(
	page: Page,
	songs = mockSongs(3),
	artist = MOCK_ARTIST
): Promise<void> {
	await mockSharedAlbum(page, songs, artist);
	await page.goto(MOCK_URL);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(MOCK_ALBUM_TITLE);
}
