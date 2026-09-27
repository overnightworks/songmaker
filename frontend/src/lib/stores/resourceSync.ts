import { get, writable, type Writable } from 'svelte/store';
import { ApiError, NetworkError, handleSessionLost } from '$lib/api/fetch';
import { fetchMe } from '$lib/api/auth';
import {
	compareDecimalId,
	parseGenerationCreated,
	parseResourceHello,
	parseResourceResync
} from '$lib/api/resourceEvents';
import { fetchSong } from '$lib/api/songs';
import type { GenerationCreatedResourceEvent, SongItem } from '$lib/api/types';
import {
	RESOURCE_EVENT_GENERATION_CREATED,
	EVENT_SOURCE_CLOSED,
	RESOURCE_EVENT_HELLO,
	RESOURCE_EVENT_RESYNC,
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT,
	RESOURCE_SYNC_FETCH_CONCURRENCY,
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_TRACKED_EVENT_LIMIT,
	RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS
} from '$lib/constants';
import { AUTH_ACCOUNT_DISABLED_MESSAGE } from '$lib/constants/auth';
import { cancelLibraryHistoryApply, hydrateLibraryFromHistory } from '$lib/stores/libraryContext';
import {
	applySyncedSong,
	cancelLibraryDataLoads,
	forgetSyncedSong,
	listLoadedSongIds,
	watchLoadedSongIds
} from '$lib/stores/librarySearch';
import { cancelAlbumSongLoads } from '$lib/stores/libraryData';
import { selectedSongId } from '$lib/stores/player';
import { classifyAuthFailure } from '$lib/stores/auth';
import { reportResourceStreamReachable } from '$lib/stores/connectivity';
import { nextReconnectDelayMs, watchReconnectOpportunities } from '$lib/stores/sseReconnect';

// The browser only sends `Last-Event-ID` on its own native retry; the owner
// reopens a dropped stream itself (see `scheduleReconnect`), so it hands the
// server that cursor as a query parameter instead (#1020).
const RESOURCE_EVENT_RESUME_QUERY = 'last_event_id';

type ResourceSyncStatus =
	'disconnected' | 'connecting' | 'bootstrapping' | 'live' | 'reconnecting' | 'error';

type ResourceAuthProbe = 'ok' | 'unauthorized' | 'disabled' | 'retryable';

// A song refresh fails either because the network did not carry it -- the
// offline strip says that, not this owner -- or with a failure worth showing.
type SongRefreshFailure = 'network' | 'shown';

interface ResourceSyncState {
	status: ResourceSyncStatus;
	error: string | null;
	highWaterMark: string | null;
	appliedSequence: string | null;
	ready: boolean;
}

interface ResourceSyncTrackedSizes {
	deferred: number;
	seenGenerationIds: number;
}

interface ResourceEventSource {
	addEventListener(type: string, listener: (event: Event) => void): void;
	removeEventListener(type: string, listener: (event: Event) => void): void;
	close(): void;
	onerror: ((event: Event) => void) | null;
	readonly readyState: number;
}

interface ResourceSyncDeps {
	createEventSource: (url: string) => ResourceEventSource;
	fetchSong: (songId: string) => Promise<SongItem>;
	applySong: (song: SongItem) => void;
	listLoadedSongIds: () => string[];
	listPrioritySongIds: () => string[];
	forgetSong: (songId: string) => void;
	watchLoadedSongs: (onChange: () => void) => () => void;
	loadSnapshot: () => Promise<boolean>;
	cancelSnapshot: () => void;
	probeAuth: () => Promise<ResourceAuthProbe>;
	onUnauthorized: () => Promise<void>;
	reportStreamReachable: (reachable: boolean) => void;
}

const INITIAL: ResourceSyncState = {
	status: 'disconnected',
	error: null,
	highWaterMark: null,
	appliedSequence: null,
	ready: false
};

export const resourceSync = writable<ResourceSyncState>({ ...INITIAL });

