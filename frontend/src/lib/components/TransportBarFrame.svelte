<script lang="ts">
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { NOW_PLAYING_LABEL } from '$lib/constants';
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
		isPlaying: boolean;
		isLoading: boolean;
		isError: boolean;
		errorMsg?: string | null;
		currentTime: number;
		duration: number;
		formatTime: (seconds: number) => string;
		canPrev: boolean;
		canNext: boolean;
		onPrev: () => void;
		onNext: () => void;
		onTogglePlay: () => void;
		onSeek: (seconds: number) => void;
		trackInfo: Snippet<[titleGlowStyle: string]>;
		nowPlayingOpen: boolean;
		onOpenNowPlaying: () => void;
		nowPlayingDisabled: boolean;
		onNowPlayingTriggerBind?: (el: HTMLButtonElement | undefined) => void;
		mobileTransport: boolean;
	}

	let {
		isPlaying,
		isLoading,
		isError,
		errorMsg = null,
		currentTime,
		duration,
		formatTime,
		canPrev,
		canNext,
		onPrev,
		onNext,
		onTogglePlay,
		onSeek,
		trackInfo,
		nowPlayingOpen,
		onOpenNowPlaying,
		nowPlayingDisabled,
		onNowPlayingTriggerBind,
		mobileTransport
	}: Props = $props();

	let nowPlayingTrigger: HTMLButtonElement | undefined = $state();
	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let audioCtx: AudioContext | undefined;
	let analyser: AnalyserNode | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let bassLevel = $state(0);
	let energyLevel = $state(0);
	let vizColors: VizColors = $state({ pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 });

	const viz = new AudioVisualizer();
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);
	const boxShadow = $derived(isPlaying ? boxShadowStyle(energyLevel, vizColors) : '');
	const playFaceStyle = $derived(isPlaying ? `transform: scale(${1 + bassLevel * 0.15})` : '');
	const trackTitleGlowStyle = $derived(isPlaying ? titleGlowStyle(bassLevel, vizColors) : '');

	$effect(() => {
		onNowPlayingTriggerBind?.(nowPlayingTrigger);
	});

	$effect(() => {
		const playing = isPlaying;
		untrack(() => {
			if (playing) startVisualizerLoop();
			else stopVisualizerLoop();
		});
	});

	function connectAnalyser(): void {
		const audio = audioPlayer.getElement();
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
		} catch (e) {
			console.warn('Audio visualizer unavailable:', e);
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
		if (!vizCanvas) return;
		viz.stopLoop(vizCanvas);
	}

	function handleVisibilityChange(): void {
		if (document.hidden) {
			stopVisualizerLoop();
			return;
		}
		if (isPlaying) startVisualizerLoop();
	}

	function seekFromClick(e: MouseEvent, el?: HTMLElement): void {
		if (duration <= 0) return;
		const target = el ?? (e.currentTarget as HTMLElement);
		const rect = target.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		onSeek(ratio * duration);
	}

	function seekFromRange(e: Event): void {
		const target = e.currentTarget as HTMLInputElement;
		onSeek(Number(target.value));
	}

	onDestroy(() => {
		viz.destroy();
		if (audioCtx) audioCtx.close();
	});
</script>

<svelte:document onvisibilitychange={handleVisibilityChange} />

<footer
	class="player-bar"
	class:now-playing-open={nowPlayingOpen}
	class:mobile-transport={mobileTransport}
	style={boxShadow}
