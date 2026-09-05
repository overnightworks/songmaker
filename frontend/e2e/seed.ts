// Seeds the library the desktop flow drives, through the same public API the
// app uses. Runs once per Playwright run from global-setup, so the flow spec
// only ever clicks — it never creates data of its own.

import { execFile } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { expect, type APIRequestContext } from '@playwright/test';
import { nowPlayingTakeLabel } from '../src/lib/constants/now-playing';

const execFileAsync = promisify(execFile);

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const ARTIFACT_DIR = path.join(E2E_DIR, '.artifacts');
const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const SEEDED_LIBRARY_FILE = path.join(ARTIFACT_DIR, 'seeded-library.json');
// The compose recipe this suite always runs under (README, e2e.yml) -- run
// from the repo root so a caller's own COMPOSE_PROJECT_NAME (or its default,
// inferred from the cwd docker compose up already ran in) resolves to the
// same running stack.
const REPO_ROOT = path.join(E2E_DIR, '..', '..');
const COMPOSE_ARGS = ['compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.ci.yml'];

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
const KINETIC_STRIP_ALBUM_TITLE_PREFIX = 'E2E Kinetic Strip Album';
// A second, sibling album: the rail's one-open-album rule (#323) and its
// real CSS visibility (#326) only show up with two albums that can each be
// opened in turn. No take is imported for it -- the rail only needs the
// song rows to exist, not a playable generation.
const RAIL_ALBUM_TITLE_PREFIX = 'E2E Rail Album';
const RAIL_ALBUM_SONG_TITLES = ['Rail Echo', 'Rail Drift'] as const;
// Enough closed rows to make the rail's own LIBRARY+PLAYLISTS scroll region
// taller than the viewport, so the Settings/user-row pin promise (ruled in
// #302) can be measured by scrolling the rail and checking where Settings
// actually renders -- not merely asserted from the CSS class structure.
// Deliberately songless and seeded directly against the database (see
// seedFillerAlbums below), not through 30 individual POSTs: issue #344's CI
// root-cause analysis found those 30 requests -- proving no API semantics of
// their own -- were most of what pushed a run over the server's IP rate
// limit, which counts every request it receives regardless of which
// Playwright context sent it.
const RAIL_FILLER_ALBUM_TITLE_PREFIX = 'E2E Rail Filler';
const RAIL_FILLER_ALBUM_COUNT = 30;
const E2E_ALBUM_TITLE_PREFIX = 'E2E ';

function runMarker(): string {
	return Date.now().toString(36);
}

export interface SeededTake {
	songTitle: string;
	takeId: string;
}

/** A private, playable take for the Voices flow to select through its real catalogue. */
export interface SeededVoiceTake {
	songTitle: string;
	songId: string;
	caption: string;
	lyrics: string;
}

export interface QueuedJob {
	id: string;
	status: string;
}

interface VoiceLifecycle {
	status: string;
}

