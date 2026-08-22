import type { QueueStreamManifest } from '$lib/api/types';
import type { PlaybackInfo } from './playbackTypes';
import { QueueStreamEngine, type StreamFallbackState } from './queueStreamEngine';

export type { PlaybackInfo } from './playbackTypes';
export type { StreamFallbackState } from './queueStreamEngine';

export type PlayerStatus =
	| 'idle'
	| 'loading'
	| 'ready'
	| 'playing'
	| 'paused'
	| 'buffering'
	| 'error';

export type StreamEndReason = 'normal' | 'window-end';

// One typed object per owner of the singleton audioPlayer (the logged-in app
// via stores/player.ts, a share route via sharePlayback). swapCallbacks/
// restoreCallbacks move the whole set atomically so a new owner never
// inherits — or silently drops — a stray handler from the previous one, and
// app-only side effects (media-session metadata, the app's windowEnded
// store) never fire for a caller that never opted into them.
export interface AudioPlayerCallbacks {
	onEnded: ((reason: StreamEndReason) => void) | null;
	onPlaybackStarted: (() => void) | null;
	onAuthLost: (() => void | Promise<void>) | null;
	onStreamRebuild: ((state: StreamFallbackState) => Promise<QueueStreamManifest | null>) | null;
	onCurrentChange: ((current: PlaybackInfo | null) => void) | null;
}

const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null
};

const AUDIO_URL_PREFIX = '/audio/';
const ERROR_MSG_GENERIC = 'Playback failed. Click play to retry.';
const ERROR_MSG_NOT_FOUND = 'Audio file not found.';
const ERROR_MSG_NETWORK = 'Network error. Check connection and retry.';
const ERROR_MSG_STALLED = 'Playback stalled. Click play to retry.';
const STALL_RECOVERY_MS = 5000;
const MAX_RECOVERY_ATTEMPTS = 2;
const RECOVERY_SEEK_BACK_SECONDS = 0.75;

class AudioPlayer {
	status = $state<PlayerStatus>('idle');
	currentTime = $state(0);
	duration = $state(0);
	error = $state<string | null>(null);
	current = $state<PlaybackInfo | null>(null);
	mode = $state<'classic' | 'stream'>('classic');

	private callbacks: AudioPlayerCallbacks = NO_CALLBACKS;
	private audio: HTMLAudioElement | null = null;
	private currentUrl: string | null = null;
	private autoplayPending = false;
	private listenersAttached = false;
	private streamEngine = new QueueStreamEngine();
	private stallRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
	private recoveryAttempts = 0;
	private pendingRecoverySeek: number | null = null;
	private lastObservedTime = 0;
	private streamEndSignaled = false;
	private streamCanNext = $state(false);
	private streamCanPrev = $state(false);

	// Read-only view of the active callback set. Mutation only ever happens
	// through swapCallbacks/restoreCallbacks — this getter exists for
	// introspection (tests, diagnostics), never as a second write path.
	get currentCallbacks(): AudioPlayerCallbacks {
		return this.callbacks;
	}

	get canNextStreamTrack(): boolean {
		return this.streamCanNext;
	}

	get canPrevStreamTrack(): boolean {
		return this.streamCanPrev;
	}

	getElement(): HTMLAudioElement | null {
		return this.audio;
	}

	// Installs `next` as the active callback set and returns the set it
	// replaced, so a caller that only wants to visit (a share route) can
	// restore the previous owner's callbacks on teardown instead of leaving
	// the player with none.
	swapCallbacks(next: AudioPlayerCallbacks): AudioPlayerCallbacks {
		const previous = this.callbacks;
		this.callbacks = next;
		return previous;
	}

	restoreCallbacks(previous: AudioPlayerCallbacks): void {
		this.callbacks = previous;
	}

	load(
		info: PlaybackInfo,
		opts: { autoplay?: boolean; restart?: boolean; startAt?: number } = {}
	): void {
		this.loadFromUrl(info, AUDIO_URL_PREFIX + info.generation.mp3_path, opts);
	}

	// Classic per-track playback from a URL the caller already resolved
	// (share routes have no `/audio/{mp3_path}` endpoint of their own — see
	// `docs/architecture.md`'s share section). `load()` is `loadUrl()` with
	// the app's own URL convention plugged in; both funnel through the same
	// resolved-URL state so recovery and the auth probe never have to choose
	// between two URL sources.
	loadUrl(
		info: PlaybackInfo,
		url: string,
		opts: { autoplay?: boolean; restart?: boolean; startAt?: number } = {}
	): void {
		this.loadFromUrl(info, url, opts);
	}

