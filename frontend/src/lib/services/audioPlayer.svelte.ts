import type { QueueStreamManifest } from '$lib/api/types';
import type { PlaybackInfo } from './playbackTypes';
import { QueueStreamEngine, type StreamFallbackState } from './queueStreamEngine';

export type { PlaybackInfo } from './playbackTypes';
export type { StreamFallbackState } from './queueStreamEngine';

type PlayerStatus = 'idle' | 'loading' | 'ready' | 'playing' | 'paused' | 'buffering' | 'error';

type StreamEndReason = 'normal' | 'window-end';

type RecoveryReason = 'stall-timeout' | 'frozen-clock' | 'media-error';

type FailureKind = 'stalled' | 'failed' | 'autoplay-blocked';

// 'unreachable' carries no words: the owner's offline strip names the cause.
type Failure = { kind: FailureKind; message: string } | { kind: 'unreachable' };

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
	// Only the owner knows whether its page shows the offline strip; a page
	// without one needs the player's own failure line.
	networkFailureIsAnnounced: () => boolean;
}

const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null,
	networkFailureIsAnnounced: () => false
};

const AUDIO_URL_PREFIX = '/audio/';
const ERROR_MSG_GENERIC = 'Playback failed. Press Retry.';
const ERROR_MSG_NOT_FOUND = 'Audio file not found.';
const ERROR_MSG_STALLED = 'Playback stalled. Press Retry.';
const STALL_RECOVERY_MS = 5000;
const MAX_RECOVERY_ATTEMPTS = 2;
const RECOVERY_SEEK_BACK_SECONDS = 0.75;
// An element can report itself playing while its clock stands still and no
// waiting/stalled event ever fires — silence that pause and play on the same
// element do not cure. The watchdog samples the clock while playing and treats
// this many still samples in a row as a stall.
const PROGRESS_CHECK_MS = 1000;
const STILL_CHECKS_BEFORE_RECOVERY = 4;
// Playback that has played on for as long as a freeze takes to detect has
// recovered; its next freeze is a new one, not a failed recovery.
const STEADY_CHECKS_BEFORE_RECOVERY_BUDGET_RESET = STILL_CHECKS_BEFORE_RECOVERY;

class AudioPlayer {
	status = $state<PlayerStatus>('idle');
	currentTime = $state(0);
	duration = $state(0);
	current = $state<PlaybackInfo | null>(null);
	mode = $state<'classic' | 'stream'>('classic');
	private failure = $state<Failure | null>(null);

	get error(): string | null {
		return this.failure !== null && 'message' in this.failure ? this.failure.message : null;
	}

	private callbacks: AudioPlayerCallbacks = NO_CALLBACKS;
	private audio: HTMLAudioElement | null = null;
	private currentUrl: string | null = null;
	// The next take loads on a second element while the current one plays, so
	// a track change swaps decks instead of fetching from byte 0 — the silent
	// gap in which Android may freeze a page whose screen is off.
	private standby: HTMLAudioElement | null = null;
	private standbyUrl: string | null = null;
	private autoplayPending = false;
	private readonly streamEngine = new QueueStreamEngine();
	private stallRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
	private recoveryAttempts = 0;
	private pendingRecoverySeek: number | null = null;
	private lastObservedTime = 0;
	private progressWatchdog: ReturnType<typeof setInterval> | null = null;
	private lastCheckedTime = 0;
	private stillChecks = 0;
	private steadyChecks = 0;
	private recoveryUrlSerial = 0;
	private pauseRequestedByApp = false;
	private streamEndSignaled = false;
	private streamCanNext = $state(false);
	private streamCanPrev = $state(false);
	private audioGraph: { context: AudioContext; analyser: AnalyserNode } | null = null;

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