>
	<canvas class="viz-fullscreen" bind:this={vizCanvas}></canvas>
	<div class="mobile-progress" aria-hidden="true">
		<div class="mobile-progress-fill" style:width="{progressPercent}%"></div>
	</div>
	<div class="player-content">
		<div class="transport-controls">
			<button
				class="nav-btn"
				onclick={onPrev}
				disabled={!canPrev}
				aria-label="Previous"
				title="Previous"
			>
				<Icon name="skip-back" size={21} />
			</button>
			<button
				class="play-btn"
				class:loading={isLoading}
				class:playing={isPlaying}
				class:errored={isError}
				onclick={onTogglePlay}
				aria-label={isError ? 'Retry' : isPlaying ? 'Pause' : 'Play'}
				title={isError && errorMsg ? errorMsg : ''}
			>
				<span class="play-btn-face" style={playFaceStyle}>
					{#if isLoading}<span class="spinner"></span>{:else if isError}<Icon
							name="refresh-cw"
							size={24}
						/>{:else}<Icon name={isPlaying ? 'pause' : 'play'} size={26} />{/if}
				</span>
			</button>
			<button class="nav-btn" onclick={onNext} disabled={!canNext} aria-label="Next" title="Next">
				<Icon name="skip-forward" size={21} />
			</button>
		</div>
		<div class="track-info" aria-live="polite">
			{@render trackInfo(trackTitleGlowStyle)}
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
				onclick={(e) => seekFromClick(e)}
				disabled={duration <= 0}
				aria-label="Seek playback"
			/>
			<span class="time">{formatTime(duration)}</span>
		</div>
		<button
			bind:this={nowPlayingTrigger}
			class="now-playing-btn"
			onclick={onOpenNowPlaying}
			disabled={nowPlayingDisabled}
			aria-label={NOW_PLAYING_LABEL}
			aria-haspopup="dialog"
			aria-expanded={nowPlayingOpen}
		>
			<span>{NOW_PLAYING_LABEL}</span>
			<Icon name="chevron-up" size={16} />
		</button>
	</div>
</footer>

<style>
	.player-bar {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		height: var(--player-height);
		background: var(--card-bg);
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		padding: 10px 18px calc(10px + env(safe-area-inset-bottom, 0px));
		z-index: 100;
		overflow: hidden;
		transition: box-shadow 0.3s;
	}
	.player-bar.now-playing-open {
		overflow: visible;
	}
	.player-content {
		position: relative;
		z-index: 1;
		display: grid;
		grid-template-columns: auto minmax(120px, 240px) minmax(100px, 1fr) auto;
		align-items: center;
		gap: 14px;
		width: 100%;
		min-width: 0;
	}
	.transport-controls {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}
	.play-btn {
		width: 62px;
		height: 62px;
		border-radius: 50%;
		border: 2px solid var(--primary);
		background: color-mix(in srgb, var(--surface) 72%, transparent);
		color: var(--primary);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		cursor: pointer;
		position: relative;
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
		background: linear-gradient(135deg, var(--primary), var(--accent));
		border-color: transparent;
		color: #fff;
	}
	.play-btn.loading {
		border-color: var(--text-decoration);
	}
	.play-btn.playing {
		border-color: var(--accent);
	}
	.play-btn.errored {
		border-color: #d34;
		color: #d34;
	}
	@supports (animation-timeline: auto) or (background-clip: border-box) {
		@media (prefers-reduced-motion: no-preference) {
			.play-btn.playing {
				border-color: transparent;
				background-origin: border-box;
				background-clip: padding-box, border-box;
				background-image:
					linear-gradient(var(--header-bg), var(--header-bg)),
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
	.nav-btn {
		width: 44px;
		height: 44px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
		border-radius: 50%;
		color: var(--text-muted);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		flex-shrink: 0;
		transition:
			background 0.15s,
			border-color 0.15s,
			color 0.15s,
			opacity 0.15s;
	}
	.nav-btn:hover:not(:disabled) {
		color: var(--text);
		border-color: color-mix(in srgb, var(--primary) 65%, var(--border));
		background: color-mix(in srgb, var(--primary) 12%, var(--surface));
	}
	.nav-btn:disabled {
		color: var(--text-disabled);
		cursor: default;
		opacity: 0.3;
	}
	.track-info {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
		overflow: hidden;
	}
	.timeline {
		display: grid;
		grid-template-columns: auto minmax(80px, 1fr) auto;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	.time {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		color: var(--text-muted);
		min-width: 36px;
		text-align: center;
		flex-shrink: 0;
	}

	.timeline-range {
		--track-bg: color-mix(in srgb, var(--border) 45%, transparent);
		appearance: none;
		-webkit-appearance: none;
		width: 100%;
		height: 34px;
		background: transparent;
		cursor: pointer;
		accent-color: var(--accent);
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
			var(--primary) 0%,
			var(--accent) var(--progress),
			var(--track-bg) var(--progress),
			var(--track-bg) 100%
		);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 55%, transparent);
	}
	.timeline-range::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid var(--card-bg);
		background: var(--text);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent);
		margin-top: -5px;
	}
	.timeline-range:hover:not(:disabled)::-webkit-slider-thumb {
		background: #fff;
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent) 30%, transparent);
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
		border: 2px solid var(--card-bg);
		background: var(--text);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent);
	}
	.now-playing-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
		padding: 0.4rem 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
		white-space: nowrap;
	}
	.now-playing-btn:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}
	.now-playing-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.viz-fullscreen {
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		bottom: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		z-index: 0;
	}
	.mobile-progress {
		display: none;
	}
	.mobile-progress-fill {
		height: 100%;
		background: linear-gradient(90deg, var(--primary), var(--accent));
	}

	@media (max-width: 900px) {
		.player-bar {
			padding: 8px 10px calc(8px + env(safe-area-inset-bottom, 0px));
		}
		.player-content {
			grid-template-columns: auto minmax(80px, 1fr) minmax(90px, 1fr) auto;
			gap: 10px;
		}
		.nav-btn {
			width: 40px;
			height: 40px;
		}
		.play-btn {
			width: 56px;
			height: 56px;
		}
		.now-playing-btn span {
			display: none;
		}
	}

	/* One 64px transport row on mobile / coarse pointers: cover, title,
	   play/pause, and the Now Playing chevron. Prev/Next move into the Now
	   Playing overlay — see NowPlaying.svelte — and the interactive seek
	   timeline is replaced by the decorative .mobile-progress line above.
	   `.mobile-transport` is set from `subscribeCompactLayout` (JS mirrors
	   the same media query so jsdom tests can drive it via data-pointer). */
	.player-bar.mobile-transport {
		overflow: visible;
		padding: 0 14px env(safe-area-inset-bottom, 0px);
	}
	.mobile-transport .mobile-progress {
		display: block;
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		height: 2px;
		background: color-mix(in srgb, var(--border) 45%, transparent);
		z-index: 2;
	}
	.mobile-transport .player-content {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.mobile-transport .track-info {
		order: 1;
		flex: 1;
		width: auto;
		min-width: 0;
	}
	.mobile-transport .transport-controls {
		order: 2;
		flex-shrink: 0;
	}
	.mobile-transport .nav-btn {
		display: none;
	}
	.mobile-transport .play-btn {
		width: 44px;
		height: 44px;
		min-width: 44px;
		min-height: 44px;
	}
	.mobile-transport .play-btn-face {
		transform: none !important;
	}
	.mobile-transport .now-playing-btn {
		order: 3;
		flex-shrink: 0;
	}
	.mobile-transport .timeline {
		display: none;
	}
</style>