	private loadFromUrl(
		info: PlaybackInfo,
		url: string,
		opts: { autoplay?: boolean; restart?: boolean; startAt?: number }
	): void {
		const autoplay = opts.autoplay ?? true;
		const restart = opts.restart ?? false;
		const sameGen =
			!this.streamEngine.active &&
			this.current?.generation.id === info.generation.id &&
			this.currentUrl === url;

		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.streamEndSignaled = false;
		this.mode = 'classic';
		this.setCurrent(info);
		this.currentUrl = url;
		this.error = null;

		if (sameGen && this.audio && this.status !== 'error' && !restart) {
			if (autoplay && this.status !== 'playing') this.play();
			return;
		}

		this.clearStallRecoveryTimer();
		this.recoveryAttempts = 0;
		this.pendingRecoverySeek = opts.startAt ?? null;
		this.lastObservedTime = 0;
		this.autoplayPending = autoplay;
		const el = this.ensureAudio();
		el.pause();
		this.status = 'loading';
		this.currentTime = 0;
		this.duration = 0;
		el.src = url;
		el.load();
	}

	loadStream(
		manifest: QueueStreamManifest,
		startIndex = 0,
		opts: { autoplay?: boolean; restart?: boolean; resumeAt?: number } = {}
	): void {
		const autoplay = opts.autoplay ?? true;
		const streamState = this.streamEngine.start(manifest, startIndex);
		if (!streamState) return;
		this.syncStreamBoundaries();
		if (opts.resumeAt !== undefined) this.streamEngine.resumeAt(opts.resumeAt);
		const el = this.ensureAudio();
		this.clearStallRecoveryTimer();
		this.recoveryAttempts = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.mode = 'stream';
		this.setCurrent(streamState.info);
		this.currentUrl = manifest.stream_url;
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
		this.error = null;
		this.autoplayPending = autoplay;
		el.pause();
		this.status = 'loading';
		el.src = manifest.stream_url;
		el.load();
		// The start-track seek is applied on loadedmetadata, never eagerly:
		// browsers accept a currentTime assignment before metadata without
		// error, then reset it to 0 when metadata arrives — which silently
		// started every stream at track 1.
	}

	play(): void {
		if (!this.audio || !this.current) return;
		if (this.status === 'error') {
			if (this.streamEngine.active) {
				this.recoveryAttempts = 0;
				void this.recoverStream('media-error');
				return;
			}
			this.load(this.current, { autoplay: true });
			return;
		}
		if (this.status === 'loading' || this.status === 'buffering') {
			this.autoplayPending = true;
			return;
		}
		this.audio.play().catch((err) => this.handlePlayRejection(err));
	}

	pause(): void {
		if (!this.audio) return;
		this.autoplayPending = false;
		this.clearStallRecoveryTimer();
		this.audio.pause();
		if (this.status !== 'error' && !this.audio.ended) this.status = 'paused';
	}

	toggle(): void {
		if (!this.audio || !this.current) return;
		if (this.status === 'error') {
			this.play();
			return;
		}
		if (this.status === 'loading') {
			// A press while loading must not be dropped: flip the queued intent
			// (second press cancels), delivered by the existing autoplayPending
			// machinery once the element is ready.
			this.autoplayPending = !this.autoplayPending;
			return;
		}
		if (this.audio.paused) this.play();
		else this.pause();
	}

	seek(seconds: number): void {
		if (!this.audio || this.duration <= 0) return;
		if (this.streamEngine.active) {
			this.streamEngine.seekLocal(this.audio, seconds);
			return;
		}
		this.audio.currentTime = Math.max(0, Math.min(seconds, this.duration));
	}

	seekToStreamTrack(index: number, opts: { autoplay?: boolean } = {}): boolean {
		if (!this.audio || !this.streamEngine.active) return false;
		const autoplay = opts.autoplay ?? !this.audio.paused;
		const streamState = this.streamEngine.seekToTrack(this.audio, index);
		if (!streamState) return false;
		this.syncStreamBoundaries();
		this.setCurrent(streamState.info);
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
		this.lastObservedTime = streamState.absoluteTime;
		if (autoplay) this.play();
		return true;
	}

	nextStreamTrack(opts: { autoplay?: boolean } = {}): boolean {
		if (!this.audio || !this.streamEngine.active) return false;
		const streamState = this.streamEngine.nextTrack(this.audio);
		this.syncStreamBoundaries();
		if (!streamState) return false;
		this.setCurrent(streamState.info);
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
		this.lastObservedTime = streamState.absoluteTime;
		if (opts.autoplay ?? !this.audio.paused) this.play();
		return true;
	}