	// The Web Audio graph belongs to the <audio> element, not to whatever
	// happens to be drawing a visualizer. An element can be handed to
	// createMediaElementSource exactly once, and closing the context that owns
	// that source routes the element's output into a dead graph for the rest
	// of the session — silent playback that still reports itself as playing.
	// So the player owns the graph for the element's whole life and a bar that
	// comes and goes (the full Now Playing surface unmounts it) only borrows
	// this analyser; it never builds or closes one.
	//
	// Built on first request rather than with the element, so a device that
	// never draws a visualizer never routes its audio through Web Audio at all.
	// Both decks feed the one analyser, each through its own source; only the
	// active deck plays, so the analyser always carries what is heard.
	// Null where there is no element or no Web Audio; a browser that refuses a
	// context throws, and the caller decides whether that is fatal.
	getAnalyser(): AnalyserNode | null {
		if (this.audioGraph) return this.audioGraph.analyser;
		const el = this.audio;
		if (!el || typeof AudioContext === 'undefined') return null;
		const context = new AudioContext();
		try {
			const analyser = context.createAnalyser();
			analyser.connect(context.destination);
			this.audioGraph = { context, analyser };
			this.routeIntoGraph(el);
			if (this.standby) this.routeIntoGraph(this.standby);
			return analyser;
		} catch (e) {
			this.closeAudioGraph();
			throw e;
		}
	}

	private routeIntoGraph(el: HTMLAudioElement): void {
		if (!this.audioGraph) return;
		this.audioGraph.context.createMediaElementSource(el).connect(this.audioGraph.analyser);
	}

	// A context starts suspended until a user gesture, and while it carries
	// the element's output a suspended one is silence.
	resumeAudioGraph(): void {
		if (this.audioGraph?.context.state === 'suspended') void this.audioGraph.context.resume();
	}