export class ResourceSyncController {
	private source: ResourceEventSource | null = null;
	private started = false;
	private epoch = 0;
	private watermark: string | null = null;
	private lastEventId: string | null = null;
	private buffer: GenerationCreatedResourceEvent[] = [];
	private deferred: GenerationCreatedResourceEvent[] = [];
	private readonly pendingSongIds = new Set<string>();
	private readonly refreshesAwaitingBootstrap = new Set<string>();
	private readonly failedSongs = new Map<string, SongRefreshFailure>();
	private readonly queuedGenerationIds = new Set<string>();
	private readonly seenGenerationIds = new Set<string>();
	private readonly songRevisions = new Map<string, number>();
	private flushing: Promise<void> | null = null;
	private readonly readyWaiters: Array<(ok: boolean) => void> = [];
	private stopWatchingOpportunities: (() => void) | null = null;
	private visibilityTimer: ReturnType<typeof setTimeout> | null = null;
	private loadedWatchUnsub: (() => void) | null = null;
	private loadedNotifyQueued = false;
	private syncedOnce = false;
	private bootstrapErrors = 0;
	private probeGeneration = 0;
	private reconnectAttempt = 0;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private failedSongRetryTimer: ReturnType<typeof setTimeout> | null = null;
	private failedSongRetryAttempt = 0;

	constructor(
		private readonly deps: ResourceSyncDeps,
		private readonly store: Writable<ResourceSyncState> = resourceSync
	) {}

	get state(): ResourceSyncState {
		return get(this.store);
	}

	get trackedSizes(): ResourceSyncTrackedSizes {
		return {
			deferred: this.deferred.length,
			seenGenerationIds: this.seenGenerationIds.size
		};
	}

	start(): void {
		if (this.started) return;
		this.started = true;
		this.bootstrapErrors = 0;
		this.stopWatchingOpportunities ??= watchReconnectOpportunities(this.onReconnectOpportunity);
		this.bindLoadedWatch();
		this.setStatus('connecting');
		this.openSource();
	}

	stop(): void {
		this.teardown({ resetStore: true });
	}

	waitForReady(): Promise<boolean> {
		if (!this.started) return Promise.resolve(false);
		if (this.state.status === 'live' || this.syncedOnce) return Promise.resolve(true);
		if (this.state.status === 'error') return Promise.resolve(false);
		return new Promise((resolve) => this.readyWaiters.push(resolve));
	}

	async retry(): Promise<boolean> {
		this.store.update((state) => ({ ...state, error: null }));
		// A retry after teardown (an 'unauthorized' or 'disabled' probe result)
		// finds the owner stopped: start() alone opens the one EventSource it
		// needs. Routing that case into restartConnection() below as well used
		// to open a second connection and immediately close the first.
		if (!this.started) {
			this.start();
			return this.waitForReady();
		}
		if (!this.syncedOnce) {
			this.restartConnection();
			return this.waitForReady();
		}
		this.requeueFailedSongs(this.deps.listPrioritySongIds());
		this.failedSongs.clear();
		await this.flushPending(this.epoch);
		if (!this.started) return false;
		if (this.state.error) return false;
		this.setStatus('live');
		return true;
	}

	/**
	 * A refresh asked for before the stream has bootstrapped waits for that
	 * bootstrap even across a dropped attempt, which abandons the epoch's own
	 * pending songs: a job that ended while the stream was still reconnecting
	 * must still bring its take in once the stream is back (#1032).
	 */
	requestSongRefresh(songId: string): Promise<void> {
		this.invalidateSong(songId);
		if (!this.canFlush()) {
			this.refreshesAwaitingBootstrap.add(songId);
			return Promise.resolve();
		}
		return this.flushPending(this.epoch);
	}

	async handleVisibility(): Promise<void> {
		if (!this.started || !this.syncedOnce) return;
		if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
		this.requeueFailedSongs(this.deps.listPrioritySongIds());
		if (this.pendingSongIds.size === 0) return;
		await this.flushPending(this.epoch);
	}

	private restartConnection(): void {
		this.reconnectAttempt = 0;
		this.restartBootstrap();
	}

	private restartBootstrap(): void {
		this.clearReconnectTimer();
		this.closeSource();
		this.abandonEpoch();
		this.syncedOnce = false;
		this.bootstrapErrors = 0;
		this.invalidateInflightProbes();
		this.store.update((state) => ({
			...state,
			status: 'connecting',
			error: null,
			ready: false
		}));
		this.openSource();
	}

	private openSource(): void {
		const source = this.deps.createEventSource(this.streamUrl());
		this.source = source;
		source.addEventListener(RESOURCE_EVENT_HELLO, this.onHello);
		source.addEventListener(RESOURCE_EVENT_RESYNC, this.onResync);
		source.addEventListener(RESOURCE_EVENT_GENERATION_CREATED, this.onGenerationCreated);
		source.onerror = this.onError;
	}

