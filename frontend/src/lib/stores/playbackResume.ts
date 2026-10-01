import { untrack } from 'svelte';
import { get, toStore } from 'svelte/store';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import { currentUser } from '$lib/stores/auth';
import type { LibraryTakePool } from '$lib/stores/playbackSettings';

// What the app was playing, kept per user on this device, so that reopening
// a page Android killed can show the same take at the same position (#1187
// P2). Only the app's own queues are followed: the queue source the owner
// hands in is null whenever the player is not the app's (a share route).

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
		removeStorage(event.key);
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
}

/**
 * Called once by the app's player. Saves on a take change, on pause, when
 * the page hides, and about every 5 s of playback in between.
 */
export function followPlaybackForResume(queueSource: () => ResumeQueueSource | null): void {
	const save = () => saveWhatIsPlaying(queueSource);
	whenChanged(() => audioPlayer.current?.generation.id, save);
	whenChanged(
		() => audioPlayer.status,
		(status) => {
			if (status === 'paused') save();
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

function playedOnSinceLastSave(): boolean {
	const current = audioPlayer.current;
	if (current === null) return false;
	const userId = signedInUserId();
	if (userId === null) return false;
	const saved = readSavedPoint(userId);
	if (saved?.generationId !== current.generation.id) return true;
	return Math.abs(audioPlayer.currentTime - saved.position) >= PROGRESS_SAVE_EVERY_SECONDS;
}

function saveWhatIsPlaying(queueSource: () => ResumeQueueSource | null): void {
	const current = audioPlayer.current;
	if (current === null) return;
	const userId = signedInUserId();
	const source = queueSource();
	if (userId === null || source === null) return;
	writeStorage(storageKey(userId), JSON.stringify(recordOf(source, current)));
}

function recordOf(source: ResumeQueueSource, current: PlaybackInfo): PlaybackResumeRecord {
	return {
		source,
		songId: current.songId,
		generationId: current.generation.id,
		position: audioPlayer.currentTime,
		savedAt: Date.now()
	};
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

type SavedPoint = Pick<PlaybackResumeRecord, 'generationId' | 'position'>;

function readSavedPoint(userId: string): SavedPoint | null {
	const stored = readStorage(storageKey(userId));
	if (stored === null) return null;
	let value: unknown;
	try {
		value = JSON.parse(stored);
	} catch {
		return null;
	}
	return isSavedPoint(value) ? value : null;
}

function isSavedPoint(value: unknown): value is SavedPoint {
	if (typeof value !== 'object' || value === null) return false;
	const point = value as Record<string, unknown>;
	return typeof point.generationId === 'string' && Number.isFinite(point.position);
}
