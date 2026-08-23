// The share route's playback owner: drives the shared audioPlayer singleton
// for one mounted share collection. Never imports stores/player, navigation,
// editor, takeActions, or auth — see share-import-boundary.test.ts, which
// enforces that boundary for every file under lib/share and
// lib/components/share.

import type { QueueStreamManifest, QueueStreamTrackItem } from '$lib/api/types';
import {
	audioPlayer,
	type AudioPlayerCallbacks,
	type PlaybackInfo
} from '$lib/services/audioPlayer.svelte';
import { queuePlaybackMode, shouldUseQueueStream } from '$lib/stores/playbackSettings';
import { get } from 'svelte/store';
import {
	playableTracks,
	trackPlaybackInfo,
	type SharedCollectionView,
	type SharedTrack
} from './sharedCollection';
import type { QueueRowItem, QueueViewModel } from '$lib/stores/player';

export type ShareStreamFetcher = () => Promise<QueueStreamManifest>;

const STREAM_REFRESH_MARGIN_MS = 60_000;

const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null
};

function shuffleKeepingFirst(tracks: SharedTrack[], anchor: SharedTrack | null): SharedTrack[] {
	if (tracks.length <= 1) return [...tracks];
	const rest = anchor ? tracks.filter((t) => t.key !== anchor.key) : [...tracks];
	for (let i = rest.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[rest[i], rest[j]] = [rest[j], rest[i]];
	}
	return anchor ? [anchor, ...rest] : rest;
}

export class SharePlayback {
	shuffle = $state(false);
	windowEnded = $state(false);

	private collection: SharedCollectionView | null = null;
	private baseTracks: SharedTrack[] = [];
	private playOrder: SharedTrack[] = $state([]);
	private activeIndex = $state(-1);
	private manifest: QueueStreamManifest | null = $state(null);
	private fetchStream: ShareStreamFetcher | null = null;
	private previousCallbacks: AudioPlayerCallbacks = NO_CALLBACKS;

	readonly currentTrack = $derived(
		this.activeIndex >= 0 ? (this.playOrder[this.activeIndex] ?? null) : null
	);

	readonly canNext = $derived(
		audioPlayer.mode === 'stream' ? audioPlayer.canNextStreamTrack : this.playOrder.length > 1
	);

	readonly canPrev = $derived(
		audioPlayer.mode === 'stream' ? audioPlayer.canPrevStreamTrack : this.playOrder.length > 1
	);

	readonly queueRows = $derived.by((): QueueRowItem[] =>
		this.playOrder.map((track) => {
			const streamTrack = this.streamTrackFor(track);
			return {
				key: track.key,
				songId: track.key,
				songTitle: track.title,
				generationId: track.key,
				durationSec: streamTrack?.duration ?? null,
				versionNumber: null,
				generationNumber: 1
			};
		})
	);

	readonly queue = $derived.by((): QueueViewModel => {
		const items = this.queueRows;
		const currentIndex = this.activeIndex;
		const upNext =
			items.length > 1 && currentIndex >= 0
				? (items[(currentIndex + 1) % items.length] ?? null)
				: null;
		return { items, currentIndex, upNext };
	});

	start(collection: SharedCollectionView, fetchStream: ShareStreamFetcher | null): void {
		this.collection = collection;
		this.baseTracks = playableTracks(collection.tracks);
		this.playOrder = [...this.baseTracks];
		this.activeIndex = -1;
		this.manifest = null;
		this.shuffle = false;
		this.windowEnded = false;
		this.fetchStream = fetchStream;
		this.previousCallbacks = audioPlayer.swapCallbacks({
			onEnded: (reason) => {
				if (reason === 'window-end') {
					this.windowEnded = true;
					return;
				}
				this.next();
			},
			onPlaybackStarted: () => {
				this.windowEnded = false;
			},
			onAuthLost: null,
			onStreamRebuild: this.fetchStream ? () => this.rebuildManifest() : null,
			onCurrentChange: (current) => this.resyncActiveIndex(current)
		});
	}

	stop(): void {
		audioPlayer.restoreCallbacks(this.previousCallbacks);
		audioPlayer.unload();
	}