/** Seeded once per run: nothing the flows do mutates it. */
export interface SeededLibrary {
	albumTitle: string;
	/** Number of songs in the primary album, for its rendered summary. */
	albumSongCount: number;
	/** Also the album's address: an album id is its slug (issue #269). */
	albumId: string;
	albumShareUrl: string;
	/** Its take is the album pick — played from the album row, added to a playlist by hand. */
	pickedSongTitle: string;
	/** The picked song's API id, used by the Continue reorder proof. */
	pickedSongId: string;
	/** A second playable song, so each viewport proves a fresh reorder. */
	continueReorderSongTitle: string;
	continueReorderSongId: string;
	/** Takes a per-attempt playlist starts with, in playlist order. */
	playlistTakes: SeededTake[];
	/** Row label of a reimported take, which carries no version. */
	takeLabel: string;
	/** A sibling album, open in the rail beside `albumTitle` -- the rail's one-open-album rule. */
	secondAlbumTitle: string;
	/** One of the second album's own songs, for the visibility assertion. */
	secondAlbumSongTitle: string;
	/** Dedicated album the kinetic-strip flow can mutate without changing the base library. */
	kineticStripAlbumId: string;
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

/**
 * Like `execFileAsync`, but pipes `input` to the child's stdin before
 * waiting on it. `child_process.execFile`'s callback form returns the
 * `ChildProcess` synchronously, which is what makes writing to `.stdin`
 * possible at all — the promisified form (`execFileAsync`) discards that
 * return value along with any chance to reach stdin.
 */
function execWithStdin(
	command: string,
	args: string[],
	options: { cwd: string },
	input: Buffer
): Promise<{ stdout: string; stderr: string }> {
	return new Promise((resolve, reject) => {
		const child = execFile(command, args, options, (error, stdout, stderr) => {
			if (error) {
				reject(new Error(`${error.message}\n${stderr}`));
				return;
			}
			resolve({ stdout, stderr });
		});
		child.stdin?.end(input);
	});
}

/**
 * Seeds `RAIL_FILLER_ALBUM_COUNT` songless albums titled
 * `${titlePrefix}-0`, `${titlePrefix}-1`, ... directly against the database,
 * inside the web container, in one process -- not through
 * `RAIL_FILLER_ALBUM_COUNT` individual `POST /api/albums` calls. Those never
 * exercised API semantics of their own (see `scripts/seed_e2e_filler_albums.py`
 * for the full reasoning, issue #344) and their only cost to the server's IP
 * rate limiter was existing. Uses the same `docker compose` recipe the CI
 * workflow and this suite's own README already run under.
 */
async function seedFillerAlbums(titlePrefix: string): Promise<void> {
	try {
		await execFileAsync(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'scripts/seed_e2e_filler_albums.py',
				'--count',
				String(RAIL_FILLER_ALBUM_COUNT),
				'--title-prefix',
				titlePrefix,
				'--owner-username',
				requiredEnv('ADMIN_USERNAME')
			],
			{ cwd: REPO_ROOT }
		);
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Seeding filler albums failed: ${detail}`, { cause: err });
	}
}

/**
 * Keep reruns equivalent to the clean stack the request budgets describe.
 * Evidence from an earlier run remains recoverable under Archived, while its
 * rows and covers no longer inflate the live rail before this run is seeded.
 */
async function archivePreviousE2EAlbums(): Promise<void> {
	try {
		await execFileAsync(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'scripts/archive_e2e_albums.py',
				'--title-prefix',
				E2E_ALBUM_TITLE_PREFIX,
				'--owner-username',
				requiredEnv('ADMIN_USERNAME')
			],
			{ cwd: REPO_ROOT }
		);
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Archiving previous E2E albums failed: ${detail}`, { cause: err });
	}
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

	async delete(url: string): Promise<void> {
		const response = await this.api.delete(url, {
			headers: { [CSRF_HEADER]: this.csrfToken, origin: BASE_URL }
		});
		if (!response.ok()) {
			throw new Error(`DELETE ${url} failed: ${response.status()} ${await response.text()}`);
		}
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
	await archivePreviousE2EAlbums();
	const seed = await SeedApi.login(api);
	const albumTitle = `${ALBUM_TITLE_PREFIX} ${runMarker()}`;
	const takeAudio = readFileSync(TAKE_FIXTURE);

	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: albumTitle,
		artist: ALBUM_ARTIST
	});

	const songIdByTitle = new Map<string, string>();
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
		songIdByTitle.set(title, song.id);
		takeBySongTitle.set(title, take.id);
	}

	const [pickedSongTitle, ...playlistSongTitles] = SONG_TITLES;
	const pickedSongId = songIdByTitle.get(pickedSongTitle);
	if (!pickedSongId) throw new Error(`Missing seeded song ${pickedSongTitle}`);
	const continueReorderSongTitle = playlistSongTitles[playlistSongTitles.length - 1];
	const continueReorderSongId = songIdByTitle.get(continueReorderSongTitle);
	if (!continueReorderSongId) throw new Error(`Missing seeded song ${continueReorderSongTitle}`);
	await seed.postJson(`/api/generations/${takeId(takeBySongTitle, pickedSongTitle)}/pick`, {});

	const share = await seed.postJson<ShareLink>(`/api/albums/${album.id}/share`, {});

	const secondAlbumTitle = `${RAIL_ALBUM_TITLE_PREFIX} ${runMarker()}`;
	const secondAlbum = await seed.postJson<CreatedResource>('/api/albums', {
		title: secondAlbumTitle,
		artist: ALBUM_ARTIST
	});
	for (const title of RAIL_ALBUM_SONG_TITLES) {
		await seed.postJson<CreatedResource>('/api/songs', {
			title,
			album_id: secondAlbum.id,
			lyrics: `${title} — seeded lyrics`,
			prompt: 'calm test tone'
		});
	}

	const kineticStripAlbum = await seed.postJson<CreatedResource>('/api/albums', {
		title: `${KINETIC_STRIP_ALBUM_TITLE_PREFIX} ${runMarker()}`,
		artist: ALBUM_ARTIST
	});

	await seedFillerAlbums(`${RAIL_FILLER_ALBUM_TITLE_PREFIX} ${runMarker()}`);

	return {
		albumTitle,
		albumSongCount: SONG_TITLES.length,
		albumId: album.id,
		albumShareUrl: `${BASE_URL}/share/${share.share_slug}`,
		pickedSongTitle,
		pickedSongId,
		continueReorderSongTitle,
		continueReorderSongId,
		secondAlbumTitle,
		secondAlbumSongTitle: RAIL_ALBUM_SONG_TITLES[0],
		kineticStripAlbumId: kineticStripAlbum.id,
		playlistTakes: playlistSongTitles.map((songTitle) => ({
			songTitle,
			takeId: takeId(takeBySongTitle, songTitle)
		})),
		takeLabel: nowPlayingTakeLabel(null, 1)
	};
}

