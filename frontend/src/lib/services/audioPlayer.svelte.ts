import type { GenerationItem } from '$lib/api/types';

export type PlayerStatus =
	| 'idle'
	| 'loading'
	| 'ready'
	| 'playing'
	| 'paused'
	| 'buffering'
	| 'error';

export interface PlaybackInfo {
	generation: GenerationItem;
	songId: string;
	songTitle: string;
	artist: string;
}

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

	onEnded: (() => void) | null = null;
	onAuthLost: (() => void | Promise<void>) | null = null;

	private audio: HTMLAudioElement | null = null;
	private autoplayPending = false;
	private listenersAttached = false;
	private stallRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
	private recoveryAttempts = 0;
	private pendingRecoverySeek: number | null = null;
	private lastObservedTime = 0;

	getElement(): HTMLAudioElement | null {
		return this.audio;
	}

	load(info: PlaybackInfo, opts: { autoplay?: boolean; restart?: boolean } = {}): void {
		const autoplay = opts.autoplay ?? true;
		const restart = opts.restart ?? false;
		const sameGen =
			this.current?.generation.id === info.generation.id &&
			this.current?.generation.mp3_path === info.generation.mp3_path;

		this.current = info;
		this.error = null;

		if (sameGen && this.audio && this.status !== 'error' && !restart) {
			if (autoplay && this.status !== 'playing') this.play();
			return;
		}

		this.clearStallRecoveryTimer();
		this.recoveryAttempts = 0;
		this.pendingRecoverySeek = null;
		this.lastObservedTime = 0;
		this.autoplayPending = autoplay;
		const el = this.ensureAudio();
		el.pause();
		this.status = 'loading';
		this.currentTime = 0;
		this.duration = 0;
		el.src = this.audioUrl(info.generation.mp3_path);
		el.load();
	}

	play(): void {
		if (!this.audio || !this.current) return;
		if (this.status === 'error') {
			this.load(this.current, { autoplay: true });
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
		if (this.status === 'loading') return;
		if (this.audio.paused) this.play();
		else this.pause();
	}

	seek(seconds: number): void {
		if (!this.audio || this.duration <= 0) return;
		this.audio.currentTime = Math.max(0, Math.min(seconds, this.duration));
	}

	destroy(): void {
		if (!this.audio) return;
		this.clearStallRecoveryTimer();
		this.audio.pause();
		this.audio.src = '';
		this.audio.removeAttribute('src');
		this.audio = null;
		this.listenersAttached = false;
		this.status = 'idle';
		this.current = null;
		this.currentTime = 0;
		this.duration = 0;
		this.error = null;
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
			this.duration = el.duration || 0;
			this.applyPendingRecoverySeek(el);
		});
		el.addEventListener('canplay', () => {
			if (this.status === 'error') return;
			this.applyPendingRecoverySeek(el);
			this.status = el.paused ? 'ready' : 'playing';
			this.duration = el.duration || this.duration;
			if (this.autoplayPending) {
				this.autoplayPending = false;
				el.play().catch((err) => this.handlePlayRejection(err));
			}
		});
		el.addEventListener('timeupdate', () => {
			if (Math.abs(el.currentTime - this.lastObservedTime) > 0.05) {
				this.lastObservedTime = el.currentTime;
				this.clearStallRecoveryTimer();
				if (this.status === 'buffering') this.status = 'playing';
			}
			this.currentTime = el.currentTime;
		});
		el.addEventListener('play', () => {
			if (this.status !== 'error') this.status = 'playing';
		});
		el.addEventListener('playing', () => {
			this.clearStallRecoveryTimer();
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
			this.status = 'idle';
			this.currentTime = 0;
			this.onEnded?.();
		});
		el.addEventListener('error', () => {
			if (!this.recoverPlayback('media-error')) this.handleMediaError(el.error);
		});
	}

	private audioUrl(mp3Path: string, recoveryAttempt?: number): string {
		const url = AUDIO_URL_PREFIX + mp3Path;
		return recoveryAttempt ? `${url}?recover=${recoveryAttempt}` : url;
	}

	private scheduleStallRecovery(): void {
		if (this.stallRecoveryTimer || !this.current || !this.audio) return;
		this.stallRecoveryTimer = setTimeout(() => {
			this.stallRecoveryTimer = null;
			if (this.status !== 'buffering') return;
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
		if (!target || !el || el.ended || this.recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) return false;

		const observedTime = el.currentTime || this.currentTime || this.lastObservedTime;
		if (observedTime < 1) return false;

		const seekTime = Math.max(
			0,
			observedTime - RECOVERY_SEEK_BACK_SECONDS
		);
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
		el.src = this.audioUrl(target.generation.mp3_path, this.recoveryAttempts);
		el.load();
		return true;
	}

	private applyPendingRecoverySeek(el: HTMLAudioElement): void {
		if (this.pendingRecoverySeek === null) return;
		const seekTime = this.duration > 0
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
		if (!target) return;

		const probe = await this.probeAudioUrl(target.generation.mp3_path);

		if (this.current !== target) return;

		if (probe.status === 401) {
			await this.onAuthLost?.();
			return;
		}
		if (probe.status === 404) this.error = ERROR_MSG_NOT_FOUND;
		else if (probe.status === 0) this.error = ERROR_MSG_NETWORK;
		else if (probe.ok && mediaError) this.error = decodeMediaError(mediaError);
	}

	private async probeAudioUrl(mp3Path: string): Promise<{ ok: boolean; status: number }> {
		try {
			const resp = await fetch(AUDIO_URL_PREFIX + mp3Path, {
				method: 'HEAD',
				credentials: 'include'
			});
			return { ok: resp.ok, status: resp.status };
		} catch {
			return { ok: false, status: 0 };
		}
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
