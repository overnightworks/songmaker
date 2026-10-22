// Seeds the library the desktop flow drives, through the same public API the
// app uses. Runs once per Playwright run from global-setup, so the flow spec
// only ever clicks — it never creates data of its own.

import { execFile } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { expect, request, type APIRequestContext, type Cookie } from '@playwright/test';
import type { JobItem } from '../src/lib/api/types';
import { nowPlayingTakeLabel } from '../src/lib/constants/now-playing';

const execFileAsync = promisify(execFile);

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const ARTIFACT_DIR = path.join(E2E_DIR, '.artifacts');
export const TAKE_FIXTURE = path.join(E2E_DIR, 'fixtures', 'take.mp3');
const SEEDED_LIBRARY_FILE = path.join(ARTIFACT_DIR, 'seeded-library.json');
// The compose recipe this suite always runs under (README, e2e.yml) -- run
// from the repo root so a caller's own COMPOSE_PROJECT_NAME (or its default,
// inferred from the cwd docker compose up already ran in) resolves to the
// same running stack.
const REPO_ROOT = path.join(E2E_DIR, '..', '..');
const COMPOSE_ARGS = ['compose', '-f', 'docker-compose.yml', '-f', 'docker/docker-compose.ci.yml'];

export const STORAGE_STATE_FILE = path.join(ARTIFACT_DIR, 'storage-state.json');
export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

const CSRF_COOKIE = 'csrf_token';
// The app's own take address (`audioUrlOf` in `services/audioPlayer.svelte.ts`).
const AUDIO_PATH_PREFIX = '/audio/';
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
// Dedicated album for song-phone.spec.ts (issue #995), same reasoning as the
// kinetic-strip album above: its song is seeded well past v1 and mutated by
// the flow's own job-state seeding, so it stays off the shared base library.
const SONG_PHONE_ALBUM_TITLE_PREFIX = 'E2E Song Phone Album';
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
// The role every account but the e2e admin holds.
const NON_ADMIN_ROLE: AccountRole = 'user';

export type AccountRole = 'admin' | 'user';

// The compose defaults for the throwaway CI database (`docker-compose.yml`),
// which neither the workflow nor the README's local recipe overrides.
function postgresUser(): string {
	return process.env.POSTGRES_USER ?? 'songmaker';
}

function postgresDatabase(): string {
	return process.env.POSTGRES_DB ?? 'songmaker';
}
export const VOICES_OCCUPANCY_PROMPT = 'E2E voices occupancy prompt';
const VOICE_ADAPTER_COMPARISON_PROMPT = 'E2E adapter comparison prompt';
const VOICE_ADAPTER_COMPARISON_LYRICS = 'E2E adapter comparison lyrics';

/**
 * A per-invocation uniqueness suffix. Called fresh inside a test body (never
 * cached), so a CI retry -- which re-runs the whole test function later in
 * wall-clock time -- gets a new marker rather than colliding with the
 * previous attempt's own seeded rows.
 */
export function runMarker(): string {
	return Date.now().toString(36);
}

export interface SeededTake {
	songTitle: string;
	takeId: string;
}

export interface SeededSong {
	id: string;
	title: string;
}

/** A song and the address its one take plays from. */
export interface SeededTrack {
	songTitle: string;
	audioPath: string;
}

/** The whole library of a fresh account: one album, a take per song, nothing picked or kept. */
export interface SeededUnpickedLibrary {
	albumId: string;
	/** In album order. */
	tracks: SeededTrack[];
}

/** A private, playable take for the Voices flow to select through its real catalogue. */
export interface SeededVoiceTake {
	songTitle: string;
	songId: string;
	versionId: string;
	caption: string;
	lyrics: string;
}

export interface SeededVoiceProofSong {
	albumId: string;
	songId: string;
	songSlug: string;
	versionId: string;
}

export interface QueuedJob {
	id: string;
	status: string;
}

interface VoiceLifecycle {
	status: string;
	deleted_at: string | null;
}

interface ImportedTake extends CreatedResource {
	mp3_path: string;
}

interface SeededAlbumSong {
	songId: string;
	takeId: string;
	track: SeededTrack;
}

interface CreatedSong extends CreatedResource {
	slug: string;
}

type VersionResource = CreatedResource;