	private closeAudioGraph(): void {
		if (!this.audioGraph) return;
		void this.audioGraph.context.close();
		this.audioGraph = null;
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

	// Loads the take a later load() is expected to ask for, replacing whatever
	// stood by; null drops it. Nothing plays and nothing the player shows changes.
	preload(info: PlaybackInfo | null): void {
		if (info === null) {
			this.clearStandby();
			return;
		}
		const url = AUDIO_URL_PREFIX + info.generation.mp3_path;
		if (this.standbyUrl === url) return;
		const el = this.standby ?? this.createStandby();
		this.standbyUrl = url;
		el.src = url;
		el.load();
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

		if (sameGen && this.audio && this.status !== 'error' && !restart) {
			this.setCurrent(info);
			this.currentUrl = url;
			this.failure = null;
			if (autoplay && (this.status !== 'playing' || this.clockStoodStill)) this.play();
			return;
		}

		const readyStandby = this.standbyReadyFor(url);
		if (readyStandby) {
			this.promote(readyStandby, info, url, { autoplay, startAt: opts.startAt });
			return;
		}

		this.clearStandby();
		this.clearStallRecoveryTimer();
		this.recoveryAttempts = 0;
		this.stillChecks = 0;
		this.pendingRecoverySeek = opts.startAt ?? null;
		this.lastObservedTime = 0;
		this.autoplayPending = autoplay;
		const el = this.ensureAudio();
		this.status = 'loading';
		this.pauseElement(el);
		this.setCurrent(info);
		this.currentUrl = url;
		this.failure = null;
		this.currentTime = 0;
		this.duration = 0;
		this.loadSource(el, url);
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
		this.clearStandby();
		const el = this.ensureAudio();
		this.clearStallRecoveryTimer();
		this.recoveryAttempts = 0;
		this.stillChecks = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.mode = 'stream';
		this.autoplayPending = autoplay;
		this.status = 'loading';
		this.pauseElement(el);
		this.setCurrent(streamState.info);
		this.currentUrl = manifest.stream_url;
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
		this.failure = null;
		this.loadSource(el, manifest.stream_url);
		// The start-track seek is applied on loadedmetadata, never eagerly:
		// browsers accept a currentTime assignment before metadata without
		// error, then reset it to 0 when metadata arrives — which silently
		// started every stream at track 1.
	}

	// Never waits for canplay: a deck with future data has already passed it,
	// and on a locked phone the event may not come before the page is frozen.
	private standbyReadyFor(url: string): HTMLAudioElement | null {
		const el = this.standby;
		if (!el || this.standbyUrl !== url) return null;
		return el.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA ? el : null;
	}

	private promote(
		promoted: HTMLAudioElement,
		info: PlaybackInfo,
		url: string,
		opts: { autoplay: boolean; startAt: number | undefined }
	): void {
		const previous = this.audio;
		this.clearStallRecoveryTimer();
		this.stopProgressWatchdog();
		this.audio = promoted;
		this.standby = previous;
		this.standbyUrl = null;
		this.recoveryAttempts = 0;
		this.stillChecks = 0;
		this.pauseRequestedByApp = false;
		this.autoplayPending = false;
		this.pendingRecoverySeek = opts.startAt ?? null;
		this.lastObservedTime = 0;
		this.currentTime = promoted.currentTime;
		this.duration = promoted.duration || 0;
		this.failure = null;
		this.status = 'ready';
		this.setCurrent(info);
		this.currentUrl = url;
		this.applyPendingRecoverySeek(promoted);
		if (opts.autoplay) this.play();
		if (previous) clearDeck(previous);
	}

	private createStandby(): HTMLAudioElement {
		const el = this.createDeck();
		this.standby = el;
		this.routeIntoGraph(el);
		return el;
	}

	private clearStandby(): void {
		this.standbyUrl = null;
		if (this.standby) clearDeck(this.standby);
	}

	// Only a failure the lost network explains goes on by itself: a real
	// failure keeps its words and its Retry (#1161 R2).
	resumeAfterNetworkReturn(): void {
		if (this.failure?.kind === 'unreachable') this.play();
	}

	play(): void {
		if (!this.audio || !this.current) return;
		if (this.status === 'error') {
			this.reloadOnPlay('media-error');
			return;
		}
		if (this.status === 'loading' || this.status === 'buffering') {
			this.autoplayPending = true;
			return;
		}
		if (this.clockStoodStill) {
			this.reloadOnPlay('frozen-clock');
			return;
		}
		this.audio.play().catch((err) => this.handlePlayRejection(err));
	}

	pause(): void {
		if (!this.audio) return;
		this.autoplayPending = false;
		this.clearStallRecoveryTimer();
		this.pauseElement(this.audio);
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
		this.stopProgressWatchdog();
		this.clearStandby();
		if (this.audio) {
			this.pauseElement(this.audio);
			this.audio.src = '';
			this.audio.removeAttribute('src');
		}
		this.status = 'idle';
		this.setCurrent(null);
		this.currentUrl = null;
		this.mode = 'classic';
		this.currentTime = 0;
		this.duration = 0;
		this.failure = null;
		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.recoveryAttempts = 0;
		this.stillChecks = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.streamEndSignaled = false;
	}

	destroy(): void {
		this.streamEndSignaled = false;
		// The graph is bound to these elements for good, so it goes with them.
		this.closeAudioGraph();
		this.clearStandby();
		this.standby = null;
		if (!this.audio) {
			this.streamEngine.clear();
			this.syncStreamBoundaries();
			return;
		}
		this.clearStallRecoveryTimer();
		this.stopProgressWatchdog();
		this.pauseElement(this.audio);
		this.audio.src = '';
		this.audio.removeAttribute('src');
		this.audio = null;
		this.currentUrl = null;
		this.status = 'idle';
		this.setCurrent(null);
		this.mode = 'classic';
		this.currentTime = 0;
		this.duration = 0;
		this.failure = null;
		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.recoveryAttempts = 0;
		this.stillChecks = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
	}

	private ensureAudio(): HTMLAudioElement {
		if (this.audio) return this.audio;
		this.audio = this.createDeck();
		return this.audio;
	}

	private createDeck(): HTMLAudioElement {
		const el = new Audio();
		el.crossOrigin = 'anonymous';
		el.preload = 'auto';
		this.attachListeners(el);
		return el;
	}

	// Every handler acts for the active deck only: the standby loads, and
	// clearing a deck can fire error, without either touching what is shown.
	private attachListeners(el: HTMLAudioElement): void {
		const on = (name: keyof HTMLMediaElementEventMap, handler: () => void): void => {
			el.addEventListener(name, () => {
				if (el === this.audio) handler();
			});
		};

		on('loadstart', () => {
			this.status = 'loading';
			this.failure = null;
		});
		on('loadedmetadata', () => {
			if (this.streamEngine.active) {
				this.duration = this.streamEngine.activeDuration;
				this.applyPendingStreamSeek(el);
			} else {
				this.duration = el.duration || 0;
				this.applyPendingRecoverySeek(el);
			}
		});
		on('canplay', () => {
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
		on('timeupdate', () => {
			if (this.streamEngine.active) {
				this.updateStreamPosition(el.currentTime);
				return;
			}
			if (this.pendingRecoverySeek !== null) return;
			if (Math.abs(el.currentTime - this.lastObservedTime) > 0.05) {
				this.lastObservedTime = el.currentTime;
				this.clearStallRecoveryTimer();
				if (this.status === 'buffering') this.status = 'playing';
			}
			this.currentTime = el.currentTime;
		});
		on('play', () => {
			this.streamEndSignaled = false;
			if (this.status !== 'error') this.status = 'playing';
			this.startProgressWatchdog(el);
		});
		on('playing', () => {
			this.clearStallRecoveryTimer();
			this.startProgressWatchdog(el);
			if (this.gaveUpOnStall) this.resumeAfterGivingUp();
			if (this.status === 'buffering' || this.status === 'loading') this.status = 'playing';
			if (this.status !== 'error') this.callbacks.onPlaybackStarted?.();
		});
		on('pause', () => {
			this.recordPauseSource(el);
			this.clearStallRecoveryTimer();
			this.stopProgressWatchdog();
			if (this.status === 'loading') return;
			if (this.status === 'error') return;
			if (el.ended) return;
			this.status = 'paused';
		});
		on('waiting', () => {
			if (this.status === 'playing' || this.status === 'buffering') {
				this.status = 'buffering';
				this.scheduleStallRecovery();
			}
		});
		on('stalled', () => {
			if (this.status === 'playing' || this.status === 'buffering') {
				this.status = 'buffering';
				this.scheduleStallRecovery();
			}
		});
		on('ended', () => {
			this.clearStallRecoveryTimer();
			this.stopProgressWatchdog();
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
		on('error', () => {
			if (!this.currentUrl) return;
			if (this.streamEngine.active) {
				void this.recoverStream('media-error');
				return;
			}
			if (!this.recoverPlayback('media-error')) this.handleMediaError(el.error);
		});
	}

	// A recovery URL is never reused, not across loads or page reloads either:
	// the browser keeps a take for good, so only a URL it has not seen yet
	// makes it fetch the take again.
	private urlWithRecovery(url: string): string {
		this.recoveryUrlSerial += 1;
		const token = `${Date.now()}-${this.recoveryUrlSerial}`;
		return `${url}${url.includes('?') ? '&' : '?'}recover=${token}`;
	}

	// A download that still grows is a slow network, not a dead one: reloading
	// it would throw its buffer away and fetch the take from byte 0 again.
	private scheduleStallRecovery(): void {
		const el = this.audio;
		if (this.stallRecoveryTimer || !this.current || !el) return;
		const bufferedAtStall = bufferedUntil(el);
		this.stallRecoveryTimer = setTimeout(() => {
			this.stallRecoveryTimer = null;
			if (this.status !== 'buffering' && this.status !== 'loading') return;
			if (bufferedUntil(el) > bufferedAtStall) this.scheduleStallRecovery();
			else this.recoverFromStall('stall-timeout');
		}, STALL_RECOVERY_MS);
	}

	private recoverFromStall(reason: 'stall-timeout' | 'frozen-clock'): void {
		if (this.streamEngine.active) {
			void this.recoverStream(reason);
			return;
		}
		if (!this.recoverPlayback(reason)) this.giveUpOnStall();
	}

	// Pausing the element too keeps the sound and the lock screen in line with
	// the stalled message.
	private giveUpOnStall(): void {
		this.stopProgressWatchdog();
		this.fail('stalled', ERROR_MSG_STALLED);
		if (this.audio) this.pauseElement(this.audio);
	}

	private fail(kind: FailureKind, message: string): void {
		this.status = 'error';
		this.failure = { kind, message };
	}

	private get gaveUpOnStall(): boolean {
		return this.status === 'error' && this.failure?.kind === 'stalled';
	}

	private resumeAfterGivingUp(): void {
		this.status = 'playing';
		this.failure = null;
	}

	private startProgressWatchdog(el: HTMLAudioElement): void {
		if (this.progressWatchdog) return;
		this.lastCheckedTime = el.currentTime;
		this.stillChecks = 0;
		this.steadyChecks = 0;
		this.progressWatchdog = setInterval(() => this.checkProgress(el), PROGRESS_CHECK_MS);
	}

	private stopProgressWatchdog(): void {
		if (!this.progressWatchdog) return;
		clearInterval(this.progressWatchdog);
		this.progressWatchdog = null;
	}

	// Only stillness while the player calls itself playing counts: buffering, a
	// seek and a paused element are expected to stand still.
	private checkProgress(el: HTMLAudioElement): void {
		const clockMoved = el.currentTime !== this.lastCheckedTime;
		this.lastCheckedTime = el.currentTime;
		this.trackSteadyPlayback(clockMoved && this.status === 'playing' && !el.seeking);
		if (clockMoved || this.status !== 'playing' || el.paused || el.seeking) {
			this.stillChecks = 0;
			return;
		}
		this.stillChecks += 1;
		if (this.stillChecks >= STILL_CHECKS_BEFORE_RECOVERY) this.recoverFromStall('frozen-clock');
	}

	private trackSteadyPlayback(playingSteadily: boolean): void {
		this.steadyChecks = playingSteadily ? this.steadyChecks + 1 : 0;
		if (this.steadyChecks >= STEADY_CHECKS_BEFORE_RECOVERY_BUDGET_RESET) this.recoveryAttempts = 0;
	}

	// Survives a pause on purpose: pause and play on an element whose clock
	// stood still leave it silent, so the next play must reload instead.
	private get clockStoodStill(): boolean {
		return this.stillChecks > 0;
	}

	// A play on a broken or silent element fetches the take again rather than
	// resuming what the element holds.
	private reloadOnPlay(reason: 'media-error' | 'frozen-clock'): void {
		this.recoveryAttempts = 0;
		if (this.streamEngine.active) {
			void this.recoverStream(reason);
			return;
		}
		if (this.audio) this.reloadAt(this.reachedPosition(this.audio), reason);
	}

	private pauseElement(el: HTMLAudioElement): void {
		if (!el.paused) this.pauseRequestedByApp = true;
		el.pause();
	}

	// A reload whose data stops arriving is a stall of its own: watching it the
	// way a buffering stall is watched lets it spend the recovery budget and end
	// in Retry instead of loading forever.
	private reloadSource(el: HTMLAudioElement, url: string): void {
		this.pauseElement(el);
		this.loadSource(el, this.urlWithRecovery(url));
		this.scheduleStallRecovery();
	}

	// Loading a source drops the 'pause' event an app pause just queued, so the
	// app's pause marker is settled here instead of by that event.
	private loadSource(el: HTMLAudioElement, url: string): void {
		this.pauseRequestedByApp = false;
		el.src = url;
		el.load();
	}

	// Android pauses the element on its own (audio focus, another app's sound);
	// a debug line per pause tells that apart from the app's own pauses and
	// from the pause a browser fires just before 'ended'.
	private recordPauseSource(el: HTMLAudioElement): void {
		const source = this.pauseSource(el);
		this.pauseRequestedByApp = false;
		console.debug('Audio paused', {
			source,
			status: this.status,
			currentTime: el.currentTime,
			generationId: this.current?.generation.id
		});
	}

	private pauseSource(el: HTMLAudioElement): 'app' | 'ended' | 'outside' {
		if (this.pauseRequestedByApp) return 'app';
		return el.ended ? 'ended' : 'outside';
	}

	private clearStallRecoveryTimer(): void {
		if (!this.stallRecoveryTimer) return;
		clearTimeout(this.stallRecoveryTimer);
		this.stallRecoveryTimer = null;
	}

	private recoverPlayback(reason: RecoveryReason): boolean {
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

		const reachedTime = this.reachedPosition(el);
		if (reachedTime < 1) return false;

		this.recoveryAttempts += 1;
		this.reloadAt(reachedTime, reason);
		return true;
	}

	// A reload restarts the element clock at 0 before its seek lands; until
	// then the player's own position is the one the listener reached.
	private reachedPosition(el: HTMLAudioElement): number {
		return el.currentTime || this.currentTime || this.lastObservedTime;
	}

	private reloadAt(reachedTime: number, reason: RecoveryReason): void {
		const el = this.audio;
		if (!el || !this.current || !this.currentUrl) return;
		const seekTime =
			this.pendingRecoverySeek ?? Math.max(0, reachedTime - RECOVERY_SEEK_BACK_SECONDS);
		this.stillChecks = 0;
		this.pendingRecoverySeek = seekTime;
		this.currentTime = seekTime;
		this.lastObservedTime = seekTime;
		this.status = 'loading';
		this.failure = null;
		this.autoplayPending = true;
		this.clearStallRecoveryTimer();

		console.debug('Recovering audio playback', {
			reason,
			attempt: this.recoveryAttempts,
			seekTime,
			generationId: this.current.generation.id
		});

		this.reloadSource(el, this.currentUrl);
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
	private async recoverStream(reason: RecoveryReason): Promise<void> {
		const el = this.audio;
		if (!el || !this.streamEngine.active) return;
		const state = this.streamEngine.fallbackState(this.currentTime, el.currentTime);
		if (!state) return;
		if (this.recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
			this.giveUpOnStall();
			return;
		}
		this.recoveryAttempts += 1;
		this.stillChecks = 0;
		this.clearStallRecoveryTimer();
		this.status = 'loading';
		this.failure = null;
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
				const index = Math.max(0, matched);
				const freshTrack = fresh.tracks[index];
				const trackTime = Math.min(state.trackTime, freshTrack.duration);
				this.loadStream(fresh, index, {
					autoplay: true,
					resumeAt: freshTrack.start_offset + trackTime
				});
				return;
			}
			this.fail('failed', ERROR_MSG_NOT_FOUND);
			return;
		}

		console.debug('Recovering stream playback', {
			reason,
			attempt: this.recoveryAttempts,
			absoluteTime
		});
		this.streamEngine.resumeAt(absoluteTime);
		this.reloadSource(el, state.manifest.stream_url);
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
			this.failure = {
				kind: 'autoplay-blocked',
				message: 'Autoplay blocked. Press Play to start.'
			};
			return;
		}
		this.handleMediaError(this.audio?.error ?? null);
	}

	private async handleMediaError(mediaError: MediaError | null): Promise<void> {
		this.failForAnUnknownReason();

		const target = this.current;
		const url = this.currentUrl;
		if (!target || !url) return;

		const probe = await this.probeUrl(url);

		if (this.current !== target) return;

		if (probe.status === 401) {
			await this.callbacks.onAuthLost?.();
			return;
		}
		if (probe.status === 404) this.failure = { kind: 'failed', message: ERROR_MSG_NOT_FOUND };
		else if (probe.ok && mediaError && mediaError.code !== MediaError.MEDIA_ERR_NETWORK)
			this.failure = { kind: 'failed', message: decodeMediaError(mediaError) };
		else this.failForAnUnknownReason();
	}

	private failForAnUnknownReason(): void {
		if (this.callbacks.networkFailureIsAnnounced()) {
			this.status = 'error';
			this.failure = { kind: 'unreachable' };
			return;
		}
		this.fail('failed', ERROR_MSG_GENERIC);
	}

	private setCurrent(current: PlaybackInfo | null): void {
		this.current = current;
		this.callbacks.onCurrentChange?.(current);
	}
}

// Emptying src fires error on some browsers; the deck's listeners ignore it
// because a cleared deck is never the active one.
function clearDeck(el: HTMLAudioElement): void {
	el.pause();
	el.src = '';
	el.removeAttribute('src');
}

function bufferedUntil(el: HTMLAudioElement): number {
	const ranges = el.buffered;
	return ranges.length === 0 ? 0 : ranges.end(ranges.length - 1);
}

// A lost network is never decoded here: where the owner's strip names it
// (#1039), the player adds no network wording of its own.
function decodeMediaError(err: MediaError): string {
	switch (err.code) {
		case MediaError.MEDIA_ERR_ABORTED:
			return 'Playback aborted.';
		case MediaError.MEDIA_ERR_DECODE:
			return 'Audio file is corrupted.';
		case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
			return 'Audio format not supported by this browser.';
		default:
			return ERROR_MSG_GENERIC;
	}
}

export const audioPlayer = new AudioPlayer();
