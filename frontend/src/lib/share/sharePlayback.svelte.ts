// The share route's playback owner: drives the shared audioPlayer singleton
// for one mounted share collection. Never imports stores/player, navigation,
// editor, takeActions, or auth — see share-import-boundary.test.ts, which
// enforces that boundary for every file under lib/share and
// lib/components/share.

import type { QueueStreamManifest, QueueStreamTrackItem } from '#lib/api/types.ts';
import {
	audioPlayer,
	type AudioPlayerCallbacks,
	type PlaybackInfo,
	type PlayerTenure
} from '#lib/services/audioPlayer.svelte.ts';
import {
	playableTracks,
	trackPlaybackInfo,
	type SharedCollectionView,
	type SharedTrack
} from './sharedCollection';
import { updateMediaSessionMetadata } from '#lib/services/mediaSession.ts';
import { shuffled } from '#lib/utils/shuffle.ts';
import type { QueueRowItem, QueueViewModel } from '#lib/stores/player.ts';

export type ShareStreamFetcher = () => Promise<QueueStreamManifest>;

const STREAM_REFRESH_MARGIN_MS = 60_000;

// Where a track starts and whether it sounds at once: Play starts it from
// the top, a seek before the first Play readies it, paused, where it landed.
interface TrackStart {
	autoplay: boolean;
	startAt?: number;
}

const FROM_THE_TOP: TrackStart = { autoplay: true };

// Where a track stands in the share's stream.
interface StreamPlace {
	manifest: QueueStreamManifest;
	track: QueueStreamTrackItem;
}

const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null,
	networkFailureIsAnnounced: () => false
};

function shuffledAfterAnchor(tracks: SharedTrack[], anchor: SharedTrack | null): SharedTrack[] {
	if (!anchor) return shuffled(tracks);
	const rest = tracks.filter((t) => t.key !== anchor.key);
	return shuffled([anchor, ...rest], { keepFirst: true });
}

export class SharePlayback {
	shuffle = $state(false);
	// The share played to its end: its last track ran out with nothing after
	// it, never wrapping to the first. The player itself goes back to 0:00
	// there; the page keeps the end in view and Play starts the share again
	// from its first track.
	ended = $state(false);

	private collection: SharedCollectionView | null = null;
	private baseTracks: SharedTrack[] = [];
	private playOrder: SharedTrack[] = $state([]);
	private activeIndex = $state(-1);
	private manifest: QueueStreamManifest | null = $state(null);
	private fetchStream: ShareStreamFetcher | null = null;
	private previousCallbacks: AudioPlayerCallbacks = NO_CALLBACKS;
	// The hold on the player start() was given. Each request that waits on
	// the server keeps the tenure it began in, never this field: a share that
	// gave the player back and was started again holds a new one, so nothing
	// the earlier start asked for lands in the player or the manifest (#1391).
	private tenure: PlayerTenure | null = null;

	readonly currentTrack = $derived(
		this.activeIndex >= 0 ? (this.playOrder[this.activeIndex] ?? null) : null
	);

	// The playing take's own cues, taken from the share payload rather than
	// from the manifest, so lyrics follow playback in stream mode too.
	readonly currentCues = $derived(this.currentTrack?.cues ?? null);

	readonly canNext = $derived(
		audioPlayer.mode === 'stream'
			? audioPlayer.canNextStreamTrack
			: this.activeIndex < this.playOrder.length - 1
	);

	readonly canPrev = $derived(
		audioPlayer.mode === 'stream' ? audioPlayer.canPrevStreamTrack : this.activeIndex > 0
	);

	readonly queueRows = $derived.by((): QueueRowItem[] =>
		this.playOrder.map((track) => {
			const streamTrack = this.streamTrackFor(track);
			return {
				key: track.key,
				songId: track.key,
				songTitle: track.title,
				generationId: track.key,
				durationSec: streamTrack?.duration ?? track.durationSec,
				versionNumber: null,
				generationNumber: 1
			};
		})
	);

	readonly queue = $derived.by((): QueueViewModel => {
		const items = this.queueRows;
		const currentIndex = this.activeIndex;
		const upNext = currentIndex >= 0 ? (items[currentIndex + 1] ?? null) : null;
		return { items, currentIndex, upNext };
	});

	// A share shows only what was shared: whatever the signed-in app was
	// playing is dropped before the share takes the player over, while the
	// app's own callbacks still hear that take go.
	start(collection: SharedCollectionView, fetchStream: ShareStreamFetcher | null): void {
		audioPlayer.unload();
		this.collection = collection;
		this.baseTracks = playableTracks(collection.tracks);
		this.playOrder = [...this.baseTracks];
		this.activeIndex = -1;
		this.manifest = null;
		this.shuffle = false;
		this.ended = false;
		this.fetchStream = fetchStream;
		this.previousCallbacks = audioPlayer.swapCallbacks({
			onEnded: (reason) => {
				if (reason === 'window-end' || !this.canNext) this.ended = true;
				else this.next();
			},
			onPlaybackStarted: () => {
				this.ended = false;
			},
			onAuthLost: null,
			onStreamRebuild: this.fetchStream ? () => this.rebuildManifest() : null,
			onCurrentChange: (current) => this.resyncActiveIndex(current),
			networkFailureIsAnnounced: () => false
		});
		this.tenure = audioPlayer.tenure;
	}

