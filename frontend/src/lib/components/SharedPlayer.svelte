<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import type { QueueStreamTrackItem } from '$lib/api/types';
	import {
		pushMediaSessionHandlers,
		updateMediaSessionPlaybackState,
		updateMediaSessionPositionState,
		updateMediaSessionTitle
	} from '$lib/services/mediaSession';
	import { formatTime } from '$lib/utils/format';
	import Icon from './Icon.svelte';
	import QueueStreamFeedback from './QueueStreamFeedback.svelte';
	import {
		AudioVisualizer,
		FFT_SIZE,
		readVizColors,
		boxShadowStyle,
		titleGlowStyle,
		playbackVisualizerAllowed,
		type VizColors
	} from '$lib/utils/visualizer';

	interface Props {
		audioUrl: string;
		title: string;
		subtitle?: string;
		autoplay?: boolean;
		streamTracks?: QueueStreamTrackItem[];
		streamWindowed?: boolean;
		startIndex?: number;
		onended?: () => void;
		onnext?: () => void;
		onprev?: () => void;
		onerror?: () => void;
		ontrackchange?: (track: QueueStreamTrackItem, index: number) => void;
		onstatechange?: (playing: boolean, loading: boolean) => void;
	}

	type LoadAndPlayOptions =
		| number
		| {
				startIndex?: number;
				streamTracks?: QueueStreamTrackItem[] | null;
				streamWindowed?: boolean;
		  };

	let {
		audioUrl,
		title,
		subtitle,
		autoplay,
		streamTracks,
		streamWindowed = false,
		startIndex = 0,
		onended,
		onnext,
		onprev,
		onerror,
		ontrackchange,
		onstatechange
	}: Props = $props();

	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let isPlaying = $state(false);
	let isLoading = $state(false);
	let currentTime = $state(0);
	let duration = $state(0);
	let bassLevel = $state(0);
	let energyLevel = $state(0);
	let vizColors: VizColors = $state({ pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 });

	let audio: HTMLAudioElement | undefined;
	let audioCtx: AudioContext | undefined;
	let analyser: AnalyserNode | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let playWhenReady = false;
	let playIntentRevision = 0;
	let playbackStreamTracks: QueueStreamTrackItem[] | null | undefined = $state(undefined);
	let playbackStreamWindowed: boolean | undefined = $state(undefined);
	let prevUrl: string | undefined;
	let prevManifest: QueueStreamTrackItem[] | undefined;
	let prevStreamWindowed: boolean | undefined;
	let activeStreamIndex = $state(0);
	let windowEnded = $state(false);
	let terminalSignaled = false;
	const effectiveStreamTracks = $derived(
		playbackStreamTracks === undefined ? streamTracks : playbackStreamTracks
	);
	const effectiveStreamWindowed = $derived(
		playbackStreamWindowed === undefined ? streamWindowed : playbackStreamWindowed
	);
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);
	const activeStreamTrack = $derived(effectiveStreamTracks?.[activeStreamIndex] ?? null);
	const displayTitle = $derived(activeStreamTrack?.song_title ?? title);
	const displaySubtitle = $derived(activeStreamTrack?.artist ?? subtitle);
	const canPrev = $derived(
		!effectiveStreamTracks ||
			(effectiveStreamTracks.length > 1 && (!effectiveStreamWindowed || activeStreamIndex > 0))
	);
	const canNext = $derived(
		!effectiveStreamTracks ||
			(effectiveStreamTracks.length > 1 &&
				(!effectiveStreamWindowed || activeStreamIndex < effectiveStreamTracks.length - 1))
	);

	const viz = new AudioVisualizer();

	function ensureAudio(): HTMLAudioElement {
		if (audio) return audio;
		audio = new Audio();
		audio.crossOrigin = 'anonymous';
		audio.preload = 'auto';

		audio.addEventListener('loadstart', () => (isLoading = true));
		audio.addEventListener('canplay', () => {
			isLoading = false;
			duration = activeStreamTrack?.duration ?? audio?.duration ?? 0;
			applyPendingStreamStart();
			if (audio && playWhenReady) {
				playWhenReady = false;
				requestPlay(audio);
			}
			connectAnalyser();
		});
		audio.addEventListener('timeupdate', () => {
			if (effectiveStreamTracks) updateStreamPosition(audio?.currentTime ?? 0);
			else currentTime = audio?.currentTime ?? 0;
		});
		audio.addEventListener('ended', () => {
			setPaused();
			if (effectiveStreamTracks && effectiveStreamWindowed) {
				if (!terminalSignaled) {
					terminalSignaled = true;
					windowEnded = true;
				}
				return;
			}
			onended?.();
		});
		audio.addEventListener('play', () => {
			terminalSignaled = false;
			windowEnded = false;
			isPlaying = true;
			startVisualizerLoop();
		});
		audio.addEventListener('pause', () => setPaused(!isLoading));
		audio.addEventListener('error', () => {
			setPaused();
			isLoading = false;
			onerror?.();
		});

		return audio;
	}

	function requestPlay(el: HTMLAudioElement): void {
		playWhenReady = false;
		const requestRevision = ++playIntentRevision;
		el.play().catch(() => {
			if (requestRevision !== playIntentRevision) return;
			setPaused();
			isLoading = false;
		});
	}

	function setPaused(cancelPendingPlay = true): void {
		isPlaying = false;
		if (cancelPendingPlay) {
			playWhenReady = false;
			playIntentRevision += 1;
		}
		stopVisualizerLoop();
	}

	function pausePlayback(): void {
		setPaused();
		audio?.pause();
	}

	function audioUrlChanged(el: HTMLAudioElement, nextUrl: string): boolean {
		return el.src !== new URL(nextUrl, window.location.href).href;
	}

	function prepareWithoutAutoplay(nextUrl: string): HTMLAudioElement {
		const el = ensureAudio();
		if (audioUrlChanged(el, nextUrl)) {
			setPaused();
			el.pause();
			isLoading = true;
			el.src = nextUrl;
			el.load();
		} else {
			isLoading = el.readyState < HTMLMediaElement.HAVE_FUTURE_DATA;
		}
		return el;
	}

	export function loadAndPlay(nextUrl: string = audioUrl, options: LoadAndPlayOptions = {}): void {
		windowEnded = false;
		terminalSignaled = false;
		playIntentRevision += 1;
		playWhenReady = false;
		const normalized = typeof options === 'number' ? { startIndex: options } : options;
		playbackStreamTracks = normalized.streamTracks;
		playbackStreamWindowed = normalized.streamWindowed;
		const tracks = effectiveStreamTracks;
		const el = ensureAudio();
		const changed = audioUrlChanged(el, nextUrl);
		if (changed) {
			setPaused();
			el.pause();
		}
		prevUrl = nextUrl;
		const nextStartIndex = normalized.startIndex ?? startIndex;
		activeStreamIndex = Math.max(0, Math.min(nextStartIndex, (tracks?.length ?? 1) - 1));
		currentTime = 0;
		duration = activeStreamTrack?.duration ?? 0;
		isLoading = changed || el.readyState < HTMLMediaElement.HAVE_FUTURE_DATA;
		playWhenReady = true;
		if (changed) {
			el.src = nextUrl;
			el.load();
		}
		applyPendingStreamStart();
		if (el.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA && playWhenReady) {
			playWhenReady = false;
			isLoading = false;
			requestPlay(el);
		}
	}

	function connectAnalyser(): void {
		if (!audio || audioCtx) return;
		if (!playbackVisualizerAllowed()) return;
		try {
			audioCtx = new AudioContext();
			analyser = audioCtx.createAnalyser();
			analyser.fftSize = FFT_SIZE;
			analyser.smoothingTimeConstant = 0.82;
			const source = audioCtx.createMediaElementSource(audio);
			source.connect(analyser);
			analyser.connect(audioCtx.destination);
			frequencyData = new Uint8Array(analyser.frequencyBinCount) as Uint8Array<ArrayBuffer>;
			waveformData = new Uint8Array(analyser.fftSize) as Uint8Array<ArrayBuffer>;
		} catch {
			/* visualizer unavailable */
		}
	}

	function startVisualizerLoop(): void {
		if (!vizCanvas) return;
		if (!playbackVisualizerAllowed()) return;
		if (!audioCtx) connectAnalyser();
		if (!analyser || !frequencyData || !waveformData) return;
		if (audioCtx?.state === 'suspended') audioCtx.resume();
		vizColors = readVizColors();
		viz.startLoop(vizCanvas, analyser, frequencyData, waveformData, vizColors, (bass, energy) => {
			bassLevel = bass;
			energyLevel = energy;
		});
	}

	function stopVisualizerLoop(): void {
		if (vizCanvas) viz.stopLoop(vizCanvas);
	}

	function handleVisibilityChange(): void {
		if (document.hidden) {
			stopVisualizerLoop();
			return;
		}
		if (isPlaying) startVisualizerLoop();
	}

	$effect(() => {
		if (
			audioUrl === prevUrl &&
			streamTracks === prevManifest &&
			streamWindowed === prevStreamWindowed
		)
			return;
		const isInitial = prevUrl === undefined;
		prevUrl = audioUrl;
		prevManifest = streamTracks;
		prevStreamWindowed = streamWindowed;
		if (isInitial && !autoplay) {
			prepareWithoutAutoplay(audioUrl);
			return;
		}
		loadAndPlay(audioUrl, {
			startIndex,
			streamTracks: streamTracks ?? null,
			streamWindowed
		});
	});

	$effect(() => {
		onstatechange?.(isPlaying, isLoading);
	});

	$effect(() => {
		updateMediaSessionTitle(displayTitle, displaySubtitle);
		updateMediaSessionPlaybackState(isPlaying ? 'playing' : 'paused');
		updateMediaSessionPositionState(currentTime, duration);
	});

	onMount(() => {
		return pushMediaSessionHandlers({
			play: () => {
				const el = ensureAudio();
				if (!el.src) prepareWithoutAutoplay(audioUrl);
				if (isLoading || el.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
					playIntentRevision += 1;
					playWhenReady = true;
				} else requestPlay(el);
			},
			pause: pausePlayback,
			stop: pausePlayback,
			next: () => onnext?.(),
			prev: () => onprev?.(),
			seekTo: (seconds) => {
				if (!audio || duration <= 0) return;
				audio.currentTime = activeStreamTrack
					? activeStreamTrack.start_offset + seconds
					: Math.max(0, Math.min(seconds, duration));
			}
		});
	});

	export function togglePlay(): void {
		const el = ensureAudio();
		if (!el.src) prepareWithoutAutoplay(audioUrl);
		if (isLoading || el.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
			isLoading = true;
			playIntentRevision += 1;
			playWhenReady = !playWhenReady;
			return;
		}
		if (el.paused) requestPlay(el);
		else pausePlayback();
	}

	export function seekToTrack(index: number): void {
		const tracks = effectiveStreamTracks;
		if (!audio || !tracks || tracks.length === 0) return;
		if (effectiveStreamWindowed && (index < 0 || index >= tracks.length)) return;
		const nextIndex = (index + tracks.length) % tracks.length;
		activeStreamIndex = nextIndex;
		const track = tracks[nextIndex];
		currentTime = 0;
		duration = track.duration;
		audio.currentTime = track.start_offset;
		ontrackchange?.(track, nextIndex);
		if (audio.paused) requestPlay(audio);
	}

	function seek(e: MouseEvent): void {
		if (!audio || duration <= 0) return;
		const el = e.currentTarget as HTMLElement;
		const rect = el.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		const targetTime = ratio * duration;
		audio.currentTime = activeStreamTrack
			? activeStreamTrack.start_offset + targetTime
			: targetTime;
	}

	function seekFromRange(e: Event): void {
		if (!audio || duration <= 0) return;
		const targetTime = Number((e.currentTarget as HTMLInputElement).value);
		audio.currentTime = activeStreamTrack
			? activeStreamTrack.start_offset + targetTime
			: targetTime;
	}

	function applyPendingStreamStart(): void {
		if (!audio || !activeStreamTrack) return;
		if (audio.readyState < 1) return;
		if (Math.abs(audio.currentTime - activeStreamTrack.start_offset) > 0.25 && currentTime === 0) {
			try {
				audio.currentTime = activeStreamTrack.start_offset;
			} catch {
				/* wait for more metadata */
			}
		}
	}

	function updateStreamPosition(absoluteTime: number): void {
		const tracks = effectiveStreamTracks;
		if (!tracks || tracks.length === 0) return;
		let index = tracks.findIndex(
			(track) => absoluteTime >= track.start_offset && absoluteTime < track.end_offset
		);
		if (index < 0)
			index = absoluteTime >= tracks[tracks.length - 1].end_offset ? tracks.length - 1 : 0;
		if (index !== activeStreamIndex) {
			activeStreamIndex = index;
			ontrackchange?.(tracks[index], index);
		}
		const track = tracks[index];
		duration = track.duration;
		currentTime = Math.max(0, Math.min(track.duration, absoluteTime - track.start_offset));
	}

	onDestroy(() => {
		viz.destroy();
		playWhenReady = false;
		playIntentRevision += 1;
		if (audio) {
			audio.pause();
			audio.src = '';
		}
		if (audioCtx) audioCtx.close();
		terminalSignaled = false;
	});
