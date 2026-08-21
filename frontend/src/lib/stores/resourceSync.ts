import { get, writable, type Writable } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import {
	openResourceEventStream,
	type GenerationCreatedEvent,
	type ResourceStreamEvent
} from '$lib/api/resourceEvents';
import type { SongItem } from '$lib/api/types';
import {
	RESOURCE_SYNC_ERROR,
	RESOURCE_SYNC_RECONNECT_BASE_MS,
	RESOURCE_SYNC_RECONNECT_MAX_MS
} from '$lib/constants';

export type ResourceSyncPhase =
	| 'idle'
	| 'connecting'
	| 'hello'
	| 'snapshot'
	| 'live'
	| 'error';

export interface ResourceSyncState {
	phase: ResourceSyncPhase;
	error: string | null;
	highWaterMark: number | null;
	appliedSequence: number | null;
}

export interface ResourceSyncDeps {
	openStream: (
		lastEventId: number | null,
		signal: AbortSignal
	) => AsyncGenerator<ResourceStreamEvent>;
	fetchSong: (songId: string) => Promise<SongItem>;
	upsertSong: (song: SongItem) => void;
	loadVisibleLibrary: () => Promise<boolean>;
	getOpenSongId: () => string | null;
	delay?: (ms: number) => Promise<void>;
}

const INITIAL: ResourceSyncState = {
	phase: 'idle',
	error: null,
	highWaterMark: null,
	appliedSequence: null
};

export const resourceSync = writable<ResourceSyncState>({ ...INITIAL });

