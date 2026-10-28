import { execFile } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { expect, type Page, type Route } from '@playwright/test';
import type { AlbumCoverUrls, SharedPlaylistPayload } from '../src/lib/api/types';
import { sameOriginHeaders } from './helpers';
import { requiredAdminUsername } from './required-env';
import { BASE_URL, TAKE_FIXTURE, archiveOwnedAlbum, runMarker } from './seed';

export const PLAYLIST_TITLE = 'E2E Shared Journey';
export const PLAYLIST_SLUG = 'proof-playlist';
export const PLAYLIST_API = `/shared/playlist/${PLAYLIST_SLUG}`;
export const PLAYLIST_URL = `${BASE_URL}/share/playlist/${PLAYLIST_SLUG}`;
export const songTitle = (position: number) => `Journey ${position}`;
export const albumTitle = (position: number) => `E2E Member Album ${position}`;
export const songLyrics = (position: number) => `Words from journey ${position}`;
export const coverOf = (position: number): AlbumCoverUrls => ({
	card: `${PLAYLIST_API}/album-covers/${position}?variant=card`,
	detail: `${PLAYLIST_API}/album-covers/${position}?variant=detail`
});

export function repeatedAudio(copies = 40): Buffer {
	const take = readFileSync(TAKE_FIXTURE);
	const firstFrame = take.indexOf(Buffer.from([0xff, 0xf3, 0x40]));
	if (firstFrame < 0) throw new Error('The audio fixture has no MPEG frame');
	return Buffer.concat(Array(copies).fill(take.subarray(firstFrame)));
}

export function playlistPayload(count = 3): SharedPlaylistPayload {
	return {
		title: PLAYLIST_TITLE,
		cover: null,
		album_covers: Array.from({ length: Math.min(count, 4) }, (_, i) => coverOf(i + 1)),
		entries: Array.from({ length: count }, (_, i) => ({
			entry_id: `entry-${i + 1}`,
			song_title: songTitle(i + 1),
			album_title: albumTitle(i + 1),
			artist: 'E2E Ensemble',
			generation_number: 1,
			generation_id: `take-${i + 1}`,
			audio_url: `${PLAYLIST_API}/audio/${i + 1}.mp3`,
			audio_duration: 120,
			lyrics: songLyrics(i + 1),
			whisper_cues: null,
			album_cover: coverOf(i + 1)
		}))
	};
}

async function rangeableAudio(route: Route, audio: Buffer): Promise<void> {
	const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()['range'] ?? '');
	const start = range ? Number(range[1]) : 0;
	const end = Math.min(range?.[2] ? Number(range[2]) : audio.length - 1, audio.length - 1);
	await route.fulfill({
		status: range ? 206 : 200,
		contentType: 'audio/mpeg',
		headers: {
			'accept-ranges': 'bytes',
			...(range && { 'content-range': `bytes ${start}-${end}/${audio.length}` })
		},
		body: audio.subarray(start, end + 1)
	});
}

export async function refusePlaylistStream(page: Page, api = PLAYLIST_API): Promise<void> {
	await page.route(`**${api}/stream`, (route) =>
		route.fulfill({ status: 404, json: { detail: 'Stream unavailable' } })
	);
}

export async function mockPlaylist(page: Page, payload = playlistPayload()): Promise<void> {
	await page.route(`**${PLAYLIST_API}`, (route) => route.fulfill({ json: payload }));
	await refusePlaylistStream(page);
	const audio = repeatedAudio();
	await page.route(`**${PLAYLIST_API}/audio/*`, (route) => rangeableAudio(route, audio));
	await page.route(`**${PLAYLIST_API}/album-covers/*`, (route) => {
		const number = Number(new URL(route.request().url()).pathname.split('/').at(-1));
		return route.fulfill({
			contentType: 'image/svg+xml',
			body: `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="${number % 2 ? '#395b89' : '#97533c'}"/><text x="90" y="175" font-size="70" fill="white">${number}</text></svg>`
		});
	});
}

const MEMBER_COVERS = [
	Buffer.from(
		'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGOwjO4kCTGMahjVMHw1AAA0nB0QowDOUwAAAABJRU5ErkJggg==',
		'base64'
	),
	Buffer.from(
		'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGOYHmxDEmIY1TCqYfhqAACobiYQkd9DagAAAABJRU5ErkJggg==',
		'base64'
	),
	Buffer.from(
		'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGNwrYsgCTGMahjVMHw1AABhbxsQiHyWYAAAAABJRU5ErkJggg==',
		'base64'
	)
];