</script>

<svelte:document onvisibilitychange={handleVisibilityChange} />

<div class="shared-player" style={isPlaying ? boxShadowStyle(energyLevel, vizColors) : ''}>
	<canvas class="viz-canvas" bind:this={vizCanvas}></canvas>
	<div class="player-content">
		<div class="player-controls">
			<div class="transport-controls">
				{#if onprev}
					<button
						class="nav-btn"
						onclick={onprev}
						disabled={!canPrev}
						aria-label="Previous"
						title="Previous"
					>
						<Icon name="skip-back" size={21} />
					</button>
				{:else}
					<span class="nav-spacer" aria-hidden="true"></span>
				{/if}
				<button
					class="play-btn"
					class:loading={isLoading}
					class:playing={isPlaying}
					onclick={togglePlay}
					aria-label={isPlaying ? 'Pause' : 'Play'}
				>
					<span
						class="play-btn-face"
						style={isPlaying ? `transform: scale(${1 + bassLevel * 0.15})` : ''}
					>
						{#if isLoading}<span class="spinner"></span>{:else}<Icon
								name={isPlaying ? 'pause' : 'play'}
								size={26}
							/>{/if}
					</span>
				</button>
				{#if onnext}
					<button
						class="nav-btn"
						onclick={onnext}
						disabled={!canNext}
						aria-label="Next"
						title="Next"
					>
						<Icon name="skip-forward" size={21} />
					</button>
				{:else}
					<span class="nav-spacer" aria-hidden="true"></span>
				{/if}
			</div>
			<div class="queue-feedback"><QueueStreamFeedback {windowEnded} /></div>
		</div>
		<div class="track-info">
			<span
				class="track-title"
				class:glowing={isPlaying}
				style={isPlaying ? titleGlowStyle(bassLevel, vizColors) : ''}>{displayTitle}</span
			>
			{#if displaySubtitle}
				<span class="track-detail">{displaySubtitle}</span>
			{/if}
		</div>
		<div class="timeline">
			<span class="time">{formatTime(currentTime)}</span>
			<input
				class="timeline-range"
				style={`--progress: ${progressPercent}%`}
				type="range"
				min="0"
				max={duration || 0}
				step="0.1"
				value={duration > 0 ? currentTime : 0}
				oninput={seekFromRange}
				onclick={(e) => seek(e)}
				disabled={duration <= 0}
				aria-label="Seek playback"
			/>
			<span class="time">{formatTime(duration)}</span>
		</div>
	</div>
</div>

<style>
	.shared-player {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		height: var(--player-height, 88px);
		background: var(--card-bg, #111);
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		padding: 10px 18px calc(10px + env(safe-area-inset-bottom, 0px));
		z-index: 100;
		overflow: hidden;
		transition: box-shadow 0.3s;
	}

	.player-content {
		position: relative;
		z-index: 1;
		display: grid;
		grid-template-columns: auto minmax(120px, 240px) minmax(180px, 1fr);
		align-items: center;
		gap: 14px;
		width: 100%;
		min-width: 0;
	}

	.player-controls {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
		position: relative;
	}

	.transport-controls {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.nav-btn {
		width: 44px;
		height: 44px;
		background: color-mix(in srgb, var(--surface, #111) 70%, transparent);
		border: 1px solid color-mix(in srgb, var(--border, #333) 80%, transparent);
		border-radius: 50%;
		color: var(--text-muted, #888);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		flex-shrink: 0;
		transition:
			background 0.15s,
			border-color 0.15s,
			color 0.15s;
	}

	.nav-btn:hover {
		color: var(--text, #e0e0e0);
		border-color: color-mix(in srgb, var(--primary, #ff3220) 65%, var(--border, #333));
		background: color-mix(in srgb, var(--primary, #ff3220) 12%, var(--surface, #111));
	}

	.nav-spacer {
		width: 44px;
		height: 44px;
		flex: 0 0 44px;
	}

	.play-btn {
		width: 62px;
		height: 62px;
		border-radius: 50%;
		border: 2px solid var(--primary, #ff3220);
		background: color-mix(in srgb, var(--surface, #111) 72%, transparent);
		color: var(--primary, #ff3220);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		cursor: pointer;
		transition:
			background 0.2s,
			border-color 0.3s,
			color 0.2s;
	}

	.play-btn-face {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.play-btn:hover {
		background: linear-gradient(135deg, var(--primary, #ff3220), var(--accent, #a020f0));
		border-color: transparent;
		color: #fff;
	}

	.play-btn.loading {
		border-color: var(--text-decoration, #444);
	}

	.play-btn.playing {
		border-color: var(--accent, #a020f0);
	}

	@supports (animation-timeline: auto) or (background-clip: border-box) {
		@media (prefers-reduced-motion: no-preference) {
			.play-btn.playing {
				border-color: transparent;
				background-origin: border-box;
				background-clip: padding-box, border-box;
				background-image:
					linear-gradient(var(--card-bg, #111), var(--card-bg, #111)),
					conic-gradient(
						from var(--border-angle, 0deg),
						var(--primary),
						var(--accent),
						var(--primary)
					);
				animation: rotate-border 2s linear infinite;
			}
		}
	}

	@keyframes rotate-border {
		to {
			--border-angle: 360deg;
		}
	}

	@property --border-angle {
		syntax: '<angle>';
		initial-value: 0deg;
		inherits: false;
	}

	.spinner {
		width: 24px;
		height: 24px;
		border: 2px solid transparent;
		border-radius: 50%;
		background-origin: border-box;
		background-clip: content-box, border-box;
		background-image:
			linear-gradient(transparent, transparent),
			conic-gradient(var(--primary), var(--accent), var(--primary));
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.track-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
	}

	.track-title {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 0.87rem;
		color: var(--text, #e0e0e0);
		text-transform: uppercase;
		letter-spacing: 1px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		transition: text-shadow 0.3s;
	}

	@media (prefers-reduced-motion: no-preference) {
		.track-title.glowing {
			text-shadow:
				0 0 8px color-mix(in srgb, var(--accent) 50%, transparent),
				0 0 16px color-mix(in srgb, var(--accent) 20%, transparent);
		}
	}

	.track-detail {
		font-size: 0.73rem;
		color: var(--text-muted, #888);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.timeline {
		display: grid;
		grid-template-columns: auto minmax(80px, 1fr) auto;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.time {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: var(--label-font-size);
		color: var(--text-muted, #888);
		min-width: 36px;
		text-align: center;
		flex-shrink: 0;
	}

	.timeline-range {
		--track-bg: color-mix(in srgb, var(--border, #333) 45%, transparent);
		appearance: none;
		-webkit-appearance: none;
		width: 100%;
		height: 34px;
		background: transparent;
		cursor: pointer;
		accent-color: var(--accent, #a020f0);
	}

	.timeline-range:disabled {
		cursor: default;
		opacity: 0.45;
	}

	.timeline-range::-webkit-slider-runnable-track {
		height: 8px;
		border-radius: 999px;
		background: linear-gradient(
			90deg,
			var(--primary, #ff3220) 0%,
			var(--accent, #a020f0) var(--progress),
			var(--track-bg) var(--progress),
			var(--track-bg) 100%
		);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border, #333) 55%, transparent);
	}

	.timeline-range::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid var(--card-bg, #111);
		background: var(--text, #e0e0e0);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent, #a020f0) 28%, transparent);
		margin-top: -5px;
	}

	.timeline-range:hover:not(:disabled)::-webkit-slider-thumb {
		background: #fff;
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent, #a020f0) 30%, transparent);
	}

	.timeline-range::-moz-range-track {
		height: 8px;
		border-radius: 999px;
		background: var(--track-bg);
	}

	.timeline-range::-moz-range-progress {
		height: 8px;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--primary), var(--accent));
	}

	.timeline-range::-moz-range-thumb {
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid var(--card-bg, #111);
		background: var(--text, #e0e0e0);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent, #a020f0) 28%, transparent);
	}

	.viz-canvas {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		z-index: 0;
	}

	@media (max-width: 900px) {
		.shared-player {
			padding: 8px 10px calc(8px + env(safe-area-inset-bottom, 0px));
		}

		.player-content {
			grid-template-columns: auto minmax(80px, 1fr) minmax(120px, 1.2fr);
			gap: 10px;
		}

		.nav-btn {
			width: 40px;
			height: 40px;
		}

		.nav-spacer {
			width: 40px;
			height: 40px;
			flex-basis: 40px;
		}

		.play-btn {
			width: 56px;
			height: 56px;
		}
	}

	@media (max-width: 640px), (any-pointer: coarse) {
		.shared-player {
			overflow: visible;
		}
		.player-content {
			display: flex;
			flex-direction: column;
			gap: 8px;
		}

		.player-controls {
			justify-content: center;
			gap: 8px;
			width: 100%;
		}

		.transport-controls {
			gap: 8px;
		}
		.queue-feedback {
			position: absolute;
			right: 0;
			bottom: calc(100% + 4px);
		}

		.track-info {
			display: flex;
			flex-direction: column;
			align-items: center;
			justify-content: center;
			gap: 0;
			width: 100%;
			text-align: center;
		}

		.track-title {
			font-size: 0.85rem;
			width: 100%;
			max-width: 100%;
			min-width: 0;
		}

		.track-detail {
			display: none;
		}

		.timeline {
			width: 100%;
			gap: 6px;
		}

		.nav-btn {
			position: relative;
			width: 44px;
			height: 44px;
			min-width: 44px;
			min-height: 44px;
			border-color: transparent;
			background: transparent;
			isolation: isolate;
		}

		.nav-spacer {
			width: 44px;
			height: 44px;
			flex-basis: 44px;
		}

		.nav-btn::before {
			content: '';
			position: absolute;
			z-index: -1;
			width: 36px;
			height: 36px;
			border: 1px solid color-mix(in srgb, var(--border, #333) 80%, transparent);
			border-radius: 50%;
			background: color-mix(in srgb, var(--surface, #111) 70%, transparent);
		}
		.nav-btn:hover {
			border-color: transparent;
			background: transparent;
		}
		.nav-btn:hover::before {
			border-color: color-mix(in srgb, var(--primary, #ff3220) 65%, var(--border, #333));
			background: color-mix(in srgb, var(--primary, #ff3220) 12%, var(--surface, #111));
		}
		.nav-btn :global(svg) {
			position: relative;
			z-index: 1;
			width: 18px;
			height: 18px;
		}

		.play-btn {
			width: 56px;
			height: 56px;
			min-width: 56px;
			min-height: 56px;
		}

		.play-btn-face {
			transform: none !important;
		}

		.time {
			font-size: 0.7rem;
			min-width: 28px;
		}
	}
	:global(html[data-pointer='coarse']) .shared-player {
		overflow: visible;
	}
	:global(html[data-pointer='coarse']) .player-content {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	:global(html[data-pointer='coarse']) .player-controls {
		justify-content: center;
		gap: 8px;
		width: 100%;
	}
	:global(html[data-pointer='coarse']) .transport-controls {
		gap: 8px;
	}
	:global(html[data-pointer='coarse']) .queue-feedback {
		position: absolute;
		right: 0;
		bottom: calc(100% + 4px);
	}
	:global(html[data-pointer='coarse']) .track-info {
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0;
		width: 100%;
		text-align: center;
	}
	:global(html[data-pointer='coarse']) .track-title {
		font-size: 0.85rem;
		width: 100%;
		max-width: 100%;
		min-width: 0;
	}
	:global(html[data-pointer='coarse']) .track-detail {
		display: none;
	}
	:global(html[data-pointer='coarse']) .timeline {
		width: 100%;
		gap: 6px;
	}
	:global(html[data-pointer='coarse']) .nav-btn {
		position: relative;
		width: 44px;
		height: 44px;
		min-width: 44px;
		min-height: 44px;
		border-color: transparent;
		background: transparent;
		isolation: isolate;
	}
	:global(html[data-pointer='coarse']) .nav-btn::before {
		content: '';
		position: absolute;
		z-index: -1;
		width: 36px;
		height: 36px;
		border: 1px solid color-mix(in srgb, var(--border, #333) 80%, transparent);
		border-radius: 50%;
		background: color-mix(in srgb, var(--surface, #111) 70%, transparent);
	}
	:global(html[data-pointer='coarse']) .nav-btn :global(svg) {
		position: relative;
		z-index: 1;
		width: 18px;
		height: 18px;
	}
</style>
