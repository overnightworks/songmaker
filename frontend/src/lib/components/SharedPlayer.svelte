<script lang="ts">
	import { onDestroy } from 'svelte';
	import { formatTime } from '$lib/utils/format';
	import Icon from './Icon.svelte';
	import {
		AudioVisualizer,
		FFT_SIZE,
		readVizColors,
		boxShadowStyle,
		titleGlowStyle,
		type VizColors
	} from '$lib/utils/visualizer';

	interface Props {
		audioUrl: string;
		title: string;
		subtitle?: string;
		autoplay?: boolean;
		onended?: () => void;
		onnext?: () => void;
		onprev?: () => void;
		onstatechange?: (playing: boolean, loading: boolean) => void;
	}

	let { audioUrl, title, subtitle, autoplay, onended, onnext, onprev, onstatechange }: Props =
		$props();

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
	let prevUrl: string | undefined = $state(undefined);
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);

	const viz = new AudioVisualizer();

	function ensureAudio(): HTMLAudioElement {
		if (audio) return audio;
		audio = new Audio();
		audio.crossOrigin = 'anonymous';
		audio.preload = 'auto';
		audio.src = audioUrl;

		audio.addEventListener('loadstart', () => (isLoading = true));
		audio.addEventListener('canplay', () => {
			isLoading = false;
			duration = audio?.duration ?? 0;
			connectAnalyser();
		});
		audio.addEventListener('timeupdate', () => {
			currentTime = audio?.currentTime ?? 0;
		});
		audio.addEventListener('ended', () => {
			isPlaying = false;
			stopVisualizerLoop();
			onended?.();
		});
		audio.addEventListener('play', () => {
			isPlaying = true;
			startVisualizerLoop();
		});
		audio.addEventListener('pause', () => {
			isPlaying = false;
			stopVisualizerLoop();
		});

		return audio;
	}

	function requestPlay(el: HTMLAudioElement): void {
		el.play().catch(() => {
			isPlaying = false;
			isLoading = false;
		});
	}

	export function loadAndPlay(nextUrl: string = audioUrl): void {
		const el = ensureAudio();
		if (el.src !== new URL(nextUrl, window.location.href).href) {
			el.src = nextUrl;
			el.load();
		}
		prevUrl = nextUrl;
		currentTime = 0;
		duration = 0;
		isLoading = true;
		requestPlay(el);
	}

	function connectAnalyser(): void {
		if (!audio || audioCtx) return;
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
		if (!vizCanvas || !analyser || !frequencyData || !waveformData) return;
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

	$effect(() => {
		if (audioUrl === prevUrl) return;
		const isInitial = prevUrl === undefined;
		prevUrl = audioUrl;
		if (isInitial && !autoplay) return;
		loadAndPlay(audioUrl);
	});

	$effect(() => {
		onstatechange?.(isPlaying, isLoading);
	});

	export function togglePlay(): void {
		const el = ensureAudio();
		if (isLoading) return;
		if (el.paused) requestPlay(el);
		else el.pause();
	}

	function seek(e: MouseEvent): void {
		if (!audio || duration <= 0) return;
		const el = e.currentTarget as HTMLElement;
		const rect = el.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		audio.currentTime = ratio * duration;
	}

	function seekFromRange(e: Event): void {
		if (!audio || duration <= 0) return;
		audio.currentTime = Number((e.currentTarget as HTMLInputElement).value);
	}

	onDestroy(() => {
		viz.destroy();
		if (audio) {
			audio.pause();
			audio.src = '';
		}
		if (audioCtx) audioCtx.close();
	});
</script>

<div class="shared-player" style={isPlaying ? boxShadowStyle(energyLevel, vizColors) : ''}>
	<canvas class="viz-canvas" bind:this={vizCanvas}></canvas>
	<div class="player-content">
		<div class="player-controls">
			{#if onprev}
				<button class="nav-btn" onclick={onprev} aria-label="Previous" title="Previous">
					<Icon name="skip-back" size={21} />
				</button>
			{/if}
			<button
				class="play-btn"
				class:loading={isLoading}
				class:playing={isPlaying}
				onclick={togglePlay}
				disabled={isLoading}
				aria-label={isPlaying ? 'Pause' : 'Play'}
				style={isPlaying ? `transform: scale(${1 + bassLevel * 0.15})` : ''}
			>
				{#if isLoading}<span class="spinner"></span>{:else}<Icon
						name={isPlaying ? 'pause' : 'play'}
						size={26}
					/>{/if}
			</button>
			{#if onnext}
				<button class="nav-btn" onclick={onnext} aria-label="Next" title="Next">
					<Icon name="skip-forward" size={21} />
				</button>
			{/if}
		</div>
		<div class="track-info">
			<span
				class="track-title"
				class:glowing={isPlaying}
				style={isPlaying ? titleGlowStyle(bassLevel, vizColors) : ''}>{title}</span
			>
			{#if subtitle}
				<span class="track-detail">{subtitle}</span>
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
		padding: 10px 18px;
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

	.play-btn:hover:not(:disabled) {
		background: linear-gradient(135deg, var(--primary, #ff3220), var(--accent, #a020f0));
		border-color: transparent;
		color: #fff;
	}

	.play-btn:disabled {
		opacity: 0.5;
		cursor: wait;
	}

	.play-btn.loading {
		border-color: var(--text-dim, #444);
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
			padding: 8px 10px;
		}

		.player-content {
			grid-template-columns: auto minmax(120px, 1fr);
			gap: 10px;
		}

		.track-info {
			display: none;
		}

		.nav-btn {
			width: 40px;
			height: 40px;
		}

		.play-btn {
			width: 56px;
			height: 56px;
		}
	}

	@media (max-width: 640px) {
		.player-content {
			display: flex;
			flex-direction: column;
			gap: 6px;
		}

		.player-controls {
			justify-content: center;
			gap: 6px;
			width: 100%;
		}

		.timeline {
			width: 100%;
			gap: 6px;
		}

		.nav-btn {
			width: 38px;
			height: 38px;
		}

		.play-btn {
			width: 48px;
			height: 48px;
		}

		.time {
			font-size: 0.7rem;
			min-width: 28px;
		}
	}
</style>
