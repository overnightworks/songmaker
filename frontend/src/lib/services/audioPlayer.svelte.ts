import type { QueueStreamManifest } from '$lib/api/types';
import {
	PLAYER_WAITING_FOR_NETWORK,
	TRANSPORT_PAUSE_LABEL,
	TRANSPORT_PLAY_LABEL,
	TRANSPORT_RETRY_LABEL
} from '$lib/constants';
import { ContinuousDeck, TakeNotAppended, type DeckEntry } from './continuousDeck';
import {
	readThePlayingTakeFrom,
	recordPlaybackEvent,
	type PlaybackDiagnosticKind,
	type PlaybackTakeState
} from './playbackDiagnostics';
import type { PlaybackInfo } from './playbackTypes';
import { QueueStreamEngine, type StreamFallbackState } from './queueStreamEngine';

export type { PlaybackInfo } from './playbackTypes';
export type { StreamFallbackState } from './queueStreamEngine';

type PlayerStatus = 'idle' | 'loading' | 'ready' | 'playing' | 'paused' | 'buffering' | 'error';

// What every surface that draws the transport shows. A stalled take that is
// being brought back is 'recovering' and one given up while the offline strip
// names the cause is 'waiting-for-network': the listener asked for sound in
// both, so both offer Pause. A given-up take the listener paused is 'paused'.
export type TransportState =
	'idle' | 'loading' | 'playing' | 'recovering' | 'paused' | 'waiting-for-network' | 'failed';

const TRANSPORT_OFFERING_PAUSE: ReadonlySet<TransportState> = new Set([
	'playing',
	'recovering',
	'waiting-for-network'
]);

export function transportOffersPause(transport: TransportState): boolean {
	return TRANSPORT_OFFERING_PAUSE.has(transport);
}

export function transportButtonLabel(transport: TransportState): string {
	if (transport === 'failed') return TRANSPORT_RETRY_LABEL;
	return transportOffersPause(transport) ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL;
}

const TRANSPORT_OF_SETTLED_STATUS: Readonly<
	Record<Exclude<PlayerStatus, 'loading' | 'error'>, TransportState>
> = {
	idle: 'idle',
	ready: 'paused',
	playing: 'playing',
	paused: 'paused',
	buffering: 'recovering'
};

type StreamEndReason = 'normal' | 'window-end';

type StallReason = 'stall-timeout' | 'frozen-clock' | 'network-return';

type RecoveryReason = StallReason | 'media-error';

// A Play tap on a take that waits for its bytes sends the deck's download on.
type DeckResumeReason = RecoveryReason | 'play';

type RecoveryStep = 'give-up' | 'wait' | 'reload';

// 'awaiting-network' is a stall given up while the network was gone; its
// return retries the take by itself.
type FailureKind = 'stalled' | 'awaiting-network' | 'failed' | 'autoplay-blocked';

// 'unreachable' carries no words: the owner's offline strip names the cause.
type Failure = { kind: FailureKind; message: string } | { kind: 'unreachable' };

type ProbeAnswer = { ok: boolean; status: number };

type LoadOptions = { autoplay?: boolean; restart?: boolean; startAt?: number };

// A queue playing on the continuous deck (#1187): the takes after the current
// one are appended into the same element, so a track change is the playhead
// crossing into the next take, with no ended, no pause and no new source.
// A take is told apart by its PlaybackInfo object, never by its URL: the queue
// hands over one object per place, so one take in two places is two takes.
interface DeckSession {
	deck: ContinuousDeck<PlaybackInfo>;
	// The entry the playhead was last seen in; entering another is a track change.
	playing: Readonly<DeckEntry<PlaybackInfo>> | null;
	// The last take handed to the deck, so that the next take is appended once.
	tail: PlaybackInfo;
}

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
	// Only the owner's queue knows which take follows one the continuous deck
	// could not fetch; an owner that never plays a queue on that deck (a share
	// route) has no answer to give.
	takeAfter?: (take: PlaybackInfo) => PlaybackInfo | null;
	// The continuous deck skips a take it could not fetch while the next one
	// plays; only the owner can tell the listener which take that was.
	onTakeSkipped?: (take: PlaybackInfo) => void;
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
// A deck whose playhead is this close to the end of what it holds, with
// nothing more on its way, has played its last take.
const END_OF_DECK_SLACK_SECONDS = 0.5;
// How often a stalled take is looked at again and, unless the owner reports
// the network gone, reloaded.
const STALL_RECOVERY_MS = 5000;
// How long a stalled take is tried before the player gives up and asks for
// Retry: long enough to ride out a dropout with the screen off (#1187 P3).
const RECOVERY_DEADLINE_MS = 2 * 60 * 1000;
const RECOVERY_SEEK_BACK_SECONDS = 0.75;
// A server that never answers the probe must not hold recovery or the error
// words back for good.
const PROBE_TIMEOUT_MS = 10_000;
// An element can report itself playing while its clock stands still and no
// waiting/stalled event ever fires — silence that pause and play on the same
// element do not cure. The watchdog samples the clock while playing and treats
// this many still samples in a row as a stall.
const PROGRESS_CHECK_MS = 1000;
const STILL_CHECKS_BEFORE_RECOVERY = 4;
// Playback that has played on for as long as a freeze takes to detect has
// recovered; its next freeze is a new one, not a failed recovery.
const STEADY_CHECKS_BEFORE_RECOVERY_ENDS = STILL_CHECKS_BEFORE_RECOVERY;
// Every media event either deck fires, for the diagnostics recorder (#1187).
// timeupdate and progress are left out: they fire several times a second and
// would push a night's evidence out of the recorder's buffer.
const DIAGNOSED_MEDIA_EVENTS: readonly (keyof HTMLMediaElementEventMap)[] = [
	'abort',
	'canplay',
	'canplaythrough',
	'durationchange',
	'emptied',
	'ended',
	'error',
	'loadeddata',
	'loadedmetadata',
	'loadstart',
	'pause',
	'play',
	'playing',
	'ratechange',
	'seeked',
	'seeking',
	'stalled',
	'suspend',
	'volumechange',
	'waiting'
];
const MEDIA_EVENTS_WITH_THEIR_OWN_KIND: ReadonlyMap<string, PlaybackDiagnosticKind> = new Map(
	(['play', 'pause', 'ended', 'waiting', 'stalled', 'error'] as const).map((kind) => [kind, kind])
);