	toggle(track: SharedTrack): void {
		if (this.currentTrack?.key === track.key) {
			audioPlayer.toggle();
			return;
		}
		void this.playTrack(track);
	}

	jump(orderIndex: number): void {
		const track = this.playOrder[orderIndex];
		if (track) void this.playTrack(track);
	}

	next(): void {
		if (audioPlayer.mode === 'stream') {
			audioPlayer.nextStreamTrack();
			return;
		}
		this.advanceClassic(1);
	}

	prev(): void {
		if (audioPlayer.mode === 'stream') {
			audioPlayer.prevStreamTrack();
			return;
		}
		this.advanceClassic(-1);
	}

	// Locked-in: enabling shuffle switches share playback to per-track loadUrl
	// over a share-local permutation; disabling it returns to stream mode.
	// Never touches the app's queueShuffleEnabled localStorage key.
	setShuffle(next: boolean): void {
		if (this.shuffle === next) return;
		this.shuffle = next;
		const anchor = this.currentTrack;
		this.playOrder = next ? shuffleKeepingFirst(this.baseTracks, anchor) : [...this.baseTracks];
		this.activeIndex = anchor ? this.playOrder.findIndex((t) => t.key === anchor.key) : -1;
		if (anchor) void this.playTrack(anchor);
	}

	private async playTrack(track: SharedTrack): Promise<void> {
		const collection = this.collection;
		if (track.audioUrl === null || !collection) return;
		if (this.canUseStream()) {
			try {
				const manifest = await this.ensureManifest();
				const streamTrack = manifest.tracks.find((t) => this.streamKeyOf(t) === track.key);
				if (streamTrack) {
					audioPlayer.loadStream(manifest, streamTrack.index, { autoplay: true });
					return;
				}
			} catch {
				this.manifest = null;
			}
		}
		this.manifest = null;
		audioPlayer.loadUrl(trackPlaybackInfo(collection, track), track.audioUrl, {
			autoplay: true,
			restart: true
		});
	}

	private advanceClassic(direction: 1 | -1): void {
		if (this.playOrder.length <= 1) return;
		const base = this.activeIndex >= 0 ? this.activeIndex : 0;
		const target = (base + direction + this.playOrder.length) % this.playOrder.length;
		void this.playTrack(this.playOrder[target]);
	}

	private canUseStream(): boolean {
		return (
			this.fetchStream !== null && !this.shuffle && shouldUseQueueStream(get(queuePlaybackMode))
		);
	}

	private async ensureManifest(): Promise<QueueStreamManifest> {
		if (
			this.manifest &&
			Date.parse(this.manifest.expires_at) > Date.now() + STREAM_REFRESH_MARGIN_MS
		) {
			return this.manifest;
		}
		if (!this.fetchStream) throw new Error('Stream unavailable for this share');
		const manifest = await this.fetchStream();
		this.manifest = manifest;
		return manifest;
	}

	private async rebuildManifest(): Promise<QueueStreamManifest | null> {
		if (!this.fetchStream) return null;
		try {
			const fresh = await this.fetchStream();
			this.manifest = fresh;
			return fresh;
		} catch {
			return null;
		}
	}

	private streamKeyOf(track: QueueStreamTrackItem): string | null {
		if (this.collection?.kind === 'album') return track.song_id;
		if (this.collection?.kind === 'playlist') return track.entry_id;
		return null;
	}

	private streamTrackFor(track: SharedTrack): QueueStreamTrackItem | null {
		if (!this.manifest) return null;
		return this.manifest.tracks.find((t) => this.streamKeyOf(t) === track.key) ?? null;
	}

	private resyncActiveIndex(current: PlaybackInfo | null): void {
		if (!current) {
			this.activeIndex = -1;
			return;
		}
		if (audioPlayer.mode === 'stream' && this.manifest) {
			const streamTrack = this.manifest.tracks.find(
				(t) => t.generation_id === current.generation.id
			);
			const key = streamTrack ? this.streamKeyOf(streamTrack) : null;
			this.activeIndex = key ? this.playOrder.findIndex((t) => t.key === key) : -1;
			return;
		}
		this.activeIndex = this.playOrder.findIndex((t) => t.key === current.generation.id);
	}
}
