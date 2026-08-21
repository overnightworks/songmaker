import type { GenerationItem, QueueStreamManifest, QueueStreamTrackItem } from '$lib/api/types';
import type { PlaybackInfo } from './playbackTypes';

export interface StreamFallbackState {
	manifest: QueueStreamManifest;
	trackIndex: number;
	trackTime: number;
}

interface StreamSession {
	manifest: QueueStreamManifest;
	activeIndex: number;
}

interface StreamTrackState {
	index: number;
	track: QueueStreamTrackItem;
	info: PlaybackInfo;
	currentTime: number;
	duration: number;
	absoluteTime: number;
}

export class QueueStreamEngine {
	private session: StreamSession | null = null;
	private pendingSeek: number | null = null;

	get active(): boolean {
		return this.session !== null;
	}

	get activeDuration(): number {
		return this.activeTrack?.duration ?? 0;
	}

	get canNext(): boolean {
		const session = this.session;
		if (!session || session.manifest.tracks.length <= 1) return false;
		return !session.manifest.windowed || session.activeIndex < session.manifest.tracks.length - 1;
	}

	get canPrev(): boolean {
		const session = this.session;
		if (!session || session.manifest.tracks.length <= 1) return false;
		return !session.manifest.windowed || session.activeIndex > 0;
	}

	get windowed(): boolean {
		return this.session?.manifest.windowed ?? false;
	}

	start(manifest: QueueStreamManifest, startIndex: number): StreamTrackState | null {
		if (manifest.tracks.length === 0) return null;
		const index = Math.max(0, Math.min(startIndex, manifest.tracks.length - 1));
		this.session = { manifest, activeIndex: index };
		this.pendingSeek = manifest.tracks[index].start_offset;
		return this.trackState(index, 0, this.pendingSeek);
	}

	clear(): void {
		this.session = null;
		this.pendingSeek = null;
	}

	resumeAt(absoluteSeconds: number): void {
		if (!this.session) return;
		this.pendingSeek = Math.max(0, absoluteSeconds);
	}

	seekLocal(el: HTMLAudioElement, seconds: number): void {
		const track = this.activeTrack;
		if (!track) return;
		el.currentTime = track.start_offset + Math.max(0, Math.min(seconds, track.duration));
	}

	seekToTrack(el: HTMLAudioElement, index: number): StreamTrackState | null {
		const session = this.session;
		if (!session) return null;
		const tracks = session.manifest.tracks;
		if (index < 0 || index >= tracks.length) return null;
		session.activeIndex = index;
		const track = tracks[index];
		el.currentTime = track.start_offset;
		return this.trackState(index, 0, track.start_offset);
	}

	nextTrack(el: HTMLAudioElement): StreamTrackState | null {
		const session = this.session;
		if (!session || !this.canNext) return null;
		const next = (session.activeIndex + 1) % session.manifest.tracks.length;
		return this.seekToTrack(el, next);
	}

	prevTrack(el: HTMLAudioElement): StreamTrackState | null {
		const session = this.session;
		if (!session || !this.canPrev) return null;
		const prev =
			(session.activeIndex - 1 + session.manifest.tracks.length) % session.manifest.tracks.length;
		return this.seekToTrack(el, prev);
	}

	applyPendingSeek(el: HTMLAudioElement): number | null {
		if (this.pendingSeek === null) return null;
		const seekTime = this.pendingSeek;
		try {
			el.currentTime = seekTime;
			this.pendingSeek = null;
			return seekTime;
		} catch {
			return null;
		}
	}

	updatePosition(absoluteTime: number): StreamTrackState | null {
		const session = this.session;
		if (!session) return null;
		const tracks = session.manifest.tracks;
		let index = tracks.findIndex(
			(track) => absoluteTime >= track.start_offset && absoluteTime < track.end_offset
		);
		if (index < 0) index = absoluteTime >= session.manifest.total_duration ? tracks.length - 1 : 0;
		session.activeIndex = index;
		const track = tracks[index];
		const currentTime = Math.max(0, Math.min(track.duration, absoluteTime - track.start_offset));
		return this.trackState(index, currentTime, absoluteTime);
	}

	fallbackState(localTime: number, absoluteTime: number): StreamFallbackState | null {
		const session = this.session;
		const track = this.activeTrack;
		if (!session || !track) return null;
		return {
			manifest: session.manifest,
			trackIndex: session.activeIndex,
			trackTime: localTime || Math.max(0, absoluteTime - track.start_offset)
		};
	}

	private get activeTrack(): QueueStreamTrackItem | null {
		const session = this.session;
		return session?.manifest.tracks[session.activeIndex] ?? null;
	}

	private trackState(index: number, currentTime: number, absoluteTime: number): StreamTrackState {
		if (!this.session) throw new Error('trackState requires an active stream session');
		const track = this.session.manifest.tracks[index];
		return {
			index,
			track,
			info: streamTrackToPlaybackInfo(track),
			currentTime,
			duration: track.duration,
			absoluteTime
		};
	}
}

export function streamTrackToPlaybackInfo(track: QueueStreamTrackItem): PlaybackInfo {
	return {
		generation: streamTrackToGeneration(track),
		songId: track.song_id,
		songTitle: track.song_title,
		artist: track.artist,
		albumTitle: track.album_title,
		lyrics: track.lyrics
	};
}

function streamTrackToGeneration(track: QueueStreamTrackItem): GenerationItem {
	return {
		id: track.generation_id,
		song_id: track.song_id,
		version_id: null,
		version_number: null,
		generation_number: track.generation_number,
		mp3_path: track.mp3_path,
		wav_path: null,
		seed: track.seed,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: true,
		is_shared: false,
		model_mode: track.model_mode,
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: track.lyrics,
		scores: null,
		generation_params: null,
		created_at: ''
	};
}