	prevStreamTrack(opts: { autoplay?: boolean } = {}): boolean {
		if (!this.audio || !this.streamEngine.active) return false;
		const streamState = this.streamEngine.prevTrack(this.audio);
		this.syncStreamBoundaries();
		if (!streamState) return false;
		this.setCurrent(streamState.info);
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
		this.lastObservedTime = streamState.absoluteTime;
		if (opts.autoplay ?? !this.audio.paused) this.play();
		return true;
	}

	// Resets playback state (pause, drop the current track, clear the stream
	// session) but keeps the underlying <audio> element and its listeners —
	// unlike destroy(), which is a full teardown. A share route calls this on
	// unmount, after restoreCallbacks(), so a listener who navigates back
	// into the logged-in app never finds a synthetic share PlaybackInfo still
	// sitting in the transport bar.
	unload(): void {
		this.autoplayPending = false;
		this.clearStallRecoveryTimer();
		if (this.audio) {
			this.audio.pause();
			this.audio.src = '';
			this.audio.removeAttribute('src');
		}
		this.status = 'idle';
		this.setCurrent(null);
		this.currentUrl = null;
		this.mode = 'classic';
		this.currentTime = 0;
		this.duration = 0;
		this.error = null;
		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.recoveryAttempts = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.streamEndSignaled = false;
	}

	destroy(): void {
		this.streamEndSignaled = false;
		if (!this.audio) {
			this.streamEngine.clear();
			this.syncStreamBoundaries();
			return;
		}
		this.clearStallRecoveryTimer();
		this.audio.pause();
		this.audio.src = '';
		this.audio.removeAttribute('src');
		this.audio = null;
		this.currentUrl = null;
		this.listenersAttached = false;
		this.status = 'idle';
		this.setCurrent(null);
		this.mode = 'classic';
		this.currentTime = 0;
		this.duration = 0;
		this.error = null;
		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.recoveryAttempts = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
	}

	private ensureAudio(): HTMLAudioElement {
		if (this.audio) return this.audio;
		const el = new Audio();
		el.crossOrigin = 'anonymous';
		el.preload = 'auto';
		this.audio = el;
		this.attachListeners(el);
		return el;
	}

	private attachListeners(el: HTMLAudioElement): void {
		if (this.listenersAttached) return;
		this.listenersAttached = true;

		el.addEventListener('loadstart', () => {
			this.status = 'loading';
			this.error = null;
		});
		el.addEventListener('loadedmetadata', () => {
			if (this.streamEngine.active) {
				this.duration = this.streamEngine.activeDuration;
				this.applyPendingStreamSeek(el);
			} else {
				this.duration = el.duration || 0;
				this.applyPendingRecoverySeek(el);
			}
		});
		el.addEventListener('canplay', () => {
			if (this.status === 'error') return;
			if (this.streamEngine.active) this.applyPendingStreamSeek(el);
			else this.applyPendingRecoverySeek(el);
			this.status = el.paused ? 'ready' : 'playing';
			this.duration = this.streamEngine.active
				? this.streamEngine.activeDuration
				: el.duration || this.duration;
			if (this.autoplayPending) {
				this.autoplayPending = false;
				el.play().catch((err) => this.handlePlayRejection(err));
			}
		});
		el.addEventListener('timeupdate', () => {
			if (this.streamEngine.active) {
				this.updateStreamPosition(el.currentTime);
				return;
			}
			if (Math.abs(el.currentTime - this.lastObservedTime) > 0.05) {
				this.lastObservedTime = el.currentTime;
				this.clearStallRecoveryTimer();
				if (this.status === 'buffering') this.status = 'playing';
			}
			this.currentTime = el.currentTime;
		});
		el.addEventListener('play', () => {
			this.streamEndSignaled = false;
			this.callbacks.onPlaybackStarted?.();
			if (this.status !== 'error') this.status = 'playing';
		});
		el.addEventListener('playing', () => {
			this.clearStallRecoveryTimer();
			// Healthy playback resets the stream recovery budget: on a long ride
			// each network blip may recover, as long as audio actually resumes
			// between blips.
			if (this.streamEngine.active) this.recoveryAttempts = 0;
			if (this.status === 'buffering' || this.status === 'loading') this.status = 'playing';
		});
		el.addEventListener('pause', () => {
			this.clearStallRecoveryTimer();
			if (this.status === 'loading') return;
			if (this.status === 'error') return;
			if (el.ended) return;
			this.status = 'paused';
		});
		el.addEventListener('waiting', () => {
			if (this.status === 'playing' || this.status === 'buffering') {
				this.status = 'buffering';
				this.scheduleStallRecovery();
			}
		});
		el.addEventListener('stalled', () => {
			if (this.status === 'playing' || this.status === 'buffering') {
				this.status = 'buffering';
				this.scheduleStallRecovery();
			}
		});
		el.addEventListener('ended', () => {
			this.clearStallRecoveryTimer();
			if (this.streamEngine.active && this.nextStreamTrack({ autoplay: true })) return;
			const reason: StreamEndReason =
				this.streamEngine.active && this.streamEngine.windowed ? 'window-end' : 'normal';
			this.status = 'idle';
			this.currentTime = 0;
			if (!this.streamEndSignaled) {
				this.streamEndSignaled = true;
				this.callbacks.onEnded?.(reason);
			}
		});
		el.addEventListener('error', () => {
			if (this.streamEngine.active) {
				void this.recoverStream('media-error');
				return;
			}
			if (!this.recoverPlayback('media-error')) this.handleMediaError(el.error);
		});
	}