	private streamUrl(): string {
		if (this.lastEventId === null) return RESOURCE_EVENT_STREAM_PATH;
		const query = new URLSearchParams({ [RESOURCE_EVENT_RESUME_QUERY]: this.lastEventId });
		return `${RESOURCE_EVENT_STREAM_PATH}?${query}`;
	}

	private rememberEventId(event: MessageEvent): void {
		if (event.lastEventId !== '') this.lastEventId = event.lastEventId;
	}

	private closeSource(): void {
		const source = this.source;
		if (!source) return;
		source.removeEventListener(RESOURCE_EVENT_HELLO, this.onHello);
		source.removeEventListener(RESOURCE_EVENT_RESYNC, this.onResync);
		source.removeEventListener(RESOURCE_EVENT_GENERATION_CREATED, this.onGenerationCreated);
		source.onerror = null;
		source.close();
		this.source = null;
	}

	/**
	 * Reconnects after a live (post-bootstrap) drop, or after a first sync that
	 * failed while the server could not be reached -- the offline strip says
	 * "retrying" and offers no button, so that retry must really happen -- with
	 * the same backoff `jobs.ts` uses for its job streams -- an unbounded flat
	 * native EventSource retry here is what produced the operator's ERR_QUIC storm
	 * (issue #257). `reconnectAttempt` resets on the next successful `hello`
	 * (see `handleHello`), so a connection that recovers goes back to the
	 * short delay on its next drop.
	 */
	private scheduleReconnect(reconnect: () => void): void {
		this.reconnectAttempt += 1;
		const delay = nextReconnectDelayMs(this.reconnectAttempt);
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			if (!this.started) return;
			reconnect();
		}, delay);
	}

	private clearReconnectTimer(): void {
		if (this.reconnectTimer === null) return;
		clearTimeout(this.reconnectTimer);
		this.reconnectTimer = null;
	}

	private teardown(options: { resetStore: boolean }): void {
		this.started = false;
		this.clearReconnectTimer();
		this.closeSource();
		this.stopWatchingOpportunities?.();
		this.stopWatchingOpportunities = null;
		this.clearVisibilityTimer();
		this.unbindLoadedWatch();
		this.abandonEpoch();
		this.syncedOnce = false;
		this.bootstrapErrors = 0;
		this.invalidateInflightProbes();
		this.seenGenerationIds.clear();
		this.songRevisions.clear();
		this.refreshesAwaitingBootstrap.clear();
		this.flushing = null;
		this.deps.reportStreamReachable(true);
		if (options.resetStore) this.store.set({ ...INITIAL });
		this.resolveReady(false);
	}

	private abandonEpoch(): void {
		this.epoch += 1;
		this.deps.cancelSnapshot();
		this.buffer = [];
		this.deferred = [];
		this.watermark = null;
		this.lastEventId = null;
		this.pendingSongIds.clear();
		this.failedSongs.clear();
		this.clearFailedSongRetry();
		this.queuedGenerationIds.clear();
	}

	private readonly onHello = (event: Event): void => {
		void this.handleHello(event as MessageEvent);
	};

	private readonly onResync = (event: Event): void => {
		void this.handleResync(event as MessageEvent);
	};

	private readonly onGenerationCreated = (event: Event): void => {
		void this.handleGenerationCreated(event as MessageEvent);
	};

	private readonly onError = (): void => {
		void this.handleStreamError();
	};

	private async handleHello(event: MessageEvent): Promise<void> {
		if (!this.started) return;
		let hello;
		try {
			hello = parseResourceHello(event.data);
		} catch (err) {
			this.failBootstrap(visibleErrorMessage(err));
			return;
		}
		this.reconnectAttempt = 0;
		this.deps.reportStreamReachable(true);
		this.rememberEventId(event);
		this.store.update((state) => ({ ...state, highWaterMark: hello.high_water_mark }));
		this.invalidateInflightProbes();
		if (this.syncedOnce && this.state.status !== 'bootstrapping') {
			await this.recoverLiveConnection();
			return;
		}
		await this.beginEpoch(hello.high_water_mark);
	}

	private async handleResync(event: MessageEvent): Promise<void> {
		if (!this.started) return;
		let resync;
		try {
			resync = parseResourceResync(event.data);
		} catch (err) {
			this.failBootstrap(visibleErrorMessage(err));
			return;
		}
		this.rememberEventId(event);
		this.store.update((state) => ({ ...state, highWaterMark: resync.high_water_mark }));
		this.invalidateInflightProbes();
		this.syncedOnce = false;
		await this.beginEpoch(resync.high_water_mark);
	}

	private async handleGenerationCreated(event: MessageEvent): Promise<void> {
		if (!this.started) return;
		let created: GenerationCreatedResourceEvent;
		try {
			created = parseGenerationCreated(event.data);
		} catch (err) {
			this.showFailure(err);
			return;
		}
		this.advanceSequence(created.sequence);
		this.rememberEventId(event);
		if (this.seenGenerationIds.has(created.generation_id)) return;
		if (!this.canFlush()) {
			if (this.isAfterWatermark(created.sequence)) this.buffer.push(created);
			return;
		}
		this.queueLoadedSong(created);
		await this.flushPending(this.epoch);
	}

	private async handleStreamError(): Promise<void> {
		if (!this.started) return;
		const probeId = ++this.probeGeneration;
		const source = this.source;
		const result = await this.deps.probeAuth();
		if (!this.started || probeId !== this.probeGeneration || this.source !== source) return;
		this.deps.reportStreamReachable(result !== 'retryable');
		// Not a session loss (issue #385 finding 2): the account exists and is still logged in,
		// an admin disabled it, so this must not read as "sign in again" -- that would only fail
		// the same way.
		if (result === 'disabled') {
			this.teardown({ resetStore: false });
			this.setVisibleError(AUTH_ACCOUNT_DISABLED_MESSAGE);
			this.resolveReady(false);
			return;
		}
		if (result === 'unauthorized') {
			this.teardown({ resetStore: false });
			this.setVisibleError(RESOURCE_SYNC_ERROR);
			this.resolveReady(false);
			await this.deps.onUnauthorized();
			return;
		}
		if (!this.syncedOnce) {
			this.bootstrapErrors += 1;
			// A non-200 answer (the edge's 5xx while the server restarts) closes the
			// source for good: the browser will not retry it, so this attempt is over.
			const browserGaveUp = source?.readyState === EVENT_SOURCE_CLOSED;
			if (browserGaveUp || this.bootstrapErrors >= RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT) {
				this.failBootstrap(RESOURCE_SYNC_ERROR);
				if (result === 'retryable') this.scheduleReconnect(() => this.restartBootstrap());
				return;
			}
			this.abandonEpoch();
			this.setStatus('reconnecting');
			return;
		}
		this.closeSource();
		if (this.state.status !== 'error') this.setStatus('reconnecting');
		this.scheduleReconnect(() => this.openSource());
	}

	private async recoverLiveConnection(): Promise<void> {
		this.promoteDeferredSongs();
		this.requeueFailedSongs();
		if (this.pendingSongIds.size > 0) {
			await this.flushPending(this.epoch);
		}
		if (!this.started) return;
		if (this.hasShownSongFailure()) {
			this.setVisibleError(this.state.error || RESOURCE_SYNC_ERROR);
			return;
		}
		this.store.update((state) => ({
			...state,
			status: 'live',
			error: null
		}));
	}

	private async beginEpoch(watermark: string): Promise<void> {
		const epoch = ++this.epoch;
		this.deps.cancelSnapshot();
		this.watermark = watermark;
		this.buffer = this.buffer.filter((event) => this.isAfterWatermark(event.sequence));
		this.deferred = this.deferred.filter((event) => this.isAfterWatermark(event.sequence));
		this.store.update((state) => ({
			...state,
			status: 'bootstrapping',
			error: null,
			highWaterMark: watermark
		}));
		try {
			const ok = await this.deps.loadSnapshot();
			if (!this.isCurrentEpoch(epoch)) return;
			if (!ok) {
				this.failBootstrap(RESOURCE_SYNC_ERROR);
				return;
			}
			while (this.isCurrentEpoch(epoch)) {
				this.queueBufferedSongs();
				this.queueRefreshesAwaitingBootstrap();
				if (this.pendingSongIds.size === 0) break;
				await this.flushPending(epoch, true);
			}
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.failedSongs.size > 0) {
				this.failBootstrap(this.songFailureFallback());
				return;
			}
			this.syncedOnce = true;
			this.bootstrapErrors = 0;
			this.promoteDeferredSongs();
			if (this.pendingSongIds.size > 0) {
				await this.flushPending(epoch, true);
				if (!this.isCurrentEpoch(epoch)) return;
				if (this.failedSongs.size > 0) {
					this.failBootstrap(this.songFailureFallback());
					return;
				}
			}
			this.store.update((state) => ({
				...state,
				status: 'live',
				error: null,
				ready: true
			}));
			this.resolveReady(true);
		} catch (err) {
			if (!this.isCurrentEpoch(epoch)) return;
			this.failBootstrap(visibleErrorMessage(err));
		}
	}

	private queueBufferedSongs(): void {
		const pending = this.buffer
			.filter((event) => this.isAfterWatermark(event.sequence))
			.sort((a, b) => compareDecimalId(a.sequence, b.sequence));
		this.buffer = [];
		for (const event of pending) {
			this.queueLoadedSong(event);
		}
	}

	private queueRefreshesAwaitingBootstrap(): void {
		for (const songId of this.refreshesAwaitingBootstrap) {
			this.invalidateSong(songId);
		}
		this.refreshesAwaitingBootstrap.clear();
	}

	private queueLoadedSong(event: GenerationCreatedResourceEvent): void {
		if (this.seenGenerationIds.has(event.generation_id)) return;
		if (this.queuedGenerationIds.has(event.generation_id)) return;
		if (!this.deps.listLoadedSongIds().includes(event.resource_id)) {
			this.deferEvent(event);
			return;
		}
		this.queuedGenerationIds.add(event.generation_id);
		this.invalidateSong(event.resource_id);
	}

	private deferEvent(event: GenerationCreatedResourceEvent): void {
		if (this.deferred.some((queued) => queued.generation_id === event.generation_id)) return;
		this.deferred.push(event);
		if (this.deferred.length > RESOURCE_SYNC_TRACKED_EVENT_LIMIT) {
			this.deferred.sort((a, b) => compareDecimalId(a.sequence, b.sequence));
			this.deferred = this.deferred.slice(-RESOURCE_SYNC_TRACKED_EVENT_LIMIT);
		}
	}

	private promoteDeferredSongs(): void {
		if (this.deferred.length === 0) return;
		const leftover: GenerationCreatedResourceEvent[] = [];
		const loaded = new Set(this.deps.listLoadedSongIds());
		for (const event of this.deferred) {
			if (this.seenGenerationIds.has(event.generation_id)) continue;
			if (!loaded.has(event.resource_id)) {
				leftover.push(event);
				continue;
			}
			this.queueLoadedSong(event);
		}
		this.deferred = leftover;
	}

	private invalidateSong(songId: string): void {
		this.pendingSongIds.add(songId);
		this.songRevisions.set(songId, (this.songRevisions.get(songId) ?? 0) + 1);
	}

	private canFlush(): boolean {
		return this.started && this.syncedOnce && this.state.status !== 'bootstrapping';
	}

	private async flushPending(epoch: number, force = false): Promise<void> {
		if (!force && !this.canFlush()) return;
		if (this.flushing !== null) {
			await this.flushing;
			if (!this.isCurrentEpoch(epoch) || this.pendingSongIds.size === 0) return;
		}
		const run = this.drainPending(epoch);
		this.flushing = run;
		try {
			await run;
		} finally {
			if (this.flushing === run) this.flushing = null;
		}
	}

	private async drainPending(epoch: number): Promise<void> {
		while (this.isCurrentEpoch(epoch) && this.pendingSongIds.size > 0) {
			const songIds = [...this.pendingSongIds];
			this.pendingSongIds.clear();
			await runLimited(songIds, RESOURCE_SYNC_FETCH_CONCURRENCY, (songId) =>
				this.fetchAndApply(songId, epoch)
			);
		}
	}

	private async fetchAndApply(songId: string, epoch: number): Promise<void> {
		const revision = this.songRevisions.get(songId) ?? 0;
		try {
			const song = await this.deps.fetchSong(songId);
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.songRevisions.get(songId) !== revision) return;
			this.deps.applySong(song);
			this.forgetFailedSong(songId);
			for (const generation of song.generations) {
				this.trackSeenGenerationId(generation.id);
			}
			this.clearLiveErrorIfHealed();
		} catch (err) {
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.songRevisions.get(songId) !== revision) return;
			if (err instanceof ApiError && err.status === 404) {
				this.forgetFailedSong(songId);
				this.deps.forgetSong(songId);
				this.clearLiveErrorIfHealed();
				return;
			}
			this.failedSongs.set(songId, err instanceof NetworkError ? 'network' : 'shown');
			this.showFailure(err);
			this.scheduleFailedSongRetry();
		}
	}

	private forgetFailedSong(songId: string): void {
		this.failedSongs.delete(songId);
		if (this.failedSongs.size === 0) this.failedSongRetryAttempt = 0;
	}

	private hasShownSongFailure(): boolean {
		return [...this.failedSongs.values()].includes('shown');
	}

	/** The bootstrap's own words for failed songs; a network failure has none. */
	private songFailureFallback(): string | null {
		return this.hasShownSongFailure() ? RESOURCE_SYNC_ERROR : null;
	}

	/**
	 * A song refresh that failed while the stream stays up has no stream
	 * drop to piggyback on, and a network that returns without an `online`
	 * event fires nothing either, so the failed songs retry on the stream's
	 * own capped backoff until they land (#1032).
	 */
	private scheduleFailedSongRetry(): void {
		if (this.failedSongRetryTimer !== null) return;
		this.failedSongRetryAttempt += 1;
		this.failedSongRetryTimer = setTimeout(() => {
			this.failedSongRetryTimer = null;
			void this.retryFailedSongs();
		}, nextReconnectDelayMs(this.failedSongRetryAttempt));
	}

	private async retryFailedSongs(): Promise<void> {
		if (!this.canFlush() || this.failedSongs.size === 0) return;
		this.requeueFailedSongs();
		await this.flushPending(this.epoch);
	}

	private requeueFailedSongs(extraIds: readonly string[] = []): void {
		for (const songId of new Set([...this.failedSongs.keys(), ...extraIds])) {
			this.invalidateSong(songId);
		}
	}

	private clearFailedSongRetry(): void {
		this.failedSongRetryAttempt = 0;
		if (this.failedSongRetryTimer === null) return;
		clearTimeout(this.failedSongRetryTimer);
		this.failedSongRetryTimer = null;
	}

	private trackSeenGenerationId(generationId: string): void {
		this.seenGenerationIds.delete(generationId);
		this.seenGenerationIds.add(generationId);
		if (this.seenGenerationIds.size <= RESOURCE_SYNC_TRACKED_EVENT_LIMIT) return;
		const oldest = this.seenGenerationIds.values().next().value;
		if (oldest !== undefined) this.seenGenerationIds.delete(oldest);
	}

	private isAfterWatermark(sequence: string): boolean {
		if (this.watermark === null) return true;
		return compareDecimalId(sequence, this.watermark) > 0;
	}

	private isCurrentEpoch(epoch: number): boolean {
		return this.started && epoch === this.epoch;
	}

	private advanceSequence(sequence: string): void {
		this.store.update((state) => ({
			...state,
			appliedSequence:
				state.appliedSequence === null || compareDecimalId(sequence, state.appliedSequence) > 0
					? sequence
					: state.appliedSequence
		}));
	}

	private failBootstrap(message: string | null): void {
		this.closeSource();
		this.abandonEpoch();
		this.syncedOnce = false;
		this.invalidateInflightProbes();
		this.store.update((state) => ({
			...state,
			status: 'error',
			error: state.error || message,
			ready: false
		}));
		this.resolveReady(false);
	}

	private invalidateInflightProbes(): void {
		this.probeGeneration += 1;
	}

	private showFailure(err: unknown): void {
		const message = visibleErrorMessage(err);
		if (message !== null) this.setVisibleError(message);
	}

	private setVisibleError(message: string): void {
		this.store.update((state) => ({
			...state,
			status: 'error',
			error: message
		}));
	}

	private clearLiveErrorIfHealed(): void {
		if (!this.syncedOnce || this.hasShownSongFailure()) return;
		if (this.state.status !== 'error') return;
		this.store.update((state) => ({
			...state,
			status: 'live',
			error: null
		}));
	}

	private setStatus(status: ResourceSyncStatus): void {
		this.store.update((state) => ({ ...state, status }));
	}

	private resolveReady(ok: boolean): void {
		const waiters = this.readyWaiters.splice(0);
		for (const waiter of waiters) waiter(ok);
	}

	private readonly onReconnectOpportunity = (): void => {
		if (this.bootstrapFailed()) {
			this.restartConnection();
			return;
		}
		this.reconnectNowIfWaiting();
		this.scheduleRevalidation();
	};

	private bootstrapFailed(): boolean {
		return !this.syncedOnce && this.state.status === 'error';
	}

	private reconnectNowIfWaiting(): void {
		if (this.reconnectTimer === null) return;
		this.clearReconnectTimer();
		this.openSource();
	}

	private scheduleRevalidation(): void {
		this.clearVisibilityTimer();
		this.visibilityTimer = setTimeout(() => {
			this.visibilityTimer = null;
			void this.handleVisibility();
		}, RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS);
	}

	private clearVisibilityTimer(): void {
		if (this.visibilityTimer === null) return;
		clearTimeout(this.visibilityTimer);
		this.visibilityTimer = null;
	}

	private bindLoadedWatch(): void {
		if (this.loadedWatchUnsub) return;
		this.loadedWatchUnsub = this.deps.watchLoadedSongs(this.onLoadedSongsChanged);
	}

	private unbindLoadedWatch(): void {
		this.loadedWatchUnsub?.();
		this.loadedWatchUnsub = null;
		this.loadedNotifyQueued = false;
	}

	private readonly onLoadedSongsChanged = (): void => {
		if (this.loadedNotifyQueued) return;
		this.loadedNotifyQueued = true;
		void Promise.resolve().then(() => {
			this.loadedNotifyQueued = false;
			if (!this.started || !this.syncedOnce) return;
			this.promoteDeferredSongs();
			if (this.pendingSongIds.size === 0) return;
			void this.flushPending(this.epoch);
		});
	};
}

