import type { PlaybackInfo } from './audioPlayer.svelte';
import { recordPlaybackEvent } from './playbackDiagnostics';

interface MediaHandlers {
	play: () => void;
	pause: () => void;
	stop: () => void;
	next: () => void;
	prev: () => void;
	seekTo: (seconds: number) => void;
}

let activeHandlers: MediaHandlers | null = null;

export function setupMediaSessionHandlers(handlers: MediaHandlers): () => void {
	activeHandlers = handlers;
	applyMediaSessionHandlers(handlers);
	return () => {
		if (activeHandlers !== handlers) return;
		activeHandlers = null;
		clearMediaSessionHandlers();
	};
}

export function updateMediaSessionMetadata(info: PlaybackInfo | null): void {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	if (!info) {
		navigator.mediaSession.metadata = null;
		return;
	}
	if (typeof MediaMetadata === 'undefined') return;
	navigator.mediaSession.metadata = new MediaMetadata({
		title: info.songTitle,
		artist: info.artist,
		album: info.albumTitle
	});
}

export function updateMediaSessionPlaybackState(status: 'none' | 'paused' | 'playing'): void {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	navigator.mediaSession.playbackState = status;
}

export function updateMediaSessionPositionState(position: number, duration: number): void {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	if (!Number.isFinite(position) || !Number.isFinite(duration) || duration <= 0) return;
	try {
		navigator.mediaSession.setPositionState({
			duration,
			playbackRate: 1,
			position: Math.max(0, Math.min(position, duration))
		});
	} catch {
		// Browser does not support position state or rejected the values.
	}
}

function applyMediaSessionHandlers(handlers: MediaHandlers): void {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	const mediaSession = navigator.mediaSession;
	const set = (action: MediaSessionAction, handler: MediaSessionActionHandler) =>
		safeSetHandler(mediaSession, action, recordedAction(action, handler));
	set('play', handlers.play);
	set('pause', handlers.pause);
	set('stop', handlers.stop);
	set('nexttrack', handlers.next);
	set('previoustrack', handlers.prev);
	set('seekto', (details: MediaSessionActionDetails) => {
		if (typeof details.seekTime === 'number') handlers.seekTo(details.seekTime);
	});
}

function recordedAction(
	action: MediaSessionAction,
	handler: MediaSessionActionHandler
): MediaSessionActionHandler {
	return (details) => {
		const detail = typeof details.seekTime === 'number' ? `${action} ${details.seekTime}` : action;
		recordPlaybackEvent({ kind: 'media_session_action', detail, take: null });
		handler(details);
	};
}

function clearMediaSessionHandlers(): void {
	if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
	const mediaSession = navigator.mediaSession;
	safeSetHandler(mediaSession, 'play', null);
	safeSetHandler(mediaSession, 'pause', null);
	safeSetHandler(mediaSession, 'stop', null);
	safeSetHandler(mediaSession, 'nexttrack', null);
	safeSetHandler(mediaSession, 'previoustrack', null);
	safeSetHandler(mediaSession, 'seekto', null);
}

function safeSetHandler(
	mediaSession: MediaSession,
	action: MediaSessionAction,
	handler: MediaSessionActionHandler | null
): void {
	try {
		mediaSession.setActionHandler(action, handler);
	} catch {
		// Browser does not support this action.
	}
}
