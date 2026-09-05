import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	pushMediaSessionHandlers,
	setupMediaSessionHandlers,
	updateMediaSessionMetadata,
	updateMediaSessionPlaybackState,
	updateMediaSessionPositionState,
	updateMediaSessionTitle
} from './mediaSession';

type Action = 'play' | 'pause' | 'stop' | 'nexttrack' | 'previoustrack' | 'seekto';

interface FakeMediaSession {
	handlers: Map<Action, MediaSessionActionHandler | null>;
	metadata: MediaMetadata | null;
	playbackState: MediaSessionPlaybackState;
	positionStates: MediaPositionState[];
	setPositionState: (state?: MediaPositionState) => void;
	setActionHandler: (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => void;
}

function fakeMediaSession(rejectedAction?: Action): FakeMediaSession {
	const handlers = new Map<Action, MediaSessionActionHandler | null>();
	return {
		handlers,
		metadata: null,
		playbackState: 'none',
		positionStates: [],
		setPositionState(state) {
			if (state) this.positionStates.push(state);
		},
		setActionHandler(action, handler) {
			if (action === rejectedAction) throw new Error('unsupported action');
			handlers.set(action as Action, handler);
		}
	};
}

function installMediaSession(rejectedAction?: Action): FakeMediaSession {
	const session = fakeMediaSession(rejectedAction);
	vi.stubGlobal('navigator', { mediaSession: session });
	class FakeMediaMetadata {
		constructor(readonly values: MediaMetadataInit) {}
	}
	vi.stubGlobal('MediaMetadata', FakeMediaMetadata);
	return session;
}

function callbacks(label: string, calls: string[]) {
	return {
		play: () => calls.push(`${label}:play`),
		pause: () => calls.push(`${label}:pause`),
		stop: () => calls.push(`${label}:stop`),
		next: () => calls.push(`${label}:next`),
		prev: () => calls.push(`${label}:prev`),
		seekTo: (seconds: number) => calls.push(`${label}:seek:${seconds}`)
	};
}

function invoke(
	session: FakeMediaSession,
	action: Action,
	details: Partial<MediaSessionActionDetails> = {}
): void {
	session.handlers.get(action)?.(details as MediaSessionActionDetails);
}

afterEach(() => {
	const removeCleanupHandlers = setupMediaSessionHandlers(callbacks('cleanup', []));
	removeCleanupHandlers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('Media Session handlers', () => {
	it.each([
		['play', 'play'],
		['pause', 'pause'],
		['stop', 'stop'],
		['nexttrack', 'next'],
		['previoustrack', 'prev']
	] as const)('routes the %s action to the active player behaviour', (action, expected) => {
		const session = installMediaSession();
		const calls: string[] = [];
		const remove = setupMediaSessionHandlers(callbacks('player', calls));

		invoke(session, action);

		expect(calls).toEqual([`player:${expected}`]);
		remove();
	});

	it('forwards seek positions but ignores seek actions without a position', () => {
		const session = installMediaSession();
		const calls: string[] = [];
		const remove = setupMediaSessionHandlers(callbacks('player', calls));

		invoke(session, 'seekto', { seekTime: 42 });
		invoke(session, 'seekto');

		expect(calls).toEqual(['player:seek:42']);
		remove();
	});

	it('restores the previous owner when a temporary owner leaves', () => {
		const session = installMediaSession();
		const calls: string[] = [];
		const removeBase = setupMediaSessionHandlers(callbacks('base', calls));
		const removeTemporary = pushMediaSessionHandlers(callbacks('temporary', calls));

		invoke(session, 'play');
		removeTemporary();
		invoke(session, 'play');
		removeBase();
		invoke(session, 'play');

		expect(calls).toEqual(['temporary:play', 'base:play']);
	});

	it('removes a temporary owner when it has no previous owner to restore', () => {
		const session = installMediaSession();
		const calls: string[] = [];
		const removeTemporary = pushMediaSessionHandlers(callbacks('temporary', calls));

		invoke(session, 'play');
		removeTemporary();
		invoke(session, 'play');

		expect(calls).toEqual(['temporary:play']);
	});

	it('leaves the currently active owner in place when an older owner is removed', () => {
		const session = installMediaSession();
		const calls: string[] = [];
		const removeBase = setupMediaSessionHandlers(callbacks('base', calls));
		const removeTemporary = setupMediaSessionHandlers(callbacks('temporary', calls));

		removeBase();
		invoke(session, 'pause');
		removeTemporary();
		invoke(session, 'pause');

		expect(calls).toEqual(['temporary:pause']);
	});

	it('continues with supported actions when the browser rejects one action', () => {
		const session = installMediaSession('stop');
		const calls: string[] = [];
		const remove = setupMediaSessionHandlers(callbacks('player', calls));

		invoke(session, 'play');

		expect(calls).toEqual(['player:play']);
		remove();
	});

	it('does nothing when the browser has no Media Session API', () => {
		vi.stubGlobal('navigator', {});
		const calls: string[] = [];

		expect(() => {
			const remove = setupMediaSessionHandlers(callbacks('player', calls));
			remove();
			updateMediaSessionMetadata(null);
			updateMediaSessionTitle('Song');
			updateMediaSessionPlaybackState('playing');
			updateMediaSessionPositionState(1, 2);
		}).not.toThrow();
		expect(calls).toEqual([]);
	});
});

describe('Media Session state', () => {
	it('publishes playback metadata and clears it when nothing is playing', () => {
		const session = installMediaSession();

		updateMediaSessionMetadata({
			songTitle: 'Night Drive',
			artist: 'The Makers',
			albumTitle: 'After Dark'
		} as Parameters<typeof updateMediaSessionMetadata>[0]);

		expect((session.metadata as unknown as { values: MediaMetadataInit }).values).toEqual({
			title: 'Night Drive',
			artist: 'The Makers',
			album: 'After Dark'
		});
		updateMediaSessionMetadata(null);
		expect(session.metadata).toBeNull();
	});

	it.each([
		['Interlude', undefined, { title: 'Interlude', artist: '' }],
		['Interlude', 'The Makers', { title: 'Interlude', artist: 'The Makers' }]
	])('publishes title metadata with %s and %s', (title, artist, expected) => {
		const session = installMediaSession();

		updateMediaSessionTitle(title, artist);

		expect((session.metadata as unknown as { values: MediaMetadataInit }).values).toEqual(expected);
	});

	it.each(['none', 'paused', 'playing'] as const)('publishes the %s playback state', (state) => {
		const session = installMediaSession();

		updateMediaSessionPlaybackState(state);

		expect(session.playbackState).toBe(state);
	});

	it.each([
		[-2, 10, { duration: 10, playbackRate: 1, position: 0 }],
		[12, 10, { duration: 10, playbackRate: 1, position: 10 }],
		[4, 10, { duration: 10, playbackRate: 1, position: 4 }]
	])('limits a position of %s to the playable duration', (position, duration, expected) => {
		const session = installMediaSession();

		updateMediaSessionPositionState(position, duration);

		expect(session.positionStates).toEqual([expected]);
	});

	it.each([
		[Number.NaN, 10],
		[1, Number.NaN],
		[1, 0],
		[1, -2]
	])('does not publish an invalid position state for %s/%s', (position, duration) => {
		const session = installMediaSession();

		updateMediaSessionPositionState(position, duration);

		expect(session.positionStates).toEqual([]);
	});

	it('ignores a browser rejection of an otherwise valid position state', () => {
		const session = installMediaSession();
		session.setPositionState = () => {
			throw new Error('unsupported position state');
		};

		expect(() => updateMediaSessionPositionState(1, 2)).not.toThrow();
	});
});