async function runLimited<T>(
	items: readonly T[],
	limit: number,
	worker: (item: T) => Promise<void>
): Promise<void> {
	if (items.length === 0) return;
	let next = 0;
	const workers = Math.min(limit, items.length);
	await Promise.all(
		Array.from({ length: workers }, async () => {
			while (next < items.length) {
				const current = next;
				next += 1;
				await worker(items[current]);
			}
		})
	);
}

// A NetworkError is not this owner's to word: the offline strip says it once
// (#1039) while the failed work retries on its own, and its browser text
// ("Failed to fetch") is not copy a musician should read either.
function visibleErrorMessage(err: unknown): string | null {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof NetworkError) return null;
	if (err instanceof Error) return err.message;
	return RESOURCE_SYNC_ERROR;
}

async function probeResourceAuth(): Promise<ResourceAuthProbe> {
	try {
		await fetchMe();
		return 'ok';
	} catch (err) {
		const failure = classifyAuthFailure(err);
		return failure === 'retryable' ? 'retryable' : failure;
	}
}

function cancelLibrarySnapshot(): void {
	cancelLibraryHistoryApply();
	cancelLibraryDataLoads();
	cancelAlbumSongLoads();
}

function librarySyncDeps(): ResourceSyncDeps {
	return {
		createEventSource: (url) => new EventSource(url, { withCredentials: true }),
		fetchSong,
		applySong: applySyncedSong,
		listLoadedSongIds,
		listPrioritySongIds: () => {
			const selected = get(selectedSongId);
			return selected ? [selected] : [];
		},
		forgetSong: forgetSyncedSong,
		watchLoadedSongs: watchLoadedSongIds,
		loadSnapshot: hydrateLibraryFromHistory,
		cancelSnapshot: cancelLibrarySnapshot,
		probeAuth: probeResourceAuth,
		onUnauthorized: handleSessionLost,
		reportStreamReachable: reportResourceStreamReachable
	};
}

let libraryController: ResourceSyncController | null = null;

function libraryOwner(): ResourceSyncController {
	libraryController ??= new ResourceSyncController(librarySyncDeps());
	return libraryController;
}

export function startLibraryResourceSync(): void {
	libraryOwner().start();
}

export function stopLibraryResourceSync(): void {
	libraryController?.stop();
}

export function waitForResourceReady(): Promise<boolean> {
	return libraryOwner().waitForReady();
}

export function retryResourceSync(): Promise<boolean> {
	return libraryOwner().retry();
}

export function requestSongRefresh(songId: string): Promise<void> {
	if (libraryController === null) return Promise.resolve();
	return libraryController.requestSongRefresh(songId);
}

export function resetResourceSyncForTests(): void {
	libraryController?.stop();
	libraryController = null;
	resourceSync.set({ ...INITIAL });
}
