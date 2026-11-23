import { untrack } from 'svelte';
import { get, toStore } from 'svelte/store';
import { fetchPlaylist, fetchSong } from '#lib/api/client.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { GenerationItem, PlaylistDetailItem, SongItem } from '#lib/api/types.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import type { PlaybackInfo } from '#lib/services/playbackTypes.ts';
import { currentUser } from '#lib/stores/auth.ts';
import { LIBRARY_TAKE_POOLS, type LibraryTakePool } from '#lib/stores/playbackSettings.ts';
import { isPlayableTake } from '#lib/utils/playable.ts';
import { readStorage, removeStorage, writeStorage } from '#lib/utils/storage.ts';

// What the app was playing, kept per user on this device, so that reopening
// a page Android killed can show the same take at the same position (#1187
// P2). Only the app's own takes are followed, never a share route's.

export type ResumeQueueSource =
	// The song of the saved take: a song queue holds no other song's takes.
	| { type: 'song' }
	| { type: 'album'; albumId: string }
	| { type: 'playlist'; playlistId: string }
	| { type: 'library'; pool: LibraryTakePool; shuffle: boolean };

interface PlaybackResumeRecord {
	source: ResumeQueueSource;
	songId: string;
	generationId: string;
	position: number;
	savedAt: number;
}

const STORAGE_KEY_PREFIX = 'playbackResume:';
const LOGOUT_KEY_PREFIX = 'playbackLogout:';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PROGRESS_SAVE_EVERY_SECONDS = 5;

function storageKey(userId: string): string {
	return `${STORAGE_KEY_PREFIX}${userId}`;
}

function logoutMarkerKey(userId: string): string {
	return `${LOGOUT_KEY_PREFIX}${userId}`;
}

// A tab can keep playing after logout until its own session check fails.
// Explicit logout suppresses saves until the next authenticated lifecycle;
// ordinary queue exhaustion only retires the current record.
let loggedOutInAnotherTab = false;

function signedInUserId(): string | null {
	if (loggedOutInAnotherTab) return null;
	return get(currentUser)?.id ?? null;
}

function stopSavingOnLogoutInAnotherTab(): void {
	window.addEventListener('storage', (event) => {
		const userId = signedInUserId();
		if (
			userId === null ||
			event.storageArea !== localStorage ||
			event.key !== logoutMarkerKey(userId) ||
			event.newValue === null ||
			event.newValue === event.oldValue
		)
			return;
		retireCurrentPlaybackResume(userId);
		stopSavingUntilTheUserChanges();
	});
}

function stopSavingUntilTheUserChanges(): void {
	if (loggedOutInAnotherTab) return;
	loggedOutInAnotherTab = true;
	let heardTheCurrentUser = false;
	const stopListening = currentUser.subscribe(() => {
		if (!heardTheCurrentUser) {
			heardTheCurrentUser = true;
			return;
		}
		loggedOutInAnotherTab = false;
		stopListening();
	});
}

export function forgetPlaybackResume(userId: string): void {
	retireCurrentPlaybackResume(userId);
	if (get(currentUser)?.id === userId) stopSavingUntilTheUserChanges();
	writeStorage(logoutMarkerKey(userId), crypto.randomUUID());
}

function retireCurrentPlaybackResume(userId: string): void {
	removeStorage(storageKey(userId));
	if (knownRecord?.userId === userId) knownRecord = null;
}

/** Where the signed-in user's take stood when this device last saved it. */
export interface SavedPlayback {
	source: ResumeQueueSource;
	songId: string;
	generationId: string;
	position: number;
}

/** The signed-in user's saved take; null when none is saved or it cannot be read. */
export function savedPlayback(): SavedPlayback | null {
	const userId = signedInUserId();
	if (userId === null) return null;
	const saved = parseSavedPlayback(readStorage(storageKey(userId)));
	if (saved !== null) knownRecord = { userId, ...saved };
	return saved;
}

// The entries are sorted, so the order a record wrote the fields in is no
// difference.
function sameQueueSource(a: ResumeQueueSource, b: ResumeQueueSource): boolean {
	const entriesOf = (source: ResumeQueueSource) => JSON.stringify(Object.entries(source).sort());
	return entriesOf(a) === entriesOf(b);
}