/** Seeded once per run: nothing the flows do mutates it. */
export interface SeededLibrary {
	albumTitle: string;
	/** Number of songs in the primary album, for its rendered summary. */
	albumSongCount: number;
	/** The primary album's songs in album order; only the first one's take is picked. */
	albumTracks: SeededTrack[];
	/** Also the album's address: an album id is its slug (issue #269). */
	albumId: string;
	albumShareUrl: string;
	/** A shared playlist that opens directly as the page player. */
	playlistShareUrl: string;
	/** Its take is the album pick — played from the album row, added to a playlist by hand. */
	pickedSongTitle: string;
	/**
	 * One non-leading song per shell, so the serial desktop and mobile flows
	 * each prove their own reorder without relying on another spec to move the
	 * shared library's leader in between.
	 */
	listenReorderSongs: Record<'desktop' | 'mobile', SeededSong>;
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
	/** Dedicated album song-phone.spec.ts and take-arrives.spec.ts seed their own songs and job states into. */
	songPhoneAlbumId: string;
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

export function requiredEnv(name: string): string {
	const value = process.env[name];
	if (!value) throw new Error(`${name} must be set to the e2e admin's username`);
	return value;
}

function seededSong(songIdByTitle: Map<string, string>, title: string): SeededSong {
	const id = songIdByTitle.get(title);
	if (!id) throw new Error(`Missing seeded song ${title}`);
	return { id, title };
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
				requiredEnv('E2E_ADMIN_USERNAME')
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
				requiredEnv('E2E_ADMIN_USERNAME')
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

	/** Seeds from a context that already carries a seeded session (`seedAccount`). */
	static async fromSession(api: APIRequestContext): Promise<SeedApi> {
		const { cookies } = await api.storageState();
		const csrf = cookies.find((cookie) => cookie.name === CSRF_COOKIE);
		if (!csrf) throw new Error('Context carries no CSRF cookie');
		return new SeedApi(api, csrf.value);
	}

	async postJson<T>(url: string, data: unknown): Promise<T> {
		return this.send<T>(url, { data });
	}

	async postFile<T>(url: string, multipart: Record<string, MultipartFile>): Promise<T> {
		return this.send<T>(url, { multipart });
	}

	async getJson<T>(url: string): Promise<T> {
		const response = await this.api.get(url);
		if (!response.ok()) {
			throw new Error(`GET ${url} failed: ${response.status()} ${await response.text()}`);
		}
		return (await response.json()) as T;
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

/** Seeds `SONG_TITLES` into the album in that order, each with one imported take. */
async function seedSongsWithOneTakeEach(
	seed: SeedApi,
	albumId: string
): Promise<SeededAlbumSong[]> {
	const takeAudio = readFileSync(TAKE_FIXTURE);
	const songs: SeededAlbumSong[] = [];
	for (const title of SONG_TITLES) {
		const song = await seed.postJson<CreatedResource>('/api/songs', {
			title,
			album_id: albumId,
			lyrics: `${title} — seeded lyrics`,
			prompt: 'calm test tone'
		});
		const take = await seed.postFile<ImportedTake>(`/api/songs/${song.id}/reimport`, {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: takeAudio }
		});
		songs.push({
			songId: song.id,
			takeId: take.id,
			track: { songTitle: title, audioPath: AUDIO_PATH_PREFIX + take.mp3_path }
		});
	}
	return songs;
}

export async function seedLibrary(api: APIRequestContext): Promise<SeededLibrary> {
	await archivePreviousE2EAlbums();
	const seed = await SeedApi.fromSession(api);
	const albumTitle = `${ALBUM_TITLE_PREFIX} ${runMarker()}`;

	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: albumTitle,
		artist: ALBUM_ARTIST
	});

	const albumSongs = await seedSongsWithOneTakeEach(seed, album.id);
	const songIdByTitle = new Map(albumSongs.map((song) => [song.track.songTitle, song.songId]));
	const takeBySongTitle = new Map(albumSongs.map((song) => [song.track.songTitle, song.takeId]));

	const [pickedSongTitle, mobileListenSongTitle, desktopListenSongTitle] = SONG_TITLES;
	// Each project records listens with its own song. The persisted fixture key
	// also serves the Library ordering flow.
	const playlistSongTitles = [desktopListenSongTitle, mobileListenSongTitle];
	const listenReorderSongs = {
		desktop: seededSong(songIdByTitle, desktopListenSongTitle),
		mobile: seededSong(songIdByTitle, mobileListenSongTitle)
	};
	await seed.postJson(`/api/generations/${takeId(takeBySongTitle, pickedSongTitle)}/pick`, {});