export class ResourceSyncController {
	private abort: AbortController | null = null;
	private started = false;
	private snapshotToken = 0;
	private buffer: GenerationCreatedEvent[] = [];
	private seenGenerationIds = new Set<string>();
	private readyWaiters: Array<(ok: boolean) => void> = [];
	private reconnectAttempt = 0;
	private visibilityBound = false;
	private loopGeneration = 0;

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
		this.loopGeneration += 1;
		void this.runLoop(this.loopGeneration);
	}

	stop(): void {
		this.started = false;
		this.loopGeneration += 1;
		this.abort?.abort();
		this.abort = null;
		this.unbindVisibility();
		this.snapshotToken += 1;
		this.buffer = [];
		this.seenGenerationIds.clear();
		this.reconnectAttempt = 0;
		this.store.set({ ...INITIAL });
		this.resolveReady(false);
	}

	waitForReady(): Promise<boolean> {
		if (!this.started) this.start();
		const phase = this.state.phase;
		if (phase === 'live') return Promise.resolve(true);
		if (phase === 'error') return Promise.resolve(false);
		return new Promise((resolve) => this.readyWaiters.push(resolve));
	}

	async retry(): Promise<boolean> {
		this.store.update((state) => ({ ...state, error: null }));
		if (this.state.phase === 'live') {
			const libraryOk = await this.deps.loadVisibleLibrary();
			const songOk = await this.revalidateOpenSong();
			if (!libraryOk || !songOk) {
				this.setError(RESOURCE_SYNC_ERROR);
				return false;
			}
			return true;
		}
		this.restartFromScratch();
		return this.waitForReady();
	}

	async handleVisibility(): Promise<void> {
		if (!this.started || this.state.phase !== 'live') return;
		const libraryOk = await this.deps.loadVisibleLibrary();
		const songOk = await this.revalidateOpenSong();
		if (!libraryOk || !songOk) this.setError(RESOURCE_SYNC_ERROR);
	}

	resetForTests(): void {
		this.stop();
	}

	private restartFromScratch(): void {
		this.abort?.abort();
		this.abort = null;
		this.snapshotToken += 1;
		this.buffer = [];
		this.seenGenerationIds.clear();
		this.reconnectAttempt = 0;
		this.store.set({ ...INITIAL, phase: 'connecting' });
		if (!this.started) {
			this.started = true;
			this.bindVisibility();
		}
		this.loopGeneration += 1;
		void this.runLoop(this.loopGeneration);
	}

	private async runLoop(generation: number): Promise<void> {
		while (this.started && generation === this.loopGeneration) {
			this.abort = new AbortController();
			const signal = this.abort.signal;
			const cursor = this.reconnectCursor();
			this.store.update((state) => ({
				...state,
				phase: state.phase === 'live' ? 'live' : 'connecting',
				error: state.phase === 'live' ? state.error : null
			}));
			try {
				for await (const event of this.deps.openStream(cursor, signal)) {
					if (!this.started || signal.aborted || generation !== this.loopGeneration) return;
					await this.handleEvent(event);
				}
				if (!this.started || signal.aborted || generation !== this.loopGeneration) return;
			} catch (err) {
				if (!this.started || signal.aborted || generation !== this.loopGeneration) return;
				if (this.state.phase !== 'live') {
					this.setError(errorMessage(err));
				}
			}
			this.reconnectAttempt += 1;
			await this.waitBackoff(signal);
		}
	}

	private async handleEvent(event: ResourceStreamEvent): Promise<void> {
		if (event.type === 'heartbeat') return;
		if (event.type === 'hello') {
			this.store.update((state) => ({
				...state,
				phase: state.phase === 'live' ? 'live' : 'hello',
				highWaterMark: event.high_water_mark
			}));
			if (this.state.phase !== 'live') {
				void this.runSnapshot();
			}
			return;
		}
		if (event.type === 'resync') {
			this.store.update((state) => ({
				...state,
				highWaterMark: event.high_water_mark,
				appliedSequence: null
			}));
			this.buffer = [];
			void this.runSnapshot();
			return;
		}
		await this.handleGenerationCreated(event);
	}

	private async handleGenerationCreated(event: GenerationCreatedEvent): Promise<void> {
		const helloHwm = this.state.highWaterMark ?? -1;
		const applied = this.state.appliedSequence;
		if (event.sequence <= helloHwm && this.state.phase !== 'live') return;
		if (applied !== null && event.sequence <= applied) return;
		if (this.seenGenerationIds.has(event.generation_id)) return;
		if (this.state.phase === 'live') {
			try {
				await this.applyEvents([event]);
			} catch (err) {
				this.setError(errorMessage(err));
			}
			return;
		}
		this.buffer.push(event);
	}

	private async runSnapshot(): Promise<void> {
		const token = ++this.snapshotToken;
		this.store.update((state) => ({ ...state, phase: 'snapshot', error: null }));
		try {
			const libraryOk = await this.deps.loadVisibleLibrary();
			if (token !== this.snapshotToken || !this.started) return;
			if (!libraryOk) {
				this.failBootstrap(RESOURCE_SYNC_ERROR);
				return;
			}
			const songOk = await this.revalidateOpenSong();
			if (token !== this.snapshotToken || !this.started) return;
			if (!songOk) {
				this.failBootstrap(RESOURCE_SYNC_ERROR);
				return;
			}
			await this.applyEvents(this.drainBuffer());
			if (token !== this.snapshotToken || !this.started) return;
			const hwm = this.state.highWaterMark ?? 0;
			const applied = this.state.appliedSequence;
			this.store.update((state) => ({
				...state,
				phase: 'live',
				error: null,
				appliedSequence: applied === null ? hwm : Math.max(applied, hwm)
			}));
			this.reconnectAttempt = 0;
			this.resolveReady(true);
		} catch (err) {
			if (token !== this.snapshotToken || !this.started) return;
			this.failBootstrap(errorMessage(err));
		}
	}

	private drainBuffer(): GenerationCreatedEvent[] {
		const helloHwm = this.state.highWaterMark ?? -1;
		const pending = this.buffer
			.filter((event) => event.sequence > helloHwm)
			.sort((a, b) => a.sequence - b.sequence);
		this.buffer = [];
		return pending;
	}

	private async applyEvents(events: GenerationCreatedEvent[]): Promise<void> {
		const ordered = [...events].sort((a, b) => a.sequence - b.sequence);
		const unique = new Map<string, GenerationCreatedEvent>();
		for (const event of ordered) {
			if (this.seenGenerationIds.has(event.generation_id)) {
				this.advanceSequence(event.sequence);
				continue;
			}
			unique.set(event.song_id, event);
		}
		for (const event of [...unique.values()].sort((a, b) => a.sequence - b.sequence)) {
			if (this.seenGenerationIds.has(event.generation_id)) {
				this.advanceSequence(event.sequence);
				continue;
			}
			const song = await this.deps.fetchSong(event.song_id);
			this.deps.upsertSong(song);
			this.seenGenerationIds.add(event.generation_id);
			for (const generation of song.generations) {
				this.seenGenerationIds.add(generation.id);
			}
			this.advanceSequence(event.sequence);
		}
	}

	private advanceSequence(sequence: number): void {
		this.store.update((state) => ({
			...state,
			appliedSequence:
				state.appliedSequence === null ? sequence : Math.max(state.appliedSequence, sequence)
		}));
	}

	private async revalidateOpenSong(): Promise<boolean> {
		const songId = this.deps.getOpenSongId();
		if (!songId) return true;
		try {
			const song = await this.deps.fetchSong(songId);
			this.deps.upsertSong(song);
			for (const generation of song.generations) {
				this.seenGenerationIds.add(generation.id);
			}
			return true;
		} catch (err) {
			this.setError(errorMessage(err));
			return false;
		}
	}

	private reconnectCursor(): number | null {
		if (this.state.appliedSequence !== null) return this.state.appliedSequence;
		if (this.state.highWaterMark !== null) return this.state.highWaterMark;
		return null;
	}

	private failBootstrap(message: string): void {
		this.snapshotToken += 1;
		this.store.update((state) => ({
			...state,
			phase: 'error',
			error: state.error || message
		}));
		this.resolveReady(false);
	}

	private setError(message: string): void {
		this.store.update((state) => ({ ...state, error: message }));
	}

	private resolveReady(ok: boolean): void {
		const waiters = this.readyWaiters.splice(0);
		for (const waiter of waiters) waiter(ok);
	}

	private async waitBackoff(signal: AbortSignal): Promise<void> {
		const delayMs = Math.min(
			RESOURCE_SYNC_RECONNECT_MAX_MS,
			RESOURCE_SYNC_RECONNECT_BASE_MS * 2 ** Math.max(0, this.reconnectAttempt - 1)
		);
		if (this.deps.delay) {
			await this.deps.delay(delayMs);
			return;
		}
		await sleep(delayMs, signal);
	}

	private bindVisibility(): void {
		if (this.visibilityBound || typeof window === 'undefined') return;
		this.visibilityBound = true;
		window.addEventListener('visibilitychange', this.onVisibility);
		window.addEventListener('focus', this.onVisibility);
	}

	private unbindVisibility(): void {
		if (!this.visibilityBound || typeof window === 'undefined') return;
		this.visibilityBound = false;
		window.removeEventListener('visibilitychange', this.onVisibility);
		window.removeEventListener('focus', this.onVisibility);
	}

	private onVisibility = (): void => {
		if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
		void this.handleVisibility();
	};
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve) => {
		const timer = setTimeout(resolve, ms);
		signal?.addEventListener(
			'abort',
			() => {
				clearTimeout(timer);
				resolve();
			},
			{ once: true }
		);
	});
}

function errorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return RESOURCE_SYNC_ERROR;
}

export { INITIAL as EMPTY_RESOURCE_SYNC };
