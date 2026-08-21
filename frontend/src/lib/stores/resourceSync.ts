import { get, writable, type Writable } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
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
	RESOURCE_EVENT_HELLO,
	RESOURCE_EVENT_RESYNC,
	RESOURCE_EVENT_STREAM_PATH,
	RESOURCE_SYNC_ERROR
} from '$lib/constants';
import { cancelLibraryHistoryApply, hydrateLibraryFromHistory } from '$lib/stores/libraryContext';
import {
	applySyncedSong,
	cancelLibraryDataLoads,
	listLoadedSongIds
} from '$lib/stores/librarySearch';
import { clearAuth } from '$lib/stores/auth';

export type ResourceSyncStatus =
	| 'disconnected'
	| 'connecting'
	| 'bootstrapping'
	| 'live'
	| 'reconnecting'
	| 'error';

export type ResourceAuthProbe = 'ok' | 'unauthorized' | 'retryable';

export interface ResourceSyncState {
	status: ResourceSyncStatus;
	error: string | null;
	highWaterMark: string | null;
	appliedSequence: string | null;
	ready: boolean;
}

export interface ResourceEventSource {
	addEventListener(type: string, listener: (event: Event) => void): void;
	removeEventListener(type: string, listener: (event: Event) => void): void;
	close(): void;
	onerror: ((event: Event) => void) | null;
}

export interface ResourceSyncDeps {
	createEventSource: (url: string) => ResourceEventSource;
	fetchSong: (songId: string) => Promise<SongItem>;
	applySong: (song: SongItem) => void;
	listLoadedSongIds: () => string[];
	loadSnapshot: () => Promise<boolean>;
	cancelSnapshot: () => void;
	probeAuth: () => Promise<ResourceAuthProbe>;
	onUnauthorized: () => Promise<void>;
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
	private buffer: GenerationCreatedResourceEvent[] = [];
	private pendingSongIds = new Set<string>();
	private failedSongIds = new Set<string>();
	private queuedGenerationIds = new Set<string>();
	private seenGenerationIds = new Set<string>();
	private songRevisions = new Map<string, number>();
	private flushing: Promise<void> | null = null;
	private readyWaiters: Array<(ok: boolean) => void> = [];
	private visibilityBound = false;
	private syncedOnce = false;

	constructor(
		private readonly deps: ResourceSyncDeps,
		private readonly store: Writable<ResourceSyncState> = resourceSync
	) {}

	get state(): ResourceSyncState {
		return get(this.store);
	}

	start(): void {
		if (this.started) return;
		this.started = true;
		this.bindVisibility();
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
		if (!this.started) this.start();
		this.store.update((state) => ({ ...state, error: null }));
		if (!this.syncedOnce) {
			this.restartConnection();
			return this.waitForReady();
		}
		const retryIds = new Set([...this.failedSongIds, ...this.deps.listLoadedSongIds()]);
		this.failedSongIds.clear();
		for (const songId of retryIds) {
			this.invalidateSong(songId);
		}
		await this.flushPending(this.epoch);
		if (!this.started) return false;
		if (this.state.error) return false;
		this.setStatus('live');
		return true;
	}

	requestSongRefresh(songId: string): Promise<void> {
		this.invalidateSong(songId);
		if (!this.canFlush()) return Promise.resolve();
		return this.flushPending(this.epoch);
	}

	async handleVisibility(): Promise<void> {
		if (!this.started || !this.syncedOnce) return;
		if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
		for (const songId of this.deps.listLoadedSongIds()) {
			this.invalidateSong(songId);
		}
		await this.flushPending(this.epoch);
	}

	private restartConnection(): void {
		this.closeSource();
		this.abandonEpoch();
		this.syncedOnce = false;
		this.store.update((state) => ({
			...state,
			status: 'connecting',
			error: null,
			ready: false
		}));
		this.openSource();
	}