class AudioPlayer {
	status = $state<PlayerStatus>('idle');
	currentTime = $state(0);
	duration = $state(0);
	// Raw, so the take the player holds is the very object it was handed,
	// which is how a queue tells one take's two places apart.
	current = $state.raw<PlaybackInfo | null>(null);
	mode = $state<'classic' | 'stream'>('classic');
	private failure = $state<Failure | null>(null);

	constructor() {
		readThePlayingTakeFrom(() => this.takeStateOf(this.audio));
	}

	get error(): string | null {
		return this.failure !== null && 'message' in this.failure ? this.failure.message : null;
	}

	get transport(): TransportState {
		if (this.status === 'loading')
			return this.recoveryStartedAt === null ? 'loading' : 'recovering';
		if (this.status === 'error') return this.failedTransport;
		return TRANSPORT_OF_SETTLED_STATUS[this.status];
	}

	private get failedTransport(): TransportState {
		if (this.gaveUpOnStall && !this.autoplayPending) return 'paused';
		return this.failure?.kind === 'awaiting-network' ? 'waiting-for-network' : 'failed';
	}

	private callbacks: AudioPlayerCallbacks = NO_CALLBACKS;
	private audio: HTMLAudioElement | null = null;
	private currentUrl: string | null = null;
	// The next take loads on a second element while the current one plays, so
	// a track change swaps decks instead of fetching from byte 0 — the silent
	// gap in which Android may freeze a page whose screen is off.
	private standby: HTMLAudioElement | null = null;
	private standbyUrl: string | null = null;
	private deckSession: DeckSession | null = null;
	private autoplayPending = $state(false);
	private readonly streamEngine = new QueueStreamEngine();
	private stallRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
	private recoveryStartedAt = $state<number | null>(null);
	private pendingRecoverySeek: number | null = null;
	private lastObservedTime = 0;
	private progressWatchdog: ReturnType<typeof setInterval> | null = null;
	private lastCheckedTime = 0;
	private stillChecks = 0;
	private steadyChecks = 0;
	private frozenClockNudged = false;
	private recoveryUrlSerial = 0;
	private streamProbe: Promise<ProbeAnswer> | null = null;
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

	// currentTime as the element's clock gives it this instant rather than at
	// the last timeupdate; on the continuous deck that clock runs across every
	// take, so the current take's start is taken off. Null without an element.
	get currentTimeNow(): number | null {
		return this.audio ? this.positionWithinTake(this.audio) : null;
	}

