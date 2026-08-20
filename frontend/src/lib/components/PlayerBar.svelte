<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import {
		navigateToPlaying,
		playNextSong,
		playPrevSong,
		canPlayPrevSong,
		canPlayNextSong,
		queueContext,
		retryLastPlayIntent,
		songList,
		shuffleEnabled,
		toggleShuffle
	} from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		updateMediaSessionPlaybackState,
		updateMediaSessionPositionState
	} from '$lib/services/mediaSession';
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

	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let audioCtx: AudioContext | undefined;
	let analyser: AnalyserNode | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let bassLevel = $state(0);
	let energyLevel = $state(0);
	let vizColors: VizColors = $state({ pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 });

	const viz = new AudioVisualizer();

	const current = $derived(audioPlayer.current);
	const status = $derived(audioPlayer.status);
	const errorMsg = $derived(audioPlayer.error);
	const currentTime = $derived(audioPlayer.currentTime);
	const duration = $derived(audioPlayer.duration);
	const shuffle = $derived($shuffleEnabled);

	const isPlaying = $derived(status === 'playing');
	const isLoading = $derived(status === 'loading' || status === 'buffering');
	const isError = $derived(status === 'error');

	const songs = $derived($songList);
	const ctx = $derived($queueContext);
	const prevSong = $derived(canPlayPrevSong(current, songs, ctx));
	const nextSong = $derived(canPlayNextSong(current, songs, ctx, shuffle));
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);

	$effect(() => {
		const playing = isPlaying;
		untrack(() => {
			if (playing) startVisualizerLoop();
			else stopVisualizerLoop();
		});
	});

	$effect(() => {
		updateMediaSessionPlaybackState(isPlaying ? 'playing' : current ? 'paused' : 'none');
		updateMediaSessionPositionState(currentTime, duration);
	});

	function visualizerAllowed(): boolean {
		if (typeof window === 'undefined') return false;
		if (document.hidden) return false;
		return !window.matchMedia('(max-width: 640px)').matches;
	}

	function connectAnalyser(): void {
		const audio = audioPlayer.getElement();
		if (!audio || audioCtx) return;
		if (!visualizerAllowed()) return;
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
		if (!visualizerAllowed()) return;
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
		audioPlayer.seek(ratio * duration);
	}

	function seekFromRange(e: Event): void {
		const target = e.currentTarget as HTMLInputElement;
		audioPlayer.seek(Number(target.value));
	}

	onDestroy(() => {
		viz.destroy();
		if (audioCtx) audioCtx.close();
	});

	function togglePlay(): void {
		void retryLastPlayIntent().then((retried) => {
			if (!retried) audioPlayer.toggle();
		});
	}
</script>

<svelte:document onvisibilitychange={handleVisibilityChange} />

<footer class="player-bar" style={isPlaying ? boxShadowStyle(energyLevel, vizColors) : ''}>
	<canvas class="viz-fullscreen" bind:this={vizCanvas}></canvas>
	<div class="player-content">
		<div class="player-controls">
			<button
				class="nav-btn mode-btn"
				class:active={shuffle}
				onclick={toggleShuffle}
				aria-label={shuffle ? 'Disable shuffle' : 'Enable shuffle'}
				aria-pressed={shuffle}
				title="Shuffle"
			>
				<Icon name="shuffle" size={20} />
			</button>
			<button
				class="nav-btn"
				onclick={playPrevSong}
				disabled={!prevSong}
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
				onclick={togglePlay}
				aria-label={isError ? 'Retry' : isPlaying ? 'Pause' : 'Play'}
				title={isError && errorMsg ? errorMsg : ''}
			>
				<span
					class="play-btn-face"
					style={isPlaying ? `transform: scale(${1 + bassLevel * 0.15})` : ''}
				>
					{#if isLoading}<span class="spinner"></span>{:else if isError}<Icon
							name="refresh-cw"
							size={24}
						/>{:else}<Icon name={isPlaying ? 'pause' : 'play'} size={26} />{/if}
				</span>
			</button>
			<button
				class="nav-btn"
				onclick={playNextSong}
				disabled={!nextSong}
				aria-label="Next"
				title="Next"
			>
				<Icon name="skip-forward" size={21} />
			</button>
		</div>
		<button class="track-info" onclick={navigateToPlaying} aria-label="Go to playing song">
			{#if current}
				<span
					class="track-title"
					class:glowing={isPlaying}
					style={isPlaying ? titleGlowStyle(bassLevel, vizColors) : ''}>{current.songTitle}</span
				>
				<span class="track-detail"
					>{current.artist} · gen{current.generation.generation_number}{#if isLoading}<span
							class="loading-text">Loading...</span
						>{:else if isError}<span class="error-text">{errorMsg ?? 'Error'}</span>{/if}</span
				>
			{/if}
		</button>
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
	.player-content {
		position: relative;
		z-index: 1;
		display: grid;
		grid-template-columns: auto minmax(140px, 260px) minmax(180px, 1fr);
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
		border-color: var(--text-dim);
	}
	.play-btn.playing {
		border-color: var(--accent);
	}
	.play-btn.errored {
		border-color: #d34;
		color: #d34;
	}
	.error-text {
		color: #d34;
		margin-left: 4px;
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
	.nav-btn.active {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 70%, var(--border));
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	.nav-btn:disabled {
		color: var(--text-dim);
		cursor: default;
		opacity: 0.3;
	}
	.track-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
		background: none;
		border: 1px solid transparent;
		cursor: pointer;
		text-align: left;
		padding: 0.45rem 0.6rem;
		border-radius: var(--card-radius);
		color: inherit;
		transition:
			background 0.15s,
			border-color 0.15s;
	}
	.track-info:hover {
		background: var(--surface-hover);
		border-color: var(--border);
	}
	.track-title {
		font-family: var(--font-display);
		font-size: 0.95rem;
		color: var(--text);
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
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.loading-text {
		color: var(--primary);
		margin-left: 4px;
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

	@media (max-width: 900px) {
		.player-bar {
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
		.play-btn {
			width: 56px;
			height: 56px;
		}
	}

	@media (max-width: 640px) {
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
		.track-info {
			display: flex;
			flex-direction: row;
			align-items: center;
			justify-content: center;
			gap: 0.5rem;
			width: 100%;
			text-align: center;
			padding: 0 0.25rem;
			white-space: nowrap;
		}
		.track-title {
			font-size: 0.85rem;
			max-width: 55%;
			min-width: 0;
		}
		.track-detail {
			max-width: 45%;
			min-width: 0;
		}
		.timeline {
			width: 100%;
			gap: 6px;
		}
		.nav-btn {
			width: 44px;
			height: 44px;
			min-width: 44px;
			min-height: 44px;
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
</style>
