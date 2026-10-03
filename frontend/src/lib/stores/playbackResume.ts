import { untrack } from 'svelte';
import { get, toStore } from 'svelte/store';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import { currentUser } from '$lib/stores/auth';
import { LIBRARY_TAKE_POOLS, type LibraryTakePool } from '$lib/stores/playbackSettings';

// What the app was playing, kept per user on this device, so that reopening
// a page Android killed can show the same take at the same position (#1187
// P2). Only the app's own takes are followed, never a share route's.

export type ResumeQueueSource =
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
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PROGRESS_SAVE_EVERY_SECONDS = 5;

function storageKey(userId: string): string {
	return `${STORAGE_KEY_PREFIX}${userId}`;
}

// A logout in another tab removes the record, but this tab still holds the
// user until its own session check fails; the take it keeps playing must not
// write the record back, and a copy written before this tab heard of the
// logout goes too (#1209). Saving resumes once the signed-in user changes.
let loggedOutInAnotherTab = false;

function signedInUserId(): string | null {
	if (loggedOutInAnotherTab) return null;
	return get(currentUser)?.id ?? null;
}

function stopSavingOnLogoutInAnotherTab(): void {
	window.addEventListener('storage', (event) => {
		const userId = signedInUserId();
		if (userId === null || event.key !== storageKey(userId) || event.newValue !== null) return;
		forgetPlaybackResume(userId);
		stopSavingUntilTheUserChanges();
	});
}

function stopSavingUntilTheUserChanges(): void {
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
	if (next === null || source === null) forgetPlaybackResume(userId);
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

// Private browsing, a full quota or blocked site data: resuming is a comfort,
// so playback goes on and simply nothing is remembered (#1209).
function readStorage(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function writeStorage(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		// Nothing is remembered; see readStorage.
	}
}

function removeStorage(key: string): void {
	try {
		localStorage.removeItem(key);
	} catch {
		// Storage that cannot be reached holds no record to forget.
	}
}