	private openSource(): void {
		const source = this.deps.createEventSource(RESOURCE_EVENT_STREAM_PATH);
		this.source = source;
		source.addEventListener(RESOURCE_EVENT_HELLO, this.onHello);
		source.addEventListener(RESOURCE_EVENT_RESYNC, this.onResync);
		source.addEventListener(RESOURCE_EVENT_GENERATION_CREATED, this.onGenerationCreated);
		source.onerror = this.onError;
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

	private teardown(options: { resetStore: boolean }): void {
		this.started = false;
		this.closeSource();
		this.unbindVisibility();
		this.abandonEpoch();
		this.syncedOnce = false;
		this.seenGenerationIds.clear();
		this.songRevisions.clear();
		this.flushing = null;
		if (options.resetStore) this.store.set({ ...INITIAL });
		this.resolveReady(false);
	}

	private abandonEpoch(): void {
		this.epoch += 1;
		this.deps.cancelSnapshot();
		this.buffer = [];
		this.watermark = null;
		this.pendingSongIds.clear();
		this.failedSongIds.clear();
		this.queuedGenerationIds.clear();
	}

	private onHello = (event: Event): void => {
		void this.handleHello(event as MessageEvent);
	};

	private onResync = (event: Event): void => {
		void this.handleResync(event as MessageEvent);
	};

	private onGenerationCreated = (event: Event): void => {
		void this.handleGenerationCreated(event as MessageEvent);
	};

	private onError = (): void => {
		void this.handleStreamError();
	};

	private async handleHello(event: MessageEvent): Promise<void> {
		if (!this.started) return;
		let hello;
		try {
			hello = parseResourceHello(event.data);
		} catch (err) {
			this.failBootstrap(errorMessage(err));
			return;
		}
		this.store.update((state) => ({ ...state, highWaterMark: hello.high_water_mark }));
		if (this.syncedOnce && this.state.status !== 'bootstrapping') {
			if (this.state.status === 'reconnecting' || this.state.status === 'connecting') {
				this.setStatus('live');
			}
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
			this.failBootstrap(errorMessage(err));
			return;
		}
		this.store.update((state) => ({ ...state, highWaterMark: resync.high_water_mark }));
		this.syncedOnce = false;
		await this.beginEpoch(resync.high_water_mark);
	}

	private async handleGenerationCreated(event: MessageEvent): Promise<void> {
		if (!this.started) return;
		let created: GenerationCreatedResourceEvent;
		try {
			created = parseGenerationCreated(event.data);
		} catch (err) {
			this.setVisibleError(errorMessage(err));
			return;
		}
		this.advanceSequence(created.sequence);
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
		const result = await this.deps.probeAuth();
		if (!this.started) return;
		if (result === 'unauthorized') {
			this.teardown({ resetStore: false });
			this.setVisibleError(RESOURCE_SYNC_ERROR);
			this.resolveReady(false);
			await this.deps.onUnauthorized();
			return;
		}
		if (!this.syncedOnce) {
			this.abandonEpoch();
			this.setStatus('reconnecting');
			return;
		}
		this.setStatus('reconnecting');
	}

	private async beginEpoch(watermark: string): Promise<void> {
		const epoch = ++this.epoch;
		this.deps.cancelSnapshot();
		this.watermark = watermark;
		this.buffer = this.buffer.filter((event) => this.isAfterWatermark(event.sequence));
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
				if (this.pendingSongIds.size === 0) break;
				await this.flushPending(epoch, true);
			}
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.failedSongIds.size > 0) {
				this.failBootstrap(this.state.error || RESOURCE_SYNC_ERROR);
				return;
			}
			this.syncedOnce = true;
			this.store.update((state) => ({
				...state,
				status: 'live',
				error: null,
				ready: true
			}));
			this.resolveReady(true);
		} catch (err) {
			if (!this.isCurrentEpoch(epoch)) return;
			this.failBootstrap(errorMessage(err));
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

	private queueLoadedSong(event: GenerationCreatedResourceEvent): void {
		if (this.seenGenerationIds.has(event.generation_id)) return;
		if (this.queuedGenerationIds.has(event.generation_id)) return;
		if (!this.deps.listLoadedSongIds().includes(event.resource_id)) return;
		this.queuedGenerationIds.add(event.generation_id);
		this.invalidateSong(event.resource_id);
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
		if (this.flushing) {
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
			await Promise.all(songIds.map((songId) => this.fetchAndApply(songId, epoch)));
		}
	}

	private async fetchAndApply(songId: string, epoch: number): Promise<void> {
		const revision = this.songRevisions.get(songId) ?? 0;
		try {
			const song = await this.deps.fetchSong(songId);
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.songRevisions.get(songId) !== revision) return;
			this.deps.applySong(song);
			this.failedSongIds.delete(songId);
			for (const generation of song.generations) {
				this.seenGenerationIds.add(generation.id);
			}
		} catch (err) {
			if (!this.isCurrentEpoch(epoch)) return;
			if (this.songRevisions.get(songId) !== revision) return;
			this.failedSongIds.add(songId);
			this.setVisibleError(errorMessage(err));
		}
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

	private failBootstrap(message: string): void {
		this.abandonEpoch();
		this.syncedOnce = false;
		this.store.update((state) => ({
			...state,
			status: 'error',
			error: state.error || message,
			ready: false
		}));
		this.resolveReady(false);
	}

	private setVisibleError(message: string): void {
		this.store.update((state) => ({
			...state,
			status: 'error',
			error: message
		}));
	}

	private setStatus(status: ResourceSyncStatus): void {
		this.store.update((state) => ({ ...state, status }));
	}

	private resolveReady(ok: boolean): void {
		const waiters = this.readyWaiters.splice(0);
		for (const waiter of waiters) waiter(ok);
	}

	private bindVisibility(): void {
		if (this.visibilityBound || typeof window === 'undefined') return;
		this.visibilityBound = true;
		window.addEventListener('focus', this.onVisibility);
		window.addEventListener('visibilitychange', this.onVisibility);
	}

	private unbindVisibility(): void {
		if (!this.visibilityBound || typeof window === 'undefined') return;
		this.visibilityBound = false;
		window.removeEventListener('focus', this.onVisibility);
		window.removeEventListener('visibilitychange', this.onVisibility);
	}

	private onVisibility = (): void => {
		void this.handleVisibility();
	};
}

function errorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return RESOURCE_SYNC_ERROR;
}

export async function probeResourceAuth(): Promise<ResourceAuthProbe> {
	try {
		await fetchMe();
		return 'ok';
	} catch (err) {
		if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
			return 'unauthorized';
		}
		return 'retryable';
	}
}

async function redirectToLogin(): Promise<void> {
	clearAuth();
	const { goto } = await import('$app/navigation');
	await goto('/login');
}

function cancelLibrarySnapshot(): void {
	cancelLibraryHistoryApply();
	cancelLibraryDataLoads();
}

function librarySyncDeps(): ResourceSyncDeps {
	return {
		createEventSource: (url) => new EventSource(url, { withCredentials: true }),
		fetchSong,
		applySong: applySyncedSong,
		listLoadedSongIds,
		loadSnapshot: hydrateLibraryFromHistory,
		cancelSnapshot: cancelLibrarySnapshot,
		probeAuth: probeResourceAuth,
		onUnauthorized: redirectToLogin
	};
}

let libraryController: ResourceSyncController | null = null;

function libraryOwner(): ResourceSyncController {
	if (libraryController === null) {
		libraryController = new ResourceSyncController(librarySyncDeps());
	}
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

export { INITIAL as EMPTY_RESOURCE_SYNC };