// A record that another tab has written since, for another take or from
// another queue, or one of another user, is not this restore's to drop. Only
// the position may differ: it moves on while the record still names the
// same gone thing.
function forgetSavedPlayback(userId: string | null, gone: SavedPlayback): void {
	if (userId === null || signedInUserId() !== userId) return;
	const stored = parseSavedPlayback(readStorage(storageKey(userId)));
	if (
		stored !== null &&
		stored.songId === gone.songId &&
		stored.generationId === gone.generationId &&
		sameQueueSource(stored.source, gone.source)
	) {
		retireCurrentPlaybackResume(userId);
	}
}

// A restore reports nothing it cannot find: a server out of reach, or an
// answer refusing the request, is no take to restore. A 404 means the record
// names something gone, so the record goes with it and later page loads do
// not ask again; any other failure keeps it for the next load.
async function quietly<T>(
	userId: string | null,
	saved: SavedPlayback,
	request: () => Promise<T>
): Promise<T | null> {
	try {
		return await request();
	} catch (err) {
		if (err instanceof ApiError && err.status === 404) forgetSavedPlayback(userId, saved);
		if (err instanceof ApiError || err instanceof NetworkError) return null;
		throw err;
	}
}

/**
 * The saved take as its song holds it now, when it can play. The server
 * answers 404 for a song deleted or out of this user's reach, and a take
 * deleted, archived or left without audio since is missing from its song or
 * marked so; the record of any of them is forgotten.
 */
export async function loadSavedTake(
	saved: SavedPlayback
): Promise<{ song: SongItem; take: GenerationItem } | null> {
	const userId = signedInUserId();
	const song = await quietly(userId, saved, () => fetchSong(saved.songId));
	if (song === null) return null;
	const take = song.generations.find((gen) => gen.id === saved.generationId && isPlayableTake(gen));
	if (take === undefined) {
		forgetSavedPlayback(userId, saved);
		return null;
	}
	return { song, take };
}

/** The saved take's playlist; null once it is deleted or out of reach. */
export function loadSavedPlaylist(
	saved: SavedPlayback,
	playlistId: string
): Promise<PlaylistDetailItem | null> {
	return quietly(signedInUserId(), saved, () => fetchPlaylist(playlistId));
}

interface PlaybackToFollow {
	/** Whether the player plays the app's own takes rather than a share route's. */
	playsTheAppsTakes: () => boolean;
	/** The queue the take plays from; null while the app holds none for it yet. */
	queueSource: () => ResumeQueueSource | null;
	/**
	 * The take a reopened page should show once the current one has ended, at
	 * its start: the queue's next one, or the ended one again where the queue
	 * goes on from it; null when the queue holds nothing more to play.
	 */
	takeAfterCurrent: () => PlaybackInfo | null;
}

// The user signed in when the current take started: a take is only ever
// saved under that user, so a user switch in this tab never hands one user's
// take to another (#1226).
let takeStartedUnder: string | null = null;

// The record as this tab last saved or read it, kept in memory so that the
// 5 s rhythm costs no storage read per tick, nor a write per tick once
// storage refuses (#1226).
let knownRecord: (SavedPlayback & { userId: string }) | null = null;

/**
 * Called once by the app's player. Saves on a take change, on pause, when
 * the page hides, and about every 5 s of playback in between; a take that
 * ended leaves the take the queue names after it, at its start.
 */
export function followPlaybackForResume(follow: PlaybackToFollow): void {
	const save = () => saveWhatIsPlaying(follow);
	whenChanged(
		() => audioPlayer.current?.generation.id,
		() => {
			takeStartedUnder = signedInUserId();
			save();
		}
	);
	whenChanged(
		() => audioPlayer.status,
		(status) => {
			if (status === 'paused') save();
			if (status === 'idle') saveTheTakeAfterTheEnd(follow);
		}
	);
	whenChanged(
		() => audioPlayer.currentTime,
		() => {
			if (playedOnSinceLastSave()) save();
		}
	);
	if (typeof document === 'undefined') return;
	stopSavingOnLogoutInAnotherTab();
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'hidden') save();
	});
}

// The reaction runs untracked, so the player state it reads to save does not
// become a reason to run it again.
function whenChanged<T>(read: () => T, react: (value: T) => void): void {
	toStore(read).subscribe((value) => untrack(() => react(value)));
}

function userTheTakeStartedUnder(): string | null {
	const userId = signedInUserId();
	return userId !== null && userId === takeStartedUnder ? userId : null;
}

// The player stands idle with a take loaded only once that take has ended.
function takeHasEnded(): boolean {
	return audioPlayer.status === 'idle';
}

