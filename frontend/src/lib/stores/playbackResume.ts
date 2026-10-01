import { untrack } from 'svelte';
import { get, toStore } from 'svelte/store';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import type { PlaybackInfo } from '$lib/services/playbackTypes';
import { currentUser } from '$lib/stores/auth';
import { LIBRARY_TAKE_POOLS, type LibraryTakePool } from '$lib/stores/playbackSettings';

// What the app was playing, kept per user on this device, so that reopening
// a page Android killed can show the same take at the same position (#1187
// P2). Only the app's own queues are followed: the queue source the owner
// hands in is null whenever the player is not the app's (a share route).

export type ResumeQueueSource =
	| { type: 'album'; albumId: string }
	| { type: 'playlist'; playlistId: string }
	| { type: 'library'; pool: LibraryTakePool; shuffle: boolean };

export interface PlaybackResumeRecord {
	source: ResumeQueueSource;
	songId: string;
	generationId: string;
	position: number;
	savedAt: number;
}

const STORAGE_KEY_PREFIX = 'playbackResume:';
const PROGRESS_SAVE_EVERY_SECONDS = 5;
const VALID_POOLS: ReadonlySet<unknown> = new Set(LIBRARY_TAKE_POOLS);

function storageKey(userId: string): string {
	return `${STORAGE_KEY_PREFIX}${userId}`;
}

function signedInUserId(): string | null {
	return get(currentUser)?.id ?? null;
}

/**
 * The signed-in user's record, never another user's: the key is the
 * signed-in user's own.
 */
export function readPlaybackResume(): PlaybackResumeRecord | null {
	const userId = signedInUserId();
	if (userId === null) return null;
	const stored = readStorage(storageKey(userId));
	return stored === null ? null : parseRecord(stored);
}

export function forgetPlaybackResume(userId: string): void {
	try {
		localStorage.removeItem(storageKey(userId));
	} catch {
		// Storage that cannot be reached holds no record to forget.
	}
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
	const saved = readPlaybackResume();
	if (saved?.generationId !== current.generation.id) return true;
	return Math.abs(audioPlayer.currentTime - saved.position) >= PROGRESS_SAVE_EVERY_SECONDS;
}

function saveWhatIsPlaying(queueSource: () => ResumeQueueSource | null): void {
	const userId = signedInUserId();
	const current = audioPlayer.current;
	if (userId === null || current === null) return;
	const source = queueSource();
	if (source === null) return;
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

function parseRecord(stored: string): PlaybackResumeRecord | null {
	let value: unknown;
	try {
		value = JSON.parse(stored);
	} catch {
		return null;
	}
	return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is PlaybackResumeRecord {
	if (typeof value !== 'object' || value === null) return false;
	const record = value as Record<string, unknown>;
	return (
		isQueueSource(record.source) &&
		typeof record.songId === 'string' &&
		typeof record.generationId === 'string' &&
		Number.isFinite(record.position) &&
		Number.isFinite(record.savedAt)
	);
}

function isQueueSource(value: unknown): value is ResumeQueueSource {
	if (typeof value !== 'object' || value === null) return false;
	const source = value as Record<string, unknown>;
	if (source.type === 'album') return typeof source.albumId === 'string';
	if (source.type === 'playlist') return typeof source.playlistId === 'string';
	if (source.type === 'library') {
		return VALID_POOLS.has(source.pool) && typeof source.shuffle === 'boolean';
	}
	return false;
}
