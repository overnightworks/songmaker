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

	getElement(): HTMLAudioElement | null {
		return this.audio;
	}

	load(info: PlaybackInfo, opts: { autoplay?: boolean } = {}): void {
		const autoplay = opts.autoplay ?? true;
		const sameGen =
			this.current?.generation.id === info.generation.id &&
			this.current?.generation.mp3_path === info.generation.mp3_path;

		this.current = info;
		this.error = null;

		if (sameGen && this.audio && this.status !== 'error') {
			if (autoplay && this.status !== 'playing') this.play();
			return;
		}

		this.autoplayPending = autoplay;
		const el = this.ensureAudio();
		el.pause();
		this.status = 'loading';
		this.currentTime = 0;
		this.duration = 0;
		el.src = AUDIO_URL_PREFIX + info.generation.mp3_path;
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
		this.audio.pause();
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
		});
		el.addEventListener('canplay', () => {
			if (this.status === 'error') return;
			this.status = el.paused ? 'ready' : 'playing';
			this.duration = el.duration || this.duration;
			if (this.autoplayPending) {
				this.autoplayPending = false;
				el.play().catch((err) => this.handlePlayRejection(err));
			}
		});
		el.addEventListener('timeupdate', () => {
			this.currentTime = el.currentTime;
		});
		el.addEventListener('play', () => {
			if (this.status !== 'error') this.status = 'playing';
		});
		el.addEventListener('playing', () => {
			if (this.status === 'buffering' || this.status === 'loading') this.status = 'playing';
		});
		el.addEventListener('pause', () => {
			if (this.status === 'error') return;
			if (el.ended) return;
			this.status = 'paused';
		});
		el.addEventListener('waiting', () => {
			if (this.status === 'playing') this.status = 'buffering';
		});
		el.addEventListener('stalled', () => {
			if (this.status === 'playing') this.status = 'buffering';
		});
		el.addEventListener('ended', () => {
			this.status = 'idle';
			this.currentTime = 0;
			this.onEnded?.();
		});
		el.addEventListener('error', () => {
			this.handleMediaError(el.error);
		});
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