function playedOnSinceLastSave(): boolean {
	const current = audioPlayer.current;
	if (current === null || takeHasEnded()) return false;
	const userId = userTheTakeStartedUnder();
	if (userId === null) return false;
	const saved = savedRecordOf(userId, current);
	if (saved === null) return true;
	return Math.abs(audioPlayer.currentTime - saved.position) >= PROGRESS_SAVE_EVERY_SECONDS;
}

function savedRecordOf(userId: string, take: PlaybackInfo): SavedPlayback | null {
	if (knownRecord?.userId !== userId || knownRecord.generationId !== take.generation.id) {
		return null;
	}
	return knownRecord;
}

// A take the app holds no queue for yet (one a reload restored, or one still
// playing while a new library queue builds) keeps the queue its record names;
// a take new to the record has none to keep and is not saved (#1226).
function saveWhatIsPlaying(follow: PlaybackToFollow): void {
	const current = audioPlayer.current;
	if (current === null || takeHasEnded() || !follow.playsTheAppsTakes()) return;
	const userId = userTheTakeStartedUnder();
	if (userId === null) return;
	const source = follow.queueSource() ?? savedRecordOf(userId, current)?.source ?? null;
	if (source === null) return;
	const position = positionToSave(userId, current);
	if (position === null) return;
	writeRecord(userId, recordOf(source, current, position));
}

// A take still loading, or failed to load, has no position of its own: one
// the record already holds keeps the saved position (a restore, a reload), a
// take new to it starts at 0. Otherwise the element's own clock counts, since
// the player's copy only moves with timeupdate and may stand a quarter second
// behind a pause (#1226).
function positionToSave(userId: string, take: PlaybackInfo): number | null {
	if (audioPlayer.status === 'loading' || audioPlayer.status === 'error') {
		return savedRecordOf(userId, take) === null ? 0 : null;
	}
	return audioPlayer.currentTimeNow ?? audioPlayer.currentTime;
}

function saveTheTakeAfterTheEnd(follow: PlaybackToFollow): void {
	if (audioPlayer.current === null || !follow.playsTheAppsTakes()) return;
	const userId = userTheTakeStartedUnder();
	if (userId === null) return;
	const next = follow.takeAfterCurrent();
	const source = follow.queueSource();
	if (next === null || source === null) retireCurrentPlaybackResume(userId);
	else writeRecord(userId, recordOf(source, next, 0));
}

function recordOf(
	source: ResumeQueueSource,
	take: PlaybackInfo,
	position: number
): PlaybackResumeRecord {
	return {
		source,
		songId: take.songId,
		generationId: take.generation.id,
		position,
		savedAt: Date.now()
	};
}

function writeRecord(userId: string, record: PlaybackResumeRecord): void {
	knownRecord = {
		userId,
		source: record.source,
		songId: record.songId,
		generationId: record.generationId,
		position: record.position
	};
	writeStorage(storageKey(userId), JSON.stringify(record));
}

function parseSavedPlayback(stored: string | null): SavedPlayback | null {
	if (stored === null) return null;
	let value: unknown;
	try {
		value = JSON.parse(stored);
	} catch {
		return null;
	}
	return isSavedPlayback(value)
		? {
				source: value.source,
				songId: value.songId,
				generationId: value.generationId,
				position: value.position
			}
		: null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

// A restore sends the record's ids to the server, so a record edited by hand
// or written by a broken build is refused here rather than requested.
function isUuid(value: unknown): value is string {
	return typeof value === 'string' && UUID_PATTERN.test(value);
}

function isResumeQueueSource(value: unknown): value is ResumeQueueSource {
	if (!isRecord(value)) return false;
	if (value.type === 'song') return true;
	if (value.type === 'album') return typeof value.albumId === 'string';
	if (value.type === 'playlist') return isUuid(value.playlistId);
	return (
		value.type === 'library' &&
		typeof value.shuffle === 'boolean' &&
		(LIBRARY_TAKE_POOLS as readonly unknown[]).includes(value.pool)
	);
}

function isSavedPlayback(value: unknown): value is SavedPlayback {
	if (!isRecord(value)) return false;
	return (
		isResumeQueueSource(value.source) &&
		isUuid(value.songId) &&
		isUuid(value.generationId) &&
		typeof value.position === 'number' &&
		Number.isFinite(value.position) &&
		value.position >= 0
	);
}