	const share = await seed.postJson<ShareLink>(`/api/albums/${album.id}/share`, {});

	const sharedPlaylist = await seed.postJson<CreatedPlaylist>('/api/playlists', {
		title: `${PLAYLIST_TITLE_PREFIX} shared ${runMarker()}`
	});
	for (const songTitle of playlistSongTitles) {
		await seed.postJson(`/api/playlists/${sharedPlaylist.id}/entries/generation`, {
			generation_id: takeId(takeBySongTitle, songTitle)
		});
	}
	const playlistShare = await seed.postJson<ShareLink>(
		`/api/playlists/${sharedPlaylist.id}/share`,
		{}
	);

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
	const songPhoneAlbum = await seed.postJson<CreatedResource>('/api/albums', {
		title: `${SONG_PHONE_ALBUM_TITLE_PREFIX} ${runMarker()}`,
		artist: ALBUM_ARTIST
	});

	await seedFillerAlbums(`${RAIL_FILLER_ALBUM_TITLE_PREFIX} ${runMarker()}`);

	return {
		albumTitle,
		albumSongCount: SONG_TITLES.length,
		albumTracks: albumSongs.map((song) => song.track),
		albumId: album.id,
		albumShareUrl: `${BASE_URL}/share/${share.share_slug}`,
		playlistShareUrl: `${BASE_URL}/share/playlist/${playlistShare.share_slug}`,
		pickedSongTitle,
		listenReorderSongs,
		secondAlbumTitle,
		secondAlbumSongTitle: RAIL_ALBUM_SONG_TITLES[0],
		kineticStripAlbumId: kineticStripAlbum.id,
		songPhoneAlbumId: songPhoneAlbum.id,
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
	const caption = VOICES_OCCUPANCY_PROMPT;
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
				requiredEnv('E2E_ADMIN_USERNAME'),
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
		const versions = await seed.getJson<VersionResource[]>(`/api/songs/${songId}/versions`);
		const versionId = versions.at(-1)?.id;
		if (!versionId) throw new Error(`Voices source song ${songId} has no version`);
		return { songTitle, songId, versionId, caption, lyrics };
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Seeding the voices source take failed: ${detail}`, { cause: err });
	}
}

/** Creates one ordinary version per adapter comparison side through the public API. */
export async function seedVoiceAdapterComparisonSong(
	api: APIRequestContext,
	userLoraId: string | null
): Promise<SeededVoiceProofSong> {
	const seed = await SeedApi.fromSession(api);
	const marker = runMarker();
	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: `E2E Voice Adapter Album ${marker}`,
		artist: ALBUM_ARTIST
	});
	const song = await seed.postJson<CreatedSong>('/api/songs', {
		title: userLoraId ? `E2E With Voice ${marker}` : `E2E Without Voice ${marker}`,
		album_id: album.id,
		lyrics: VOICE_ADAPTER_COMPARISON_LYRICS,
		prompt: VOICE_ADAPTER_COMPARISON_PROMPT,
		generation_params: userLoraId ? { user_lora_id: userLoraId } : null
	});
	const versions = await seed.getJson<VersionResource[]>(`/api/songs/${song.id}/versions`);
	const versionId = versions.at(-1)?.id;
	if (!versionId) throw new Error(`Voice comparison song ${song.id} has no version`);
	return { albumId: album.id, songId: song.id, songSlug: song.slug, versionId };
}

/**
 * The foreign-mode proof reuses a genuinely trained adapter, then changes only
 * its declared model mode in the isolated E2E database. It never seeds a
 * ready state or an adapter storage path.
 */
export async function setVoiceProofModelMode(
	voiceId: string,
	modelMode: 'sft' | 'turbo'
): Promise<void> {
	const script = [
		'from songmaker_cli.db.engine import connect_db, resolve_database_url',
		'from songmaker_cli.db.queries.loras import get_user_lora, update_user_lora',
		'import sys',
		'factory = connect_db(resolve_database_url())',
		'with factory() as session:',
		'    voice = get_user_lora(session, sys.argv[1], include_deleted_rows=True)',
		'    if voice is None: raise SystemExit(f"Voice {sys.argv[1]} was not found")',
		'    update_user_lora(session, voice.id, model_mode=sys.argv[2])',
		'    session.commit()'
	].join('\n');
	try {
		await execFileAsync(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'songmaker-web',
				'/app/.venv/bin/python',
				'-c',
				script,
				voiceId,
				modelMode
			],
			{ cwd: REPO_ROOT }
		);
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Setting the trained voice model mode failed: ${detail}`, { cause: err });
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
		const response = await api.get(`/api/loras/${voiceId}`);
		if (!response.ok()) {
			throw new Error(`GET /api/loras/${voiceId} failed: ${response.status()}`);
		}
		const voice = (await response.json()) as VoiceLifecycle;
		if (voice.deleted_at !== null) continue;
		await expect
			.poll(
				async () => {
					const current = await api.get(`/api/loras/${voiceId}`);
					if (!current.ok()) {
						throw new Error(`GET /api/loras/${voiceId} failed: ${current.status()}`);
					}
					const currentVoice = (await current.json()) as VoiceLifecycle;
					return !['queued', 'preprocessing', 'training', 'exporting'].includes(
						currentVoice.status
					);
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
	songId: string,
	versionId: string
): Promise<QueuedJob> {
	const seed = await SeedApi.fromSession(api);
	return seed.postJson<QueuedJob>(`/api/songs/${songId}/generate`, {
		count: 1,
		model: 'sft',
		version_id: versionId
	});
}

/** Queues a normal, non-occupying generation for the deterministic adapter comparison. */
export async function queueVoiceAdapterComparison(
	api: APIRequestContext,
	songId: string,
	versionId: string,
	seedValue: number
): Promise<QueuedJob> {
	const seed = await SeedApi.fromSession(api);
	return seed.postJson<QueuedJob>(`/api/songs/${songId}/generate`, {
		count: 1,
		model: 'sft',
		version_id: versionId,
		seed: seedValue
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
				requiredEnv('E2E_ADMIN_USERNAME')
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

export async function seedJobState(verb: string, args: string[], audio?: Buffer): Promise<string> {
	const commandArgs = [
		...COMPOSE_ARGS,
		'exec',
		'-T',
		'songmaker-web',
		'/app/.venv/bin/python',
		'scripts/seed_e2e_job_states.py',
		verb,
		...args
	];
	try {
		const { stdout } = audio
			? await execWithStdin('docker', commandArgs, { cwd: REPO_ROOT }, audio)
			: await execFileAsync('docker', commandArgs, { cwd: REPO_ROOT });
		return stdout.trim();
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		const stderr = (err as { stderr?: string }).stderr ?? '';
		throw new Error(`Seeding job state ${verb} failed: ${detail}\n${stderr}`, { cause: err });
	}
}

export function requiredSeedId(id: string): string {
	if (!id) throw new Error('seed_e2e_job_states.py printed no id on stdout');
	return id;
}

/**
 * A song already at `versionNumber` with `takeCount` real takes on that
 * version, seeded directly against the database
 * (`scripts/seed_e2e_job_states.py`) rather than through `versionNumber - 1`
 * individual saves and `takeCount` reimports — the same reasoning
 * `seedTakeStripSong` above already uses (issue #344): those requests would
 * exercise no API semantics `song-phone.spec.ts` needs, only cost its
 * budget. Returns the song's id.
 */
export async function seedSongPhoneSong(
	albumId: string,
	title: string,
	versionNumber: number,
	takeCount: number
): Promise<string> {
	return requiredSeedId(
		await seedJobState(
			'create-song',
			[
				'--album-id',
				albumId,
				'--title',
				title,
				'--version-number',
				String(versionNumber),
				'--take-count',
				String(takeCount),
				'--owner-username',
				requiredEnv('E2E_ADMIN_USERNAME')
			],
			readFileSync(TAKE_FIXTURE)
		)
	);
}

export async function seedQueuedGenerationJob(songId: string): Promise<string> {
	return requiredSeedId(
		await seedJobState('set-queued', [
			'--song-id',
			songId,
			'--owner-username',
			requiredEnv('E2E_ADMIN_USERNAME')
		])
	);
}

type GenerationPhase = NonNullable<JobItem['phase']>;

/**
 * The phase a seeded running job is in. A generating `phase` starts the
 * remaining-time estimate's clock; `generationStartedOffsetSeconds` moves that
 * start into the past, so the estimate has elapsed time to work with. A phase
 * that has not started generating (`loading_model`) has no clock to move and
 * takes no offset.
 */
type PhaseMove = {
	phase: GenerationPhase;
	generationStartedOffsetSeconds?: number;
};

function phaseArgs({ phase, generationStartedOffsetSeconds }: PhaseMove): string[] {
	const offsetArgs =
		generationStartedOffsetSeconds === undefined
			? []
			: ['--generation-started-offset', String(generationStartedOffsetSeconds)];
	return ['--phase', phase, ...offsetArgs];
}

/**
 * A running generate job for `songId`, seeded directly against the database
 * (`scripts/seed_e2e_job_states.py`) since CI's e2e stack runs no ACE-Step
 * worker to produce one. `update_job_status`'s own RUNNING branch sets
 * `heartbeat_at` to the moment the row is written, comfortably inside
 * `JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS` for the rest of the test — nothing
 * here needs to touch it by hand. Returns the job's id.
 */
export async function seedRunningGenerationJob(
	songId: string,
	options: {
		progress: number;
		takeIndex: number;
		takeCount: number;
	} & PhaseMove
): Promise<string> {
	return requiredSeedId(
		await seedJobState('set-running', [
			'--song-id',
			songId,
			'--progress',
			String(options.progress),
			'--take-index',
			String(options.takeIndex),
			'--take-count',
			String(options.takeCount),
			...phaseArgs(options),
			'--owner-username',
			requiredEnv('E2E_ADMIN_USERNAME')
		])
	);
}

/**
 * Moves an existing running generate job on to a later phase in place — the
 * same job id, so its own open `/api/jobs/{id}/stream` reports the move live,
 * the way a worker leaving the model load would. No reload needed.
 */
export async function advanceGenerationJobPhase(
	jobId: string,
	options: { progress: number } & PhaseMove
): Promise<void> {
	await seedJobState('set-phase', [
		'--job-id',
		jobId,
		'--progress',
		String(options.progress),
		...phaseArgs(options)
	]);
}

/**
 * Fails an existing generate job in place — the same job id a running
 * generation was seeded on, not a fresh one — so its own open
 * `/api/jobs/{id}/stream` (which polls the row every
 * `SSE_POLL_INTERVAL_SECONDS`) picks up the transition live, the way a real
 * worker crash would report it. No reload needed.
 */
export async function failGenerationJob(jobId: string, error: string): Promise<void> {
	await seedJobState('set-failed', ['--job-id', jobId, '--error', error]);
}

/**
 * Completes an existing generate job with its declared batch on its song's latest
 * version, in the same commit, so the job's own open
 * `/api/jobs/{id}/stream` reports the end only once the take is readable.
 * The `generation.created` resource event a real worker also writes is left
 * out on purpose (`set-completed` in `scripts/seed_e2e_job_states.py`): it
 * stands in for the event a phone's dropped resource stream never received,
 * so only the job's own terminal refresh can bring the take into the list.
 */
export async function completeGenerationJobWithoutEvent(jobId: string): Promise<void> {
	await seedJobState('set-completed', ['--job-id', jobId], readFileSync(TAKE_FIXTURE));
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

/** One account with a database session of its own, as the cookies a browser or API context carries. */
export interface SeededAccount {
	id: string;
	username: string;
	cookies: Cookie[];
}

interface SeededSessionRow {
	user_id: string;
	username: string;
	session_cookie_name: string;
	session_cookie_value: string;
	csrf_cookie_name: string;
	csrf_cookie_value: string;
	secure: boolean;
	same_site: 'strict' | 'lax';
}

const SEED_SESSIONS_SCRIPT = path.join(E2E_DIR, 'support', 'seed_sessions.py');
const SEED_SESSIONS_REQUEST_VARIABLE = 'SEED_SESSIONS_REQUEST';

/**
 * Runs `support/seed_sessions.py` in the web container (script on stdin,
 * request in the environment) and returns its last stdout line, the JSON result.
 */
async function runSeedSessions(sessionRequest: {
	seed?: Array<{ username: string; role?: AccountRole }>;
}): Promise<SeededSessionRow[]> {
	try {
		const { stdout } = await execWithStdin(
			'docker',
			[
				...COMPOSE_ARGS,
				'exec',
				'-T',
				'-e',
				`${SEED_SESSIONS_REQUEST_VARIABLE}=${JSON.stringify(sessionRequest)}`,
				'songmaker-web',
				'/app/.venv/bin/python',
				'-'
			],
			{ cwd: REPO_ROOT },
			readFileSync(SEED_SESSIONS_SCRIPT)
		);
		const lastLine = stdout.trim().split('\n').at(-1) ?? '';
		return JSON.parse(lastLine) as SeededSessionRow[];
	} catch (err) {
		const detail = err instanceof Error ? err.message : String(err);
		throw new Error(`Seeding sessions failed: ${detail}`, { cause: err });
	}
}

function sessionCookies(row: SeededSessionRow): Cookie[] {
	const shared = {
		domain: new URL(BASE_URL).hostname,
		path: '/',
		expires: -1,
		secure: row.secure,
		sameSite: row.same_site === 'lax' ? ('Lax' as const) : ('Strict' as const)
	};
	return [
		{
			...shared,
			name: row.session_cookie_name,
			value: row.session_cookie_value,
			httpOnly: true
		},
		{ ...shared, name: row.csrf_cookie_name, value: row.csrf_cookie_value, httpOnly: false }
	];
}

/**
 * Signs `username` in without Keycloak: the account is found or
 * created and given a database session straight from the stack's own side, so
 * the app itself signs the cookies. The throwaway stack drops the account
 * with the run.
 */
export async function seedAccount(
	username: string,
	role: AccountRole = NON_ADMIN_ROLE
): Promise<SeededAccount> {
	const [row] = await runSeedSessions({ seed: [{ username, role }] });
	return { id: row.user_id, username: row.username, cookies: sessionCookies(row) };
}

/** The run's one admin: the stack has no admin bootstrap, so the seeding helper makes the account. */
export function seedAdminAccount(): Promise<SeededAccount> {
	return seedAccount(requiredEnv('E2E_ADMIN_USERNAME'), 'admin');
}

/** An API context that carries the account's session. */
export function signedInApi(account: SeededAccount): Promise<APIRequestContext> {
	return request.newContext({
		baseURL: BASE_URL,
		storageState: { cookies: account.cookies, origins: [] }
	});
}

/**
 * Seeds a flow's own account's whole library -- the library a musician has
 * before their first pick. `api` carries the account's session (`signedInApi`).
 */
export async function seedUnpickedLibrary(api: APIRequestContext): Promise<SeededUnpickedLibrary> {
	const seed = await SeedApi.fromSession(api);
	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: `${ALBUM_TITLE_PREFIX} ${runMarker()}`,
		artist: ALBUM_ARTIST
	});
	const songs = await seedAfterAlbum(api, album.id, () => seedSongsWithOneTakeEach(seed, album.id));
	return { albumId: album.id, tracks: songs.map((song) => song.track) };
}

/** Runs the seeding that follows an album's creation; a failure archives that album before it rethrows, since no caller holds its id yet. */
async function seedAfterAlbum<T>(
	api: APIRequestContext,
	albumId: string,
	seedRest: () => Promise<T>
): Promise<T> {
	try {
		return await seedRest();
	} catch (error) {
		try {
			await archiveOwnedAlbum(api, albumId);
		} catch (archiveError) {
			throw new AggregateError(
				[error, archiveError],
				`Seeding failed and archiving album ${albumId} failed too`,
				{ cause: archiveError }
			);
		}
		throw error;
	}
}

/**
 * Gives a flow's own account one album holding one song titled `songTitle`,
 * returning that song's address -- a page only that account may open. `api`
 * carries the account's session (`signedInApi`).
 */
export async function seedOwnSongAddress(
	api: APIRequestContext,
	account: SeededAccount,
	songTitle: string
): Promise<string> {
	const seed = await SeedApi.fromSession(api);
	return (await createOwnSong(api, seed, account.username, songTitle)).address;
}

/** `seedOwnSongAddress`, with one take of the fixture tone the song plays. */
export async function seedOwnTakeAddress(
	api: APIRequestContext,
	account: SeededAccount,
	songTitle: string
): Promise<string> {
	const seed = await SeedApi.fromSession(api);
	const song = await createOwnSong(api, seed, account.username, songTitle);
	await seedAfterAlbum(api, song.albumId, () =>
		seed.postFile<ImportedTake>(`/api/songs/${song.id}/reimport`, {
			mp3: { name: 'take.mp3', mimeType: 'audio/mpeg', buffer: readFileSync(TAKE_FIXTURE) }
		})
	);
	return song.address;
}

async function createOwnSong(
	api: APIRequestContext,
	seed: SeedApi,
	username: string,
	songTitle: string
): Promise<{ id: string; albumId: string; address: string }> {
	const album = await seed.postJson<CreatedResource>('/api/albums', {
		title: `${ALBUM_TITLE_PREFIX} ${runMarker()}`,
		artist: username
	});
	const song = await seedAfterAlbum(api, album.id, () =>
		seed.postJson<CreatedSong>('/api/songs', {
			title: songTitle,
			album_id: album.id,
			lyrics: `${songTitle} lyrics`,
			prompt: 'calm test tone'
		})
	);
	return { id: song.id, albumId: album.id, address: `/album/${album.id}/${song.slug}` };
}

export interface PhoneLibraryFixture {
	albums: Array<{ id: string; title: string; count: number }>;
	playlist: { id: string; title: string };
	tracks: Record<string, Array<{ title: string; audioPath: string }>>;
}

/** A fresh account's 43 albums, including unheard, archived-only and unpicked music. */
export async function seedPhoneLibrary(api: APIRequestContext): Promise<PhoneLibraryFixture> {
	const seed = await SeedApi.fromSession(api);
	const albums: PhoneLibraryFixture['albums'] = [];
	const tracks: PhoneLibraryFixture['tracks'] = {};
	// Repeated MPEG frames keep the real tone sounding throughout transport assertions.
	const tone = readFileSync(TAKE_FIXTURE);
	const audio = Buffer.concat(Array.from({ length: 40 }, () => tone));
	for (let index = 0; index < 43; index++) {
		const title = `E2E Phone ${String(index).padStart(2, '0')}${index === 41 ? ' The Extraordinarily Long Album Title That Keeps Going' : ''}`;
		const album = await seed.postJson<CreatedResource>('/api/albums', { title });
		const count = index === 2 ? 2 : [1, 41, 42].includes(index) ? 1 : 0;
		albums.push({ id: album.id, title, count });
		if (!count) continue;
		tracks[album.id] = [];
		for (let trackIndex = 0; trackIndex < count; trackIndex++) {
			const songTitle = `E2E Phone Song ${index} ${trackIndex + 1}`;
			const song = await seed.postJson<CreatedResource>('/api/songs', {
				title: songTitle,
				album_id: album.id
			});
			const take = await seed.postFile<ImportedTake>(`/api/songs/${song.id}/reimport`, {
				mp3: { name: 'phone-proof.mp3', mimeType: 'audio/mpeg', buffer: audio }
			});
			tracks[album.id].push({ title: songTitle, audioPath: AUDIO_PATH_PREFIX + take.mp3_path });
			if (index === 1) {
				await execWithStdin(
					'docker',
					[
						...COMPOSE_ARGS,
						'exec',
						'-T',
						'postgres',
						'psql',
						'-U',
						postgresUser(),
						'-d',
						postgresDatabase(),
						'-v',
						'ON_ERROR_STOP=1',
						'-v',
						`take_id=${take.id}`
					],
					{ cwd: REPO_ROOT },
					Buffer.from(
						"UPDATE generations SET is_archived = true, archived_at = now() WHERE id = :'take_id';"
					)
				);
			}
		}
	}
	const title = 'E2E Phone Playlist With An Extraordinarily Long Name That Keeps Going';
	const playlist = await seed.postJson<CreatedResource>('/api/playlists', { title });
	return { albums, playlist: { id: playlist.id, title }, tracks };
}

export async function archiveOwnedAlbum(api: APIRequestContext, albumId: string): Promise<void> {
	const seed = await SeedApi.fromSession(api);
	await seed.postJson(`/api/albums/${albumId}/archive`, {});
}

/** Archives the album an address from `seedOwnSongAddress` or `seedOwnTakeAddress` sits under. */
export async function archiveAlbumOfAddress(
	api: APIRequestContext,
	songAddress: string
): Promise<void> {
	const [, , albumId] = songAddress.split('/');
	await archiveOwnedAlbum(api, albumId);
}

export async function archivePhoneLibrary(
	api: APIRequestContext,
	fixture: PhoneLibraryFixture
): Promise<void> {
	for (const album of fixture.albums) await archiveOwnedAlbum(api, album.id);
}