/**
 * Creates one album and a versioned take. The Voices browser flow then
 * discovers it through `/api/loras/own-takes`, just as a musician does,
 * rather than injecting a LoRA sample into the database.
 */
export async function seedVoiceTake(api: APIRequestContext): Promise<SeededVoiceTake> {
	const seed = await SeedApi.fromSession(api);
	const marker = runMarker();
	const songTitle = `E2E Voice Source ${marker}`;
	const caption = 'warm e2e tenor';
	const lyrics = 'E2E source lyrics';
	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: `E2E Voice Album ${marker}`,
		artist: ALBUM_ARTIST
	});
	try {
		const { stdout } = await execWithStdin(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'scripts/seed_e2e_song_takes.py',
				'--album-id',
				album.id,
				'--title',
				songTitle,
				'--take-count',
				'1',
				'--owner-username',
				requiredEnv('ADMIN_USERNAME'),
				'--lyrics',
				lyrics,
				'--prompt',
				caption
			],
			{ cwd: REPO_ROOT },
			readFileSync(TAKE_FIXTURE)
		);
		const songId = stdout.trim();
		if (!songId)
			throw new Error('seed_e2e_song_takes.py printed no song id for the Voices source take');
		return { songTitle, songId, caption, lyrics };
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Seeding the voices source take failed: ${detail}`, { cause: err });
	}
}

/** Creates draft voices through the public API so the UI can prove the configured limit. */
export async function seedVoiceDrafts(api: APIRequestContext, count: number): Promise<string[]> {
	const seed = await SeedApi.fromSession(api);
	const voiceIds: string[] = [];
	for (let index = 0; index < count; index += 1) {
		const voice = await seed.postJson<CreatedResource>('/api/loras', {
			name: `E2E Voice Limit Filler ${runMarker()}-${index}`
		});
		voiceIds.push(voice.id);
	}
	return voiceIds;
}

/** Removes browser-proof voices so desktop and mobile exercise the same configured limit. */
export async function deleteVoiceProofData(
	api: APIRequestContext,
	voiceIds: readonly string[]
): Promise<void> {
	const seed = await SeedApi.fromSession(api);
	for (const voiceId of voiceIds) {
		await expect
			.poll(
				async () => {
					const response = await api.get(`/api/loras/${voiceId}`);
					if (!response.ok()) {
						throw new Error(`GET /api/loras/${voiceId} failed: ${response.status()}`);
					}
					const voice = (await response.json()) as VoiceLifecycle;
					return !['queued', 'preprocessing', 'training', 'exporting'].includes(voice.status);
				},
				{ timeout: 40_000 }
			)
			.toBe(true);
		await seed.delete(`/api/loras/${voiceId}`);
	}
}

/** A real Generate job occupies the fake worker while the Voices flow waits. */
export async function queueGenerateForVoiceProof(
	api: APIRequestContext,
	songId: string
): Promise<QueuedJob> {
	const seed = await SeedApi.fromSession(api);
	return seed.postJson<QueuedJob>(`/api/songs/${songId}/generate`, {
		count: 1,
		model: 'sft'
	});
}

function takeId(takes: Map<string, string>, songTitle: string): string {
	const id = takes.get(songTitle);
	if (!id) throw new Error(`No take seeded for "${songTitle}"`);
	return id;
}

/**
 * A song of its own, seeded with `takeCount` takes directly against the
 * database (`scripts/seed_e2e_song_takes.py`) rather than through
 * `takeCount` individual `POST /api/songs/{id}/reimport` calls — the exact
 * mistake issue #344 already found and fixed for the rail's filler albums
 * (see `seedFillerAlbums` above): the server's IP rate limiter counts every
 * request it receives regardless of which Playwright context sent it, and
 * those calls exercise no API semantics worth spending that budget on. Its
 * own song rather than piling extra generations onto one of the base
 * seed's `SONG_TITLES`: those are shared across every flow in the run, and
 * more than one of them (`library.spec.ts`'s own `takeLabel`, `takeId`
 * above) depends on the base seed's one-take-per-song count staying exactly
 * one. Used by a flow that needs a strip of many takes to genuinely
 * overflow its container (`kinetic-strip.spec.ts`, issue #358).
 */
export async function seedTakeStripSong(
	albumId: string,
	title: string,
	takeCount: number
): Promise<string> {
	try {
		const { stdout } = await execWithStdin(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'scripts/seed_e2e_song_takes.py',
				'--album-id',
				albumId,
				'--title',
				title,
				'--take-count',
				String(takeCount),
				'--owner-username',
				requiredEnv('ADMIN_USERNAME')
			],
			{ cwd: REPO_ROOT },
			readFileSync(TAKE_FIXTURE)
		);
		const songId = stdout.trim();
		if (!songId) throw new Error('seed_e2e_song_takes.py printed no song id on stdout');
		return songId;
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Seeding the kinetic-strip song's takes failed: ${detail}`, { cause: err });
	}
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