	stop(): void {
		if (this.holdsThePlayer()) updateMediaSessionMetadata(null);
		audioPlayer.restoreCallbacks(this.previousCallbacks);
		audioPlayer.unload();
	}

	// The share's one Play: it starts the first track, pauses or resumes the
	// one playing, and once the share played to its end starts it again from
	// its first track.
	play(): void {
		if (this.currentTrack && !this.ended) {
			audioPlayer.toggle();
			return;
		}
		const first = this.playOrder[0];
		if (first) void this.playTrack(first);
	}

	// A seek leaves the end: the listener chose where the song stands. Before
	// the first Play there is nothing to move yet, so the first track is
	// readied there, paused, and Play starts where the listener put it.
	seek(seconds: number): void {
		this.ended = false;
		if (this.currentTrack) {
			audioPlayer.seek(seconds);
			return;
		}
		const first = this.playOrder[0];
		if (first) void this.playTrack(first, { autoplay: false, startAt: seconds });
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
		this.playOrder = next ? shuffledAfterAnchor(this.baseTracks, anchor) : [...this.baseTracks];
		this.activeIndex = anchor ? this.playOrder.findIndex((t) => t.key === anchor.key) : -1;
		if (anchor) void this.playTrack(anchor);
	}

	private async playTrack(track: SharedTrack, start: TrackStart = FROM_THE_TOP): Promise<void> {
		const collection = this.collection;
		const tenure = this.tenure;
		if (track.audioUrl === null || !collection || tenure === null) return;
		this.ended = false;
		// Without a stream the track loads in the same task as the press, which
		// a browser needs to let it sound.
		const place = this.canUseStream() ? await this.streamPlaceOf(track, tenure) : null;
		if (!this.stillHolds(tenure)) return;
		if (place) {
			audioPlayer.loadStream(place.manifest, place.track.index, {
				autoplay: start.autoplay,
				resumeAt: place.track.start_offset + (start.startAt ?? 0)
			});
			return;
		}
		this.manifest = null;
		audioPlayer.loadUrl(trackPlaybackInfo(collection, track), track.audioUrl, {
			autoplay: start.autoplay,
			restart: true,
			startAt: start.startAt
		});
	}

	// Null where the track plays on its own instead: the stream could not be
	// had, or does not hold it.
	private async streamPlaceOf(
		track: SharedTrack,
		tenure: PlayerTenure
	): Promise<StreamPlace | null> {
		try {
			const manifest = await this.ensureManifest(tenure);
			const streamTrack = manifest.tracks.find((t) => this.streamKeyOf(t) === track.key);
			return streamTrack ? { manifest, track: streamTrack } : null;
		} catch {
			return null;
		}
	}

	private stillHolds(tenure: PlayerTenure): boolean {
		return !audioPlayer.changedHandsSince(tenure);
	}

	private holdsThePlayer(): boolean {
		return this.tenure !== null && this.stillHolds(this.tenure);
	}

	private advanceClassic(direction: 1 | -1): void {
		const target = this.playOrder[this.activeIndex + direction];
		if (target) void this.playTrack(target);
	}

	private canUseStream(): boolean {
		return this.fetchStream !== null && !this.shuffle;
	}

	private async ensureManifest(tenure: PlayerTenure): Promise<QueueStreamManifest> {
		if (
			this.manifest &&
			Date.parse(this.manifest.expires_at) > Date.now() + STREAM_REFRESH_MARGIN_MS
		) {
			return this.manifest;
		}
		if (!this.fetchStream) throw new Error('Stream unavailable for this share');
		const manifest = await this.fetchWindowedStream(this.fetchStream);
		if (this.stillHolds(tenure)) this.manifest = manifest;
		return manifest;
	}

	// A share's stream has an end: marked windowed, the engine stops after the
	// last track and signals it instead of wrapping to the first.
	private async fetchWindowedStream(fetchStream: ShareStreamFetcher): Promise<QueueStreamManifest> {
		return { ...(await fetchStream()), windowed: true };
	}

	private async rebuildManifest(): Promise<QueueStreamManifest | null> {
		const tenure = this.tenure;
		if (!this.fetchStream || tenure === null) return null;
		try {
			const fresh = await this.fetchWindowedStream(this.fetchStream);
			if (!this.stillHolds(tenure)) return null;
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
		this.locateActiveIndex(current);
		this.nameOnLockScreen();
	}

	private nameOnLockScreen(): void {
		if (!this.holdsThePlayer()) return;
		const track = this.currentTrack;
		updateMediaSessionMetadata(
			this.collection && track ? trackPlaybackInfo(this.collection, track) : null
		);
	}

	private locateActiveIndex(current: PlaybackInfo | null): void {
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
