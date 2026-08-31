// Seeds the library the desktop flow drives, through the same public API the
// app uses. Runs once per Playwright run from global-setup, so the flow spec
// only ever clicks — it never creates data of its own.

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { APIRequestContext } from '@playwright/test';
import { nowPlayingTakeLabel } from '../src/lib/constants/now-playing';

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const ARTIFACT_DIR = path.join(E2E_DIR, '.artifacts');
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const SEEDED_LIBRARY_FILE = path.join(ARTIFACT_DIR, 'seeded-library.json');

export const STORAGE_STATE_FILE = path.join(ARTIFACT_DIR, 'storage-state.json');
export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

const CSRF_COOKIE = 'csrf_token';
const CSRF_HEADER = 'x-csrf-token';

const ALBUM_ARTIST = 'E2E Ensemble';
// Fixed titles: only one album is ever open at a time, so they stay unique on
// screen even when a local re-run seeds a second album.
const SONG_TITLES = ['Opening Move', 'Second Wind', 'Closing Time'] as const;
// The album and the playlist are listed side by side with everything a
// previous local run left behind, so their titles carry a per-run marker.
const ALBUM_TITLE_PREFIX = 'E2E Album';
const PLAYLIST_TITLE_PREFIX = 'E2E Playlist';

function runMarker(): string {
	return Date.now().toString(36);
}

export interface SeededTake {
	songTitle: string;
	takeId: string;
}

/** Seeded once per run: nothing the flows do mutates it. */
export interface SeededLibrary {
	albumTitle: string;
	/** Also the album's address: an album id is its slug (issue #269). */
	albumId: string;
	albumShareUrl: string;
	/** Its take is the album pick — played from the album row, added to a playlist by hand. */
	pickedSongTitle: string;
	/** Takes a per-attempt playlist starts with, in playlist order. */
	playlistTakes: SeededTake[];
	/** Row label of a reimported take, which carries no version. */
	takeLabel: string;
}

/** Seeded per attempt, because the flow reorders and prunes it. */
export interface SeededPlaylist {
	title: string;
	/** Also the playlist's address: /playlist/<slug> (issue #286). */
	slug: string;
	songTitles: string[];
}

interface CreatedResource {
	id: string;
}

interface CreatedPlaylist extends CreatedResource {
	slug: string;
}

interface ShareLink {
	share_slug: string;
}

type MultipartFile = { name: string; mimeType: string; buffer: Buffer };

function requiredEnv(name: string): string {
	const value = process.env[name];
	if (!value) throw new Error(`${name} must be set to the CI stack's admin credentials`);
	return value;
}

class SeedApi {
	constructor(
		private readonly api: APIRequestContext,
		private readonly csrfToken: string
	) {}

	/** The one login of the run. Everything after it reuses the session. */
	static async login(api: APIRequestContext): Promise<SeedApi> {
		const response = await api.post('/api/auth/login', {
			data: { username: requiredEnv('ADMIN_USERNAME'), password: requiredEnv('ADMIN_PASSWORD') }
		});
		if (!response.ok()) {
			throw new Error(`Login failed: ${response.status()} ${await response.text()}`);
		}
		return SeedApi.fromSession(api, 'Login set no CSRF cookie');
	}

	/** Seeds from a context that already carries the run's session, without logging in again. */
	static async fromSession(api: APIRequestContext, missingCookieError?: string): Promise<SeedApi> {
		const { cookies } = await api.storageState();
		const csrf = cookies.find((cookie) => cookie.name === CSRF_COOKIE);
		if (!csrf) throw new Error(missingCookieError ?? 'Context carries no CSRF cookie');
		return new SeedApi(api, csrf.value);
	}

	async postJson<T>(url: string, data: unknown): Promise<T> {
		return this.send<T>(url, { data });
	}

	async postFile<T>(url: string, multipart: Record<string, MultipartFile>): Promise<T> {
		return this.send<T>(url, { multipart });
	}

	private async send<T>(
		url: string,
		body: { data?: unknown; multipart?: Record<string, MultipartFile> }
	): Promise<T> {
		const response = await this.api.post(url, {
			// The origin header is what the CSRF origin check reads on a form
			// submission; without it a multipart upload is rejected with 403.
			headers: { [CSRF_HEADER]: this.csrfToken, origin: BASE_URL },
			...body
		});
		if (!response.ok()) {
			throw new Error(`POST ${url} failed: ${response.status()} ${await response.text()}`);
		}
		return (await response.json()) as T;
	}
}

export async function seedLibrary(api: APIRequestContext): Promise<SeededLibrary> {
	const seed = await SeedApi.login(api);
	const albumTitle = `${ALBUM_TITLE_PREFIX} ${runMarker()}`;
	const takeAudio = readFileSync(TAKE_FIXTURE);

	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: albumTitle,
		artist: ALBUM_ARTIST
	});

	const takeBySongTitle = new Map<string, string>();
	for (const title of SONG_TITLES) {
		const song = await seed.postJson<CreatedResource>('/api/songs', {
			title,
			album_id: album.id,
			lyrics: `${title} — seeded lyrics`,
			prompt: 'calm test tone'
		});
		const take = await seed.postFile<CreatedResource>(`/api/songs/${song.id}/reimport`, {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: takeAudio }
		});
		takeBySongTitle.set(title, take.id);
	}

	const [pickedSongTitle, ...playlistSongTitles] = SONG_TITLES;
	await seed.postJson(`/api/generations/${takeId(takeBySongTitle, pickedSongTitle)}/pick`, {});

	const share = await seed.postJson<ShareLink>(`/api/albums/${album.id}/share`, {});

	return {
		albumTitle,
		albumId: album.id,
		albumShareUrl: `${BASE_URL}/share/${share.share_slug}`,
		pickedSongTitle,
		playlistTakes: playlistSongTitles.map((songTitle) => ({
			songTitle,
			takeId: takeId(takeBySongTitle, songTitle)
		})),
		takeLabel: nowPlayingTakeLabel(null, 1)
	};
}

function takeId(takes: Map<string, string>, songTitle: string): string {
	const id = takes.get(songTitle);
	if (!id) throw new Error(`No take seeded for "${songTitle}"`);
	return id;
}

/**
 * A fresh playlist for one test attempt. The flow adds, reorders and removes
 * entries, so a retry must not inherit the previous attempt's order.
 */
export async function seedPlaylist(
	api: APIRequestContext,
	library: SeededLibrary
): Promise<SeededPlaylist> {
	const seed = await SeedApi.fromSession(api);
	const title = `${PLAYLIST_TITLE_PREFIX} ${runMarker()}`;
	const playlist = await seed.postJson<CreatedPlaylist>('/api/playlists', { title });
	for (const take of library.playlistTakes) {
		await seed.postJson(`/api/playlists/${playlist.id}/entries/generation`, {
			generation_id: take.takeId
		});
	}
	return {
		title,
		slug: playlist.slug,
		songTitles: library.playlistTakes.map((take) => take.songTitle)
	};
}

export function writeSeededLibrary(library: SeededLibrary): void {
	mkdirSync(ARTIFACT_DIR, { recursive: true });
	writeFileSync(SEEDED_LIBRARY_FILE, JSON.stringify(library, null, 2));
}

export function readSeededLibrary(): SeededLibrary {
	return JSON.parse(readFileSync(SEEDED_LIBRARY_FILE, 'utf-8')) as SeededLibrary;
}