interface Resource {
	id: string;
}
interface Share {
	share_slug: string;
}

export interface RealPlaylist {
	url: string;
	api: string;
	payload: SharedPlaylistPayload;
	setUpload(present: boolean): Promise<void>;
	revoke(): Promise<void>;
	cleanup(): Promise<void>;
}

async function seedMemberSong(albumId: string, position: number): Promise<string> {
	const owner = requiredAdminUsername();
	return new Promise((resolve, reject) => {
		const child = execFile(
			'docker',
			[
				'compose',
				'-f',
				'docker-compose.yml',
				'-f',
				'docker/docker-compose.ci.yml',
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'scripts/seed_e2e_song_takes.py',
				'--album-id',
				albumId,
				'--title',
				songTitle(position),
				'--take-count',
				'1',
				'--owner-username',
				owner,
				'--lyrics',
				songLyrics(position),
				'--prompt',
				'E2E tone'
			],
			{ cwd: '..' },
			(error, stdout, stderr) => {
				if (error) reject(new Error(`Playlist song seed failed: ${stderr}`, { cause: error }));
				else resolve(stdout.trim());
			}
		);
		child.stdin?.end(repeatedAudio(10));
	});
}

export async function createRealPlaylist(owner: Page): Promise<RealPlaylist> {
	const headers = await sameOriginHeaders(owner);
	const albums: string[] = [];
	const post = async <T>(url: string, data: unknown): Promise<T> => {
		const response = await owner.request.post(url, { headers, data });
		expect(response.ok(), `POST ${url}: ${await response.text()}`).toBeTruthy();
		return response.json() as Promise<T>;
	};
	const playlist = await post<Resource>('/api/playlists', {
		title: `${PLAYLIST_TITLE} ${runMarker()}`
	});
	const cleanup = async () => {
		const removed = await owner.request.delete(`/api/playlists/${playlist.id}`, { headers });
		expect(removed.ok()).toBeTruthy();
		// 1354_65_D5: shared-playlist proofs archive each member through the seed owner.
		for (const id of albums) await archiveOwnedAlbum(owner.request, id);
	};
	try {
		for (const position of [1, 2, 3]) {
			const album = await post<Resource>('/api/albums', {
				title: albumTitle(position),
				artist: 'E2E Ensemble'
			});
			albums.push(album.id);
			const cover = await owner.request.post(`/api/albums/${album.id}/cover`, {
				headers,
				multipart: {
					file: {
						name: 'cover.png',
						mimeType: 'image/png',
						buffer: MEMBER_COVERS[position - 1]
					}
				}
			});
			expect(cover.ok()).toBeTruthy();
			const songId = await seedMemberSong(album.id, position);
			const songResponse = await owner.request.get(`/api/songs/${songId}`);
			expect(songResponse.ok()).toBeTruthy();
			const song = (await songResponse.json()) as { generations: Resource[] };
			const take = song.generations[0];
			if (!take) throw new Error('The member song has no seeded take');
			await post(`/api/playlists/${playlist.id}/entries/generation`, { generation_id: take.id });
		}
		const share = await post<Share>(`/api/playlists/${playlist.id}/share`, {});
		const api = `/shared/playlist/${share.share_slug}`;
		const response = await owner.request.get(api, {
			headers: { 'x-forwarded-for': '192.0.2.254' }
		});
		expect(response.ok()).toBeTruthy();
		return {
			url: `${BASE_URL}/share/playlist/${share.share_slug}`,
			api,
			payload: (await response.json()) as SharedPlaylistPayload,
			async setUpload(present) {
				const url = `/api/playlists/${playlist.id}/cover`;
				const response = present
					? await owner.request.put(url, {
							headers,
							multipart: {
								file: {
									name: 'upload.png',
									mimeType: 'image/png',
									buffer: readFileSync('static/icon-192.png')
								}
							}
						})
					: await owner.request.delete(url, { headers });
				expect(response.ok()).toBeTruthy();
			},
			async revoke() {
				const response = await owner.request.delete(`/api/playlists/${playlist.id}/share`, {
					headers
				});
				expect(response.ok()).toBeTruthy();
			},
			cleanup
		};
	} catch (error) {
		await cleanup();
		throw error;
	}
}