	private urlWithRecovery(url: string, recoveryAttempt: number): string {
		return `${url}${url.includes('?') ? '&' : '?'}recover=${recoveryAttempt}`;
	}

	private scheduleStallRecovery(): void {
		if (this.stallRecoveryTimer || !this.current || !this.audio) return;
		this.stallRecoveryTimer = setTimeout(() => {
			this.stallRecoveryTimer = null;
			if (this.status !== 'buffering') return;
			if (this.streamEngine.active) {
				void this.recoverStream('stall-timeout');
				return;
			}
			if (!this.recoverPlayback('stall-timeout')) {
				this.status = 'error';
				this.error = ERROR_MSG_STALLED;
			}
		}, STALL_RECOVERY_MS);
	}

	private clearStallRecoveryTimer(): void {
		if (!this.stallRecoveryTimer) return;
		clearTimeout(this.stallRecoveryTimer);
		this.stallRecoveryTimer = null;
	}

	private recoverPlayback(reason: 'stall-timeout' | 'media-error'): boolean {
		const target = this.current;
		const el = this.audio;
		if (this.streamEngine.active) return false;
		if (
			!target ||
			!el ||
			!this.currentUrl ||
			el.ended ||
			this.recoveryAttempts >= MAX_RECOVERY_ATTEMPTS
		)
			return false;

		const observedTime = el.currentTime || this.currentTime || this.lastObservedTime;
		if (observedTime < 1) return false;

		const seekTime = Math.max(0, observedTime - RECOVERY_SEEK_BACK_SECONDS);
		this.recoveryAttempts += 1;
		this.pendingRecoverySeek = seekTime;
		this.currentTime = seekTime;
		this.lastObservedTime = seekTime;
		this.status = 'loading';
		this.error = null;
		this.autoplayPending = true;
		this.clearStallRecoveryTimer();

		console.debug('Recovering audio playback', {
			reason,
			attempt: this.recoveryAttempts,
			seekTime,
			generationId: target.generation.id
		});

		el.pause();
		el.src = this.urlWithRecovery(this.currentUrl, this.recoveryAttempts);
		el.load();
		return true;
	}

	private applyPendingRecoverySeek(el: HTMLAudioElement): void {
		if (this.pendingRecoverySeek === null) return;
		const seekTime =
			this.duration > 0
				? Math.min(this.pendingRecoverySeek, this.duration)
				: this.pendingRecoverySeek;
		try {
			el.currentTime = seekTime;
			this.currentTime = seekTime;
			this.lastObservedTime = seekTime;
			this.pendingRecoverySeek = null;
		} catch {
			// Some browsers reject early seeks until more metadata is available.
		}
	}

	private applyPendingStreamSeek(el: HTMLAudioElement): void {
		const seekTime = this.streamEngine.applyPendingSeek(el);
		if (seekTime === null) {
			// Some browsers reject early seeks until stream metadata is available.
			return;
		}
		this.lastObservedTime = seekTime;
		this.updateStreamPosition(seekTime);
	}

	private updateStreamPosition(absoluteTime: number): void {
		const streamState = this.streamEngine.updatePosition(absoluteTime);
		if (!streamState) return;
		this.syncStreamBoundaries();
		if (this.current?.generation.id !== streamState.info.generation.id) {
			this.setCurrent(streamState.info);
		}
		this.duration = streamState.duration;
		this.currentTime = streamState.currentTime;
		this.lastObservedTime = absoluteTime;
		this.clearStallRecoveryTimer();
		if (this.status === 'buffering') this.status = 'playing';
	}

