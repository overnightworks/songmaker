<script lang="ts">
	import { onDestroy } from 'svelte';
	import { formatTime } from '$lib/utils/format';
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

	let prevUrl: string | undefined = $state(undefined);
	$effect(() => {
		if (audioUrl === prevUrl) return;
		const isInitial = prevUrl === undefined;
		prevUrl = audioUrl;
		if (isInitial && !autoplay) return;
		const el = ensureAudio();
		if (!isInitial) el.src = audioUrl;
		currentTime = 0;
		duration = 0;
		isLoading = true;
		el.play().catch(() => {});
	});

	$effect(() => {
		onstatechange?.(isPlaying, isLoading);
	});

	function togglePlay(): void {
		const el = ensureAudio();
		if (isLoading) return;
		if (el.paused) el.play().catch(() => {});
		else el.pause();
	}

	function seek(e: MouseEvent): void {
		if (!audio || duration <= 0) return;
		const el = e.currentTarget as HTMLElement;
		const rect = el.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		audio.currentTime = ratio * duration;
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
	{#if onprev}
		<button class="nav-btn" onclick={onprev} aria-label="Previous">⏮</button>
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
		{#if isLoading}<span class="spinner"></span>{:else}{isPlaying ? '⏸' : '▶'}{/if}
	</button>
	{#if onnext}
		<button class="nav-btn" onclick={onnext} aria-label="Next">⏭</button>
	{/if}
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
	<span class="time">{formatTime(currentTime)}</span>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="viz-area" onclick={seek}>
		<canvas class="viz-canvas" bind:this={vizCanvas}></canvas>
	</div>
	<span class="time">{formatTime(duration)}</span>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="progress-bar" onclick={seek}>
		<div
			class="progress-fill"
			style="width: {duration > 0 ? (currentTime / duration) * 100 : 0}%"
		></div>
	</div>
</div>

<style>
	.shared-player {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		height: 64px;
		background: var(--card-bg, #111);
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 16px;
		z-index: 100;
		overflow: visible;
		transition: box-shadow 0.3s;
	}

	.nav-btn {
		background: none;
		border: none;
		color: var(--text-muted, #888);
		font-size: 16px;
		cursor: pointer;
		padding: 4px;
		flex-shrink: 0;
		transition: color 0.15s;
	}

	.nav-btn:hover {
		color: var(--text, #e0e0e0);
	}

	.play-btn {
		width: 44px;
		height: 44px;
		border-radius: 50%;
		border: 2px solid var(--primary, #ff3220);
		background: transparent;
		color: var(--primary, #ff3220);
		font-size: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		cursor: pointer;
		transition:
			border-color 0.3s,
			transform 0.1s;
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
		width: 20px;
		height: 20px;
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
		min-width: 80px;
		max-width: 200px;
		overflow: hidden;
		flex-shrink: 0;
	}

	.track-title {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 13px;
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
		font-size: 10px;
		color: var(--text-muted, #888);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.time {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 12px;
		color: var(--text-muted, #888);
		min-width: 36px;
		text-align: center;
		flex-shrink: 0;
		z-index: 1;
	}

	.viz-area {
		flex: 1;
		min-width: 80px;
		height: 52px;
		position: relative;
		cursor: pointer;
	}

	.viz-canvas {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}

	.progress-bar {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		height: 12px;
		padding-top: 10px;
		background: transparent;
		z-index: 2;
		cursor: pointer;
	}

	.progress-bar::after {
		content: '';
		display: block;
		height: 2px;
		background: color-mix(in srgb, var(--border, #333) 30%, transparent);
		border-radius: 1px;
	}

	.progress-fill {
		height: 2px;
		margin-top: -2px;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		transition: width 0.1s linear;
		border-radius: 1px;
		position: relative;
		z-index: 1;
	}

	@media (max-width: 768px) {
		.shared-player {
			gap: 6px;
			padding: 0 8px;
		}

		.track-info {
			display: none;
		}

		.time {
			font-size: 10px;
			min-width: 28px;
		}
	}
</style>