	// On the continuous deck the element clock runs across every take it holds.
	private positionWithinTake(el: HTMLAudioElement): number {
		return el.currentTime - (this.deckSession?.playing?.start_offset ?? 0);
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

	// Where the browser can append MP3 into one source, a take plays on the
	// continuous deck, and a take that deck already holds is reached by a seek.
	// A take the second deck stands ready with is promoted, as everywhere else.
	load(info: PlaybackInfo, opts: LoadOptions = {}): void {
		const url = audioUrlOf(info);
		if (this.continueCurrentTake(info, url, opts)) return;
		if (this.deckSession && this.seekWithinDeck(this.deckSession, info, url, opts)) return;
		if (!ContinuousDeck.isSupported() || this.standbyReadyFor(url)) {
			this.loadFromUrl(info, url, opts);
			return;
		}
		this.startTake(info, url, opts, (el) => this.attachDeck(el, info, url));
		this.note('fresh_load', 'deck=continuous');
	}

	// Classic per-track playback from a URL the caller already resolved
	// (share routes have no `/audio/{mp3_path}` endpoint of their own — see
	// `docs/architecture.md`'s share section). `load()` is `loadUrl()` with
	// the app's own URL convention plugged in; both funnel through the same
	// resolved-URL state so recovery and the auth probe never have to choose
	// between two URL sources.
	loadUrl(info: PlaybackInfo, url: string, opts: LoadOptions = {}): void {
		this.loadFromUrl(info, url, opts);
	}

	// Readies the take a later load() is expected to ask for: on the continuous
	// deck it is appended behind what plays, otherwise it loads on the second
	// deck, replacing whatever stood by. Nothing plays and nothing the player
	// shows changes. Null drops the second deck's take; the continuous deck
	// keeps what it holds and ends where its takes run out.
	preload(info: PlaybackInfo | null): void {
		if (this.deckSession) {
			if (info) this.appendAhead(this.deckSession, info);
			return;
		}
		if (info === null) {
			this.clearStandby();
			return;
		}
		const url = audioUrlOf(info);
		if (this.standbyUrl === url) return;
		const el = this.standby ?? this.createStandby();
		this.standbyUrl = url;
		el.src = url;
		el.load();
	}

	private loadFromUrl(info: PlaybackInfo, url: string, opts: LoadOptions): void {
		if (this.continueCurrentTake(info, url, opts)) return;

		const standbyFacts = `standby_ready_state=${this.standby?.readyState ?? 'none'} url_matched=${this.standbyUrl === url}`;
		const readyStandby = this.standbyReadyFor(url);
		if (readyStandby) {
			this.promote(readyStandby, info, url, {
				autoplay: opts.autoplay ?? true,
				startAt: opts.startAt
			});
			this.note('promote', standbyFacts);
			return;
		}

		this.startTake(info, url, opts, (el) => this.loadSource(el, url));
		this.note('fresh_load', standbyFacts);
	}

	// A load of the take already playing plays on where it is, unless it is
	// asked to restart; any load leaves a queue stream.
	private continueCurrentTake(info: PlaybackInfo, url: string, opts: LoadOptions): boolean {
		const sameTake =
			!this.streamEngine.active &&
			this.current?.generation.id === info.generation.id &&
			this.currentUrl === url;

		this.streamEngine.clear();
		this.syncStreamBoundaries();
		this.mode = 'classic';

		if (!sameTake || !this.audio || this.status === 'error' || opts.restart) return false;
		this.setCurrent(info);
		this.currentUrl = url;
		this.failure = null;
		if ((opts.autoplay ?? true) && (this.status !== 'playing' || this.clockStoodStill)) this.play();
		return true;
	}

	// A take that starts from nothing on the active element: whatever played or
	// stood by before it is dropped. The source is attached before the take
	// becomes current, so a preload the change asks for lands behind it.
	private startTake(
		info: PlaybackInfo,
		url: string,
		opts: LoadOptions,
		attachSource: (el: HTMLAudioElement) => void
	): void {
		this.clearStandby();
		this.resetTakeState();
		this.pendingRecoverySeek = opts.startAt ?? null;
		this.autoplayPending = opts.autoplay ?? true;
		const el = this.ensureAudio();
		this.status = 'loading';
		this.pauseElement(el);
		this.attachTake(el, info, url, attachSource);
	}

	private attachTake(
		el: HTMLAudioElement,
		info: PlaybackInfo,
		url: string,
		attachSource: (el: HTMLAudioElement) => void
	): void {
		this.currentUrl = url;
		attachSource(el);
		this.setCurrent(info);
		this.scheduleStallRecovery();
	}

	private attachDeck(el: HTMLAudioElement, info: PlaybackInfo, url: string): void {
		this.pauseRequestedByApp = false;
		const session: DeckSession = {
			deck: ContinuousDeck.attach<PlaybackInfo>({
				element: el,
				mediaSource: new MediaSource(),
				urls: URL,
				fetch: (input, init) => fetch(input, init)
			}),
			playing: null,
			tail: info
		};
		this.deckSession = session;
		this.appendToDeck(session, info, url);
	}

	private appendAhead(session: DeckSession, info: PlaybackInfo): void {
		if (session.tail === info) return;
		this.appendToDeck(session, info, audioUrlOf(info));
	}

	private appendToDeck(session: DeckSession, info: PlaybackInfo, url: string): void {
		session.tail = info;
		this.note('media_event', `deck_append take=${info.generation.id}`);
		session.deck.appendTake(info, url).catch((error: unknown) => this.deckFailed(session, error));
	}

	// A load the deck can play on into is a seek: the element keeps its one
	// source. Every other take starts a fresh deck.
	private seekWithinDeck(
		session: DeckSession,
		info: PlaybackInfo,
		url: string,
		opts: LoadOptions
	): boolean {
		const el = this.audio;
		const entry = el && continuableEntry(session, el.currentTime, info);
		if (!el || !entry) return false;
		const startAt = opts.startAt ?? 0;
		session.playing = entry;
		el.currentTime = entry.start_offset + startAt;
		this.currentUrl = url;
		this.currentTime = startAt;
		this.lastObservedTime = startAt;
		this.duration = takeDuration(entry);
		this.setCurrent(info);
		this.note('promote', 'deck_seek');
		if (opts.autoplay ?? true) this.play();
		else this.pause();
		return true;
	}

	// The take under the playhead is the current one: crossing into the next
	// take changes current while the element neither ends nor pauses.
	private followDeckPlayhead(session: DeckSession, el: HTMLAudioElement): number {
		const entry = session.deck.entryAt(el.currentTime);
		if (!entry) return el.currentTime;
		if (entry !== session.playing) this.enterDeckEntry(session, entry);
		this.duration = takeDuration(entry);
		return el.currentTime - entry.start_offset;
	}

	private enterDeckEntry(session: DeckSession, entry: Readonly<DeckEntry<PlaybackInfo>>): void {
		session.playing = entry;
		if (entry.take === this.current) return;
		this.currentUrl = audioUrlOf(entry.take);
		this.setCurrent(entry.take);
		this.note('media_event', 'deck_crossing');
	}

	private deckTakeDuration(el: HTMLAudioElement): number | null {
		const entry = this.deckSession?.deck.entryAt(el.currentTime);
		return entry ? takeDuration(entry) : null;
	}

	// The playhead ran out of audio in the queue's last take: the queue has
	// ended, and only an ended stream lets the element fire ended. Running out
	// while the queue names a next take is buffering, which recovery rides out
	// until that take is appended.
	private endDeckAtItsLastTake(session: DeckSession, el: HTMLAudioElement): boolean {
		if (session.deck.appending || this.queueNamesATakeAfter(session.playing) || !ranOutOfAudio(el))
			return false;
		this.note('media_event', 'deck_end');
		session.deck.endStream().catch((error: unknown) => this.deckFailed(session, error));
		return true;
	}

	private queueNamesATakeAfter(entry: Readonly<DeckEntry<PlaybackInfo>> | null): boolean {
		return entry !== null && (this.callbacks.takeAfter?.(entry.take) ?? null) !== null;
	}

	// A dropped take the playhead has not reached only shortens the stream;
	// anything else the deck cannot play on from goes to the two decks.
	private deckFailed(session: DeckSession, error: unknown): void {
		if (session !== this.deckSession) return;
		if (error instanceof TakeNotAppended && error.take !== this.current) {
			this.note(
				'media_event',
				`deck_dropped take=${error.take.generation.id} ${error.reason} ${error.message}`
			);
			if (error.reason === 'refused') this.skipTake(session, error.take);
			return;
		}
		this.fallBackToTwoDecks(
			error instanceof Error ? error.message : 'the deck failed without an error'
		);
	}

	private skipTake(session: DeckSession, dropped: PlaybackInfo): void {
		this.callbacks.onTakeSkipped?.(dropped);
		this.appendInPlaceOf(session, dropped);
	}

	// The take the queue plays after a dropped one is appended in its place, so
	// the playhead crosses on to it instead of running out where the dropped
	// take would have started.
	private appendInPlaceOf(session: DeckSession, dropped: PlaybackInfo): void {
		if (session.tail !== dropped) return;
		const next = this.callbacks.takeAfter?.(dropped);
		if (next) this.appendAhead(session, next);
	}

	// The current take loads from its own URL where the listener is, and the
	// take after it stands by on the second deck again.
	private fallBackToTwoDecks(reason: string): void {
		const el = this.audio;
		const info = this.current;
		if (!el || !info) return;
		this.note('retry', `deck_fallback ${reason}`);
		this.loadFromUrl(info, audioUrlOf(info), {
			restart: true,
			startAt: this.currentTime,
			autoplay: this.autoplayPending || !el.paused
		});
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
		this.resetTakeState();
		this.mode = 'stream';
		this.autoplayPending = autoplay;
		this.status = 'loading';
		this.pauseElement(el);
		this.setCurrent(streamState.info);
		this.currentUrl = manifest.stream_url;
		this.currentTime = streamState.currentTime;
		this.duration = streamState.duration;
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
		this.resetTakeState();
		this.audio = promoted;
		this.standby = previous;
		this.standbyUrl = null;
		this.pauseRequestedByApp = false;
		this.pendingRecoverySeek = opts.startAt ?? null;
		this.currentTime = promoted.currentTime;
		this.duration = promoted.duration || 0;
		this.status = 'ready';
		this.currentUrl = url;
		this.applyPendingRecoverySeek(promoted);
		if (opts.autoplay) this.play();
		if (previous) clearDeck(previous);
		this.setCurrent(info);
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
	// failure keeps its words and its Retry (#1161 R2). A stalled take that
	// waits for the network tries again at once instead of at its next look,
	// and so does a take ahead whose download parked while the current played.
	resumeAfterNetworkReturn(): void {
		if (this.failure?.kind === 'unreachable') {
			this.play();
			return;
		}
		if (this.failure?.kind === 'awaiting-network') {
			this.retryAfterWaitingForNetwork();
			return;
		}
		if (this.stallRecoveryTimer) {
			this.clearStallRecoveryTimer();
			this.recoverFromStall('network-return');
			return;
		}
		if (this.deckSession) this.resumeDeckDownload(this.deckSession, 'network-return');
	}

	play(): void {
		if (!this.audio || !this.current) return;
		if (this.status === 'error' || this.pausedOnAFailedLoad) {
			this.recoverOnPlay('media-error');
			return;
		}
		if (this.status === 'loading' || this.status === 'buffering') {
			this.autoplayPending = true;
			if (this.deckSession) this.resumeDeckDownload(this.deckSession, 'play');
			return;
		}
		if (this.clockStoodStill) {
			this.recoverOnPlay('frozen-clock');
			return;
		}
		// A take paused while it waited for its bytes still waits for them: its
		// download goes on now, not at the stall's next look (#1288).
		if (this.deckSession?.deck.appending && ranOutOfAudio(this.audio))
			this.resumeDeckDownload(this.deckSession, 'play');
		this.audio.play().catch((err) => this.handlePlayRejection(err));
	}

	pause(): void {
		if (!this.audio) return;
		this.autoplayPending = false;
		this.recoveryStartedAt = null;
		this.clearStallRecoveryTimer();
		this.pauseElement(this.audio);
		if (this.status !== 'error' && !this.audio.ended) this.status = 'paused';
	}

	toggle(): void {
		if (!this.audio || !this.current) return;
		if (transportOffersPause(this.transport)) {
			this.pause();
			return;
		}
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
		this.play();
	}

	seek(seconds: number): void {
		if (!this.audio || this.duration <= 0) return;
		if (this.streamEngine.active) {
			this.streamEngine.seekLocal(this.audio, seconds);
			return;
		}
		const entry = this.deckSession?.playing;
		const reachable = entry ? Math.min(this.duration, entry.duration) : this.duration;
		this.audio.currentTime = (entry?.start_offset ?? 0) + Math.max(0, Math.min(seconds, reachable));
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
		this.resetTakeState();
		this.clearStandby();
		if (this.audio) {
			this.pauseElement(this.audio);
			this.audio.src = '';
			this.audio.removeAttribute('src');
		}
		this.forgetTake();
	}

	destroy(): void {
		this.resetTakeState();
		// The graph is bound to these elements for good, so it goes with them.
		this.closeAudioGraph();
		this.clearStandby();
		this.standby = null;
		if (this.audio) {
			this.pauseElement(this.audio);
			this.audio.src = '';
			this.audio.removeAttribute('src');
			this.audio = null;
		}
		this.forgetTake();
	}

	// What one take's playback and recovery leave behind, cleared so the next
	// take — or none — starts from nothing.
	private resetTakeState(): void {
		this.clearStallRecoveryTimer();
		this.stopProgressWatchdog();
		this.recoveryStartedAt = null;
		this.streamProbe = null;
		this.stillChecks = 0;
		this.frozenClockNudged = false;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.autoplayPending = false;
		this.streamEndSignaled = false;
		this.failure = null;
		this.currentTime = 0;
		this.duration = 0;
		this.leaveDeck();
	}

	// A deck the player leaves is closed, so nothing of it keeps downloading,
	// waiting or reporting a failure.
	private leaveDeck(): void {
		this.deckSession?.deck.close();
		this.deckSession = null;
	}

	private forgetTake(): void {
		this.status = 'idle';
		this.setCurrent(null);
		this.currentUrl = null;
		this.mode = 'classic';
		this.streamEngine.clear();
		this.syncStreamBoundaries();
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
		for (const name of DIAGNOSED_MEDIA_EVENTS)
			el.addEventListener(name, () => this.noteMediaEvent(el, name));
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
				this.duration = this.deckTakeDuration(el) ?? (el.duration || 0);
				this.applyPendingRecoverySeek(el);
			}
		});
		on('canplay', () => {
			// A late answer takes the given-up message back and plays on unless the
			// listener paused; a real failure keeps its message.
			if (this.gaveUpOnStall) this.failure = null;
			else if (this.status === 'error') return;
			this.clearStallRecoveryTimer();
			if (this.streamEngine.active) this.applyPendingStreamSeek(el);
			else this.applyPendingRecoverySeek(el);
			this.status = el.paused ? 'ready' : 'playing';
			this.duration = this.streamEngine.active
				? this.streamEngine.activeDuration
				: (this.deckTakeDuration(el) ?? (el.duration || this.duration));
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
			const position = this.deckSession
				? this.followDeckPlayhead(this.deckSession, el)
				: el.currentTime;
			if (Math.abs(position - this.lastObservedTime) > 0.05) {
				this.lastObservedTime = position;
				this.clearStallRecoveryTimer();
				// A clock that plays on is the late answer even when no canplay or
				// playing event announces it; a seek while paused is not (#1288).
				if (this.gaveUpOnStall && !el.paused) this.resumeAfterGivingUp(el);
				else if (this.status === 'buffering') this.status = 'playing';
			}
			this.currentTime = position;
		});
		on('play', () => {
			this.streamEndSignaled = false;
			if (this.status !== 'error') this.status = 'playing';
			this.startProgressWatchdog(el);
		});
		on('playing', () => {
			this.clearStallRecoveryTimer();
			this.startProgressWatchdog(el);
			if (this.gaveUpOnStall) this.resumeAfterGivingUp(el);
			if (this.status === 'buffering' || this.status === 'loading') this.status = 'playing';
			if (this.status !== 'error') this.callbacks.onPlaybackStarted?.();
		});
		on('pause', () => {
			if (this.gaveUpOnStall && !this.pauseRequestedByApp) this.autoplayPending = false;
			this.pauseRequestedByApp = false;
			this.clearStallRecoveryTimer();
			this.stopProgressWatchdog();
			if (this.status === 'loading') return;
			if (this.status === 'error') return;
			if (el.ended) return;
			this.status = 'paused';
		});
		on('waiting', () => {
			if (this.deckSession && this.endDeckAtItsLastTake(this.deckSession, el)) return;
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
		// A take already given up keeps that state: the late error of its last
		// reload says nothing new.
		on('error', () => {
			if (!this.currentUrl || this.gaveUpOnStall) return;
			if (this.deckSession) {
				this.fallBackToTwoDecks(`media-error ${el.error?.code ?? ''}`);
				return;
			}
			if (this.streamEngine.active) {
				void this.recoverStream('media-error');
				return;
			}
			void this.recoverFromMediaError(el.error);
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

	private recoverFromStall(reason: StallReason): void {
		if (this.streamEngine.active) {
			void this.recoverStream(reason);
			return;
		}
		if (!this.recoverPlayback(reason)) this.giveUpOnStall();
	}

	// The player never pauses itself (#1187 P3): with the screen off a pause is
	// the moment Android may freeze the page. The listener's wish to hear the
	// take outlives the give-up, so a late answer plays on unless the listener
	// pauses in the meantime.
	private giveUpOnStall(): void {
		const listenerWantsSound =
			this.autoplayPending || this.status === 'playing' || this.status === 'buffering';
		this.stopProgressWatchdog();
		this.recoveryStartedAt = null;
		this.fail(
			this.callbacks.networkFailureIsAnnounced()
				? { kind: 'awaiting-network', message: PLAYER_WAITING_FOR_NETWORK }
				: { kind: 'stalled', message: ERROR_MSG_STALLED }
		);
		this.autoplayPending = listenerWantsSound;
		this.note('give_up', this.failure?.kind ?? '');
	}

	// A listener who paused while the take waited is not woken by the network:
	// the take keeps its Retry, now under the plain stalled words.
	private retryAfterWaitingForNetwork(): void {
		if (this.autoplayPending) this.play();
		else this.failure = { kind: 'stalled', message: ERROR_MSG_STALLED };
	}

	// A failed take is no longer watched: only Retry, the network's return
	// after an 'unreachable' or 'awaiting-network' failure, or a late canplay
	// after a given-up stall sets it going again.
	private fail(failure: Failure): void {
		this.clearStallRecoveryTimer();
		this.status = 'error';
		this.failure = failure;
	}

	private get gaveUpOnStall(): boolean {
		const kind = this.failure?.kind;
		return this.status === 'error' && (kind === 'stalled' || kind === 'awaiting-network');
	}

	// The give-up stopped the watchdog; a take that plays again is watched
	// again, even when no play or playing event announces it.
	private resumeAfterGivingUp(el: HTMLAudioElement): void {
		this.status = 'playing';
		this.failure = null;
		this.autoplayPending = false;
		this.startProgressWatchdog(el);
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
		if (this.steadyChecks < STEADY_CHECKS_BEFORE_RECOVERY_ENDS) return;
		this.recoveryStartedAt = null;
		this.frozenClockNudged = false;
	}

	// A recovery reload that failed while the network was gone leaves the
	// element holding no take; the listener's pause hid that failure, so the
	// next play must fetch the take again instead of resuming the element.
	private get pausedOnAFailedLoad(): boolean {
		return this.status === 'paused' && this.audio !== null && this.audio.error !== null;
	}

	// Survives a pause on purpose: pause and play on an element whose clock
	// stood still leave it silent, so the next play must reload instead.
	private get clockStoodStill(): boolean {
		return this.stillChecks > 0;
	}

	// A play on a broken or silent element fetches the take again rather than
	// resuming what the element holds; the deck fetches on from the bytes it
	// received and keeps its one source (#1288). The listener asked for sound,
	// so a deck whose download resumes plays on where the playhead stands.
	private recoverOnPlay(reason: 'media-error' | 'frozen-clock'): void {
		this.recoveryStartedAt = null;
		this.clearStallRecoveryTimer();
		if (this.streamEngine.active) {
			void this.recoverStream(reason);
			return;
		}
		const el = this.audio;
		if (!el) return;
		if (!this.deckSession) this.reloadAt(this.reachedPosition(el), reason);
		else if (!this.recoverOnTheDeck(this.deckSession, el, reason))
			el.play().catch((err) => this.handlePlayRejection(err));
	}

	private pauseElement(el: HTMLAudioElement): void {
		if (!el.paused) this.pauseRequestedByApp = true;
		el.pause();
	}

	// Never pauses the element first: with the screen off a pause is the
	// moment Android may freeze the page, and a new source stops the old one
	// anyway.
	private reloadSource(el: HTMLAudioElement, url: string): void {
		this.stopProgressWatchdog();
		this.leaveDeck();
		this.loadSource(el, this.urlWithRecovery(url));
	}

	// Loading a source drops the 'pause' event an app pause just queued, so the
	// app's pause marker is settled here instead of by that event. A source
	// whose data never arrives — not even its first byte — is watched like a
	// buffering stall, so it ends in Retry instead of loading forever.
	private loadSource(el: HTMLAudioElement, url: string): void {
		this.pauseRequestedByApp = false;
		el.src = url;
		el.load();
		this.scheduleStallRecovery();
	}

	// Registered before the deck's own handlers, so a pause is written down
	// before the 'pause' handler settles the app's pause marker. Android pauses
	// the element on its own (audio focus, another app's sound); the source
	// tells that apart from the app's own pauses and from the pause a browser
	// fires just before 'ended'.
	private noteMediaEvent(el: HTMLAudioElement, name: keyof HTMLMediaElementEventMap): void {
		const facts = [name, `network=${el.networkState}`, `buffered=${bufferedUntil(el).toFixed(1)}`];
		if (name === 'pause' && el === this.audio) facts.push(`source=${this.pauseSource(el)}`);
		this.note(MEDIA_EVENTS_WITH_THEIR_OWN_KIND.get(name) ?? 'media_event', facts.join(' '), el);
	}

	private note(
		kind: PlaybackDiagnosticKind,
		detail: string,
		el: HTMLAudioElement | null = this.audio
	): void {
		recordPlaybackEvent({ kind, detail, take: this.takeStateOf(el) });
	}

	private takeStateOf(el: HTMLAudioElement | null): PlaybackTakeState | null {
		if (el === null) return null;
		const active = el === this.audio;
		return {
			takeId: active ? (this.current?.generation.id ?? null) : null,
			position: active ? this.positionWithinTake(el) : el.currentTime,
			readyState: el.readyState,
			deck: active ? 'active' : 'standby'
		};
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

	// A take that fails part-way through is asked first whether the server
	// still serves it, as a stream is: a lost session or a deleted take is
	// named at once instead of being reloaded until the deadline. While the
	// owner reports the network gone the probe could only fail too. A pause
	// or a failure that lands while the probe is out has the last word.
	private async recoverFromMediaError(mediaError: MediaError | null): Promise<void> {
		const target = this.current;
		const url = this.currentUrl;
		if (
			url &&
			this.audio &&
			this.failedPartWayThrough(this.audio) &&
			!this.callbacks.networkFailureIsAnnounced()
		) {
			const probe = await this.probeUrl(url);
			if (this.current !== target || this.status === 'paused' || this.status === 'error') return;
			if (await this.answeredARefusal(probe)) return;
		}
		if (!this.recoverPlayback('media-error')) await this.handleMediaError(mediaError);
	}

	// An error before the take ever played is the take's own (gone,
	// unreadable): it is probed and named at once, never retried. An error
	// while a stall is being recovered is the stall's, however early it came.
	private failedPartWayThrough(el: HTMLAudioElement): boolean {
		return !el.ended && (this.recoveryStartedAt !== null || this.reachedPosition(el) >= 1);
	}

	private recoverPlayback(reason: RecoveryReason): boolean {
		const el = this.audio;
		if (this.streamEngine.active || !this.current || !el || !this.currentUrl || el.ended)
			return false;
		if (reason === 'media-error' && !this.failedPartWayThrough(el)) return false;
		const reachedTime = this.reachedPosition(el);

		const step = this.nextRecoveryStep(reason);
		if (step === 'give-up') return false;
		if (step === 'wait') this.keepWaiting();
		else if (this.deckSession) this.recoverOnTheDeck(this.deckSession, el, reason);
		else this.reloadAt(reachedTime, reason);
		return true;
	}

	// The deck never swaps its source (#1288): a stall its download explains
	// resumes that download, and a clock frozen over buffered audio is
	// unfrozen in place. Reports whether it set the element going itself.
	private recoverOnTheDeck(
		session: DeckSession,
		el: HTMLAudioElement,
		reason: RecoveryReason
	): boolean {
		if (unfreezesInPlace(reason, el)) {
			this.unfreezeDeckClock(el);
			return true;
		}
		this.resumeDeckDownload(session, reason);
		this.keepWaiting();
		return false;
	}

	// A seek to where the clock stands makes the element read its buffer
	// again. A clock still frozen at the next look gets a fresh deck.
	private unfreezeDeckClock(el: HTMLAudioElement): void {
		if (this.frozenClockNudged) {
			this.reopenDeckAtThePlayhead(el);
			return;
		}
		this.frozenClockNudged = true;
		this.stillChecks = 0;
		const position = el.currentTime;
		this.note('retry', `deck_nudge at=${position.toFixed(1)}`);
		el.currentTime = position;
		el.play().catch((err) => this.handlePlayRejection(err));
	}

	// The queue continues from the fresh deck: the take becomes current again,
	// so its owner hands the take after it. The element is never paused first
	// (see reloadSource), and the recovery deadline runs on.
	private reopenDeckAtThePlayhead(el: HTMLAudioElement): void {
		const info = this.current;
		const url = this.currentUrl;
		if (!info || !url) return;
		const position = this.positionWithinTake(el);
		const recoveryStartedAt = this.recoveryStartedAt;
		this.note('retry', `deck_reopen seek=${position.toFixed(1)}`);
		this.resetTakeState();
		this.recoveryStartedAt = recoveryStartedAt;
		this.pendingRecoverySeek = position;
		this.autoplayPending = true;
		this.status = 'loading';
		this.attachTake(el, info, url, (target) => this.attachDeck(target, info, url));
	}

	// The deck keeps what it holds and its one source: its download picks up
	// from the bytes received, and the playhead plays on where it stood.
	private resumeDeckDownload(session: DeckSession, reason: DeckResumeReason): void {
		this.note('retry', `deck_resume reason=${reason}`);
		session.deck.retryDownload();
	}

	// One deadline for every stalled take. While the owner reports the network
	// gone a reload would only fail, so none is spent: the take waits and the
	// network's return tries again at once. A failed reload reports its error
	// straight away; answering each with another reload would spin, so the
	// watch that already runs decides when the next one goes out.
	private nextRecoveryStep(reason: RecoveryReason): RecoveryStep {
		this.recoveryStartedAt ??= Date.now();
		if (Date.now() - this.recoveryStartedAt >= RECOVERY_DEADLINE_MS) return 'give-up';
		const aStallIsWatched = reason === 'media-error' && this.stallRecoveryTimer !== null;
		if (aStallIsWatched || this.callbacks.networkFailureIsAnnounced()) return 'wait';
		return 'reload';
	}

	private keepWaiting(): void {
		if (this.status !== 'loading') this.status = 'buffering';
		this.failure = null;
		this.scheduleStallRecovery();
	}

	// A reload restarts the element clock at 0 before its seek lands; until
	// then the player's own position is the one the listener reached.
	// On the deck the element clock runs across every take; the player's own
	// position is the one within the current take.
	private reachedPosition(el: HTMLAudioElement): number {
		const elementPosition = this.deckSession ? 0 : el.currentTime;
		return elementPosition || this.currentTime || this.lastObservedTime;
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

		this.note('retry', `reason=${reason} seek=${seekTime.toFixed(1)}`);
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
	// While a probe is out, whatever else asks for recovery — the element's
	// error, the network's return — is answered by that probe's reload. A
	// pause, a failure or another take that lands while the probe or the
	// rebuild is out has the last word.
	private async recoverStream(reason: RecoveryReason): Promise<void> {
		const el = this.audio;
		if (!el || !this.streamEngine.active || this.streamProbe !== null) return;
		const target = this.current;
		const state = this.streamEngine.fallbackState(this.currentTime, el.currentTime);
		if (!state) return;
		const step = this.nextRecoveryStep(reason);
		if (step === 'give-up') {
			this.giveUpOnStall();
			return;
		}
		if (step === 'wait') {
			this.keepWaiting();
			return;
		}
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
		const probe = await this.probeStream(state.manifest.stream_url);
		if (probe === null || this.streamRecoveryInterrupted(target)) return;

		if (probe.status === 404) {
			// Snapshot reaped server-side (TTL) — rebuild it from the manifest's
			// own track list and resume at the same track position.
			const fresh = await this.callbacks.onStreamRebuild?.(state);
			if (this.streamRecoveryInterrupted(target)) return;
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
		}
		if (await this.answeredARefusal(probe)) return;

		this.note('retry', `reason=${reason} stream_at=${absoluteTime.toFixed(1)}`);
		this.streamEngine.resumeAt(absoluteTime);
		this.reloadSource(el, state.manifest.stream_url);
	}

	private streamRecoveryInterrupted(target: PlaybackInfo | null): boolean {
		return this.current !== target || this.status !== 'loading';
	}

	// Null when the take changed while the probe was out: its answer is stale.
	private async probeStream(url: string): Promise<ProbeAnswer | null> {
		const probe = this.probeUrl(url);
		this.streamProbe = probe;
		const answer = await probe;
		if (this.streamProbe !== probe) return null;
		this.streamProbe = null;
		return answer;
	}

	private async probeUrl(url: string): Promise<ProbeAnswer> {
		try {
			const resp = await fetch(url, {
				method: 'HEAD',
				credentials: 'include',
				signal: AbortSignal.timeout(PROBE_TIMEOUT_MS)
			});
			return { ok: resp.ok, status: resp.status };
		} catch {
			return { ok: false, status: 0 };
		}
	}

	private handlePlayRejection(err: unknown): void {
		const name = err instanceof Error ? err.name : '';
		this.note('play_rejected', name);
		if (name === 'AbortError') return;
		if (name === 'NotAllowedError') {
			this.status = 'paused';
			this.failure = {
				kind: 'autoplay-blocked',
				message: 'Autoplay blocked. Press Play to start.'
			};
			return;
		}
		void this.handleMediaError(this.audio?.error ?? null);
	}

	private async handleMediaError(mediaError: MediaError | null): Promise<void> {
		this.failForAnUnknownReason();

		const target = this.current;
		const url = this.currentUrl;
		if (!target || !url) return;

		const probe = await this.probeUrl(url);

		if (this.current !== target) return;

		if (await this.answeredARefusal(probe)) return;
		if (probe.ok && mediaError && mediaError.code !== MediaError.MEDIA_ERR_NETWORK)
			this.failure = { kind: 'failed', message: decodeMediaError(mediaError) };
		else this.failForAnUnknownReason();
	}

	// A lost session goes to sign-in; a take the server no longer has says so.
	private async answeredARefusal(probe: ProbeAnswer): Promise<boolean> {
		if (probe.status === 401) {
			this.failForAnUnknownReason();
			await this.callbacks.onAuthLost?.();
			return true;
		}
		if (probe.status === 404) {
			this.fail({ kind: 'failed', message: ERROR_MSG_NOT_FOUND });
			return true;
		}
		return false;
	}

	private failForAnUnknownReason(): void {
		this.fail(
			this.callbacks.networkFailureIsAnnounced()
				? { kind: 'unreachable' }
				: { kind: 'failed', message: ERROR_MSG_GENERIC }
		);
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

// The one place a take's URL is spelled: preload() and load() must agree on it
// exactly, or a standby deck is never promoted.
function audioUrlOf(info: PlaybackInfo): string {
	return AUDIO_URL_PREFIX + info.generation.mp3_path;
}

// The take's own length, not the stretch of it appended so far.
function takeDuration(entry: Readonly<DeckEntry<PlaybackInfo>>): number {
	return entry.take.generation.audio_duration_sec ?? entry.duration;
}

// The deck only ever receives the take the queue plays after the current one,
// so the take handed to it last, directly behind the playhead's entry, is
// the queue's next take whoever asked for it; the playing take itself is
// still reached from its start. Anything else it holds may be stale.
function continuableEntry(
	session: DeckSession,
	playhead: number,
	take: PlaybackInfo
): Readonly<DeckEntry<PlaybackInfo>> | undefined {
	const { deck } = session;
	const playing = deck.entryAt(playhead);
	if (!playing) return undefined;
	const handedLast = deck.manifest.at(-1);
	const next =
		handedLast?.take === session.tail && deck.manifest.at(-2) === playing ? handedLast : undefined;
	return [playing, next].find(
		(entry) => entry !== undefined && entry.take === take && deck.isPlayableFromStart(entry)
	);
}

function bufferedUntil(el: HTMLAudioElement): number {
	const ranges = el.buffered;
	return ranges.length === 0 ? 0 : ranges.end(ranges.length - 1);
}

// The playhead stands at the end of what the element holds.
function ranOutOfAudio(el: HTMLAudioElement): boolean {
	return bufferedUntil(el) - el.currentTime <= END_OF_DECK_SLACK_SECONDS;
}

// A clock frozen over audio the deck already holds is the element's own
// fault, not the download's: it is unfrozen in place.
function unfreezesInPlace(reason: RecoveryReason, el: HTMLAudioElement): boolean {
	return reason === 'frozen-clock' && bufferedUntil(el) > el.currentTime;
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