	private syncStreamBoundaries(): void {
		this.streamCanNext = this.streamEngine.canNext;
		this.streamCanPrev = this.streamEngine.canPrev;
	}

	// Stream recovery never falls back to per-track playback: the per-track
	// path is the mode locked phones kill, so reinstating it on a blip would
	// resurrect the exact defect stream mode exists to fix. Recovery is
	// status-aware and stays in-stream.
	private async recoverStream(reason: 'stall-timeout' | 'media-error'): Promise<void> {
		const el = this.audio;
		if (!el || !this.streamEngine.active) return;
		const state = this.streamEngine.fallbackState(this.currentTime, el.currentTime);
		if (!state) return;
		if (this.recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
			this.status = 'error';
			this.error = ERROR_MSG_STALLED;
			return;
		}
		this.recoveryAttempts += 1;
		this.clearStallRecoveryTimer();
		this.status = 'loading';
		this.error = null;
		this.autoplayPending = true;

		const track = state.manifest.tracks[state.trackIndex];
		const absoluteTime = Math.max(
			0,
			(track?.start_offset ?? 0) + state.trackTime - RECOVERY_SEEK_BACK_SECONDS
		);
		const probe = await this.probeUrl(state.manifest.stream_url);
		if (!this.streamEngine.active) return;

		if (probe.status === 401) {
			await this.callbacks.onAuthLost?.();
			return;
		}
		if (probe.status === 404) {
			// Snapshot reaped server-side (TTL) — rebuild it from the manifest's
			// own track list and resume at the same track position.
			const fresh = await this.callbacks.onStreamRebuild?.(state);
			if (fresh && fresh.tracks.length > 0) {
				const currentId = track?.generation_id;
				const matched = fresh.tracks.findIndex((item) => item.generation_id === currentId);
				const index = matched >= 0 ? matched : 0;
				const freshTrack = fresh.tracks[index];
				const trackTime = Math.min(state.trackTime, freshTrack.duration);
				this.loadStream(fresh, index, {
					autoplay: true,
					resumeAt: freshTrack.start_offset + trackTime
				});
				return;
			}
			this.status = 'error';
			this.error = ERROR_MSG_NOT_FOUND;
			return;
		}

		console.debug('Recovering stream playback', {
			reason,
			attempt: this.recoveryAttempts,
			absoluteTime
		});
		this.streamEngine.resumeAt(absoluteTime);
		el.pause();
		const url = state.manifest.stream_url;
		el.src = this.urlWithRecovery(url, this.recoveryAttempts);
		el.load();
	}

	private async probeUrl(url: string): Promise<{ ok: boolean; status: number }> {
		try {
			const resp = await fetch(url, { method: 'HEAD', credentials: 'include' });
			return { ok: resp.ok, status: resp.status };
		} catch {
			return { ok: false, status: 0 };
		}
	}

	private handlePlayRejection(err: unknown): void {
		const name = err instanceof Error ? err.name : '';
		if (name === 'AbortError') return;
		if (name === 'NotAllowedError') {
			this.status = 'paused';
			this.error = 'Autoplay blocked. Click play to start.';
			return;
		}
		this.handleMediaError(this.audio?.error ?? null);
	}

	private async handleMediaError(mediaError: MediaError | null): Promise<void> {
		this.status = 'error';
		this.error = ERROR_MSG_GENERIC;

		const target = this.current;
		const url = this.currentUrl;
		if (!target || !url) return;

		const probe = await this.probeUrl(url);

		if (this.current !== target) return;

		if (probe.status === 401) {
			await this.callbacks.onAuthLost?.();
			return;
		}
		if (probe.status === 404) this.error = ERROR_MSG_NOT_FOUND;
		else if (probe.status === 0) this.error = ERROR_MSG_NETWORK;
		else if (probe.ok && mediaError) this.error = decodeMediaError(mediaError);
	}

	private setCurrent(current: PlaybackInfo | null): void {
		this.current = current;
		this.callbacks.onCurrentChange?.(current);
	}
}

function decodeMediaError(err: MediaError): string {
	switch (err.code) {
		case MediaError.MEDIA_ERR_ABORTED:
			return 'Playback aborted.';
		case MediaError.MEDIA_ERR_NETWORK:
			return ERROR_MSG_NETWORK;
		case MediaError.MEDIA_ERR_DECODE:
			return 'Audio file is corrupted.';
		case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
			return 'Audio format not supported by this browser.';
		default:
			return ERROR_MSG_GENERIC;
	}
}

export const audioPlayer = new AudioPlayer();
