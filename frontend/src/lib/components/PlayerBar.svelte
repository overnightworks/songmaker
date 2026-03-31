<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		playingGeneration,
		playback,
		playbackTime,
		playbackDuration,
		navigateToPlaying,
		isAudioPlaying,
		isAudioBuffering,
		requestTogglePlay,
		playNextGeneration,
		playPrevGeneration,
		playNextSong,
		playPrevSong,
		canPlayPrevGen,
		canPlayNextGen,
		canPlayPrevSong,
		canPlayNextSong
	} from '$lib/stores/player';
	import { formatTime } from '$lib/utils/format';
	import {
		AudioVisualizer,
		FFT_SIZE,
		readVizColors,
		boxShadowStyle,
		titleGlowStyle,
		type VizColors
	} from '$lib/utils/visualizer';
	import WaveSurfer from 'wavesurfer.js';

	let waveContainer: HTMLDivElement | undefined = $state();
	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let wavesurfer: WaveSurfer | undefined = $state();
	let isPlaying = $state(false);
	let isLoading = $state(false);
	const toggleRequest = $derived($requestTogglePlay);
	let currentTime = $state(0);
	let duration = $state(0);

	const gen = $derived($playingGeneration);
	const pb = $derived($playback);
	const prevGen = $derived($canPlayPrevGen);
	const nextGen = $derived($canPlayNextGen);
	const prevSong = $derived($canPlayPrevSong);
	const nextSong = $derived($canPlayNextSong);

	let prevFile = $state('');
	let loadedFile = $state('');

	let audioCtx: AudioContext | undefined;
	let analyser: AnalyserNode | undefined;
	let sourceNode: MediaElementAudioSourceNode | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let bassLevel = $state(0);
	let energyLevel = $state(0);
	let vizColors: VizColors = $state({ pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 });

	const viz = new AudioVisualizer();

	function connectAnalyser(): void {
		if (!wavesurfer || audioCtx) return;
		try {
			const media = wavesurfer.getMediaElement();
			if (!media) return;
			audioCtx = new AudioContext();
			analyser = audioCtx.createAnalyser();
			analyser.fftSize = FFT_SIZE;
			analyser.smoothingTimeConstant = 0.82;
			sourceNode = audioCtx.createMediaElementSource(media);
			sourceNode.connect(analyser);
			analyser.connect(audioCtx.destination);
			frequencyData = new Uint8Array(analyser.frequencyBinCount) as Uint8Array<ArrayBuffer>;
			waveformData = new Uint8Array(analyser.fftSize) as Uint8Array<ArrayBuffer>;
		} catch {
			/* Already connected */
		}
	}

	function startVisualizerLoop(): void {
		if (!vizCanvas) return;
		if (!audioCtx) connectAnalyser();
		if (!analyser || !frequencyData || !waveformData) return;
		if (audioCtx?.state === 'suspended') audioCtx.resume();
		vizColors = readVizColors();
		viz.startLoop(vizCanvas, analyser, frequencyData, waveformData, vizColors);
		syncVizLevels();
	}

	function syncVizLevels(): void {
		bassLevel = viz.bassLevel;
		energyLevel = viz.energyLevel;
		if (isPlaying) requestAnimationFrame(syncVizLevels);
	}

	function stopVisualizerLoop(): void {
		if (!vizCanvas) return;
		viz.stopLoop(vizCanvas);
	}

	function handleCanvasClick(e: MouseEvent): void {
		if (!vizCanvas || !wavesurfer || duration <= 0) return;
		const rect = vizCanvas.getBoundingClientRect();
		wavesurfer.seekTo(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)));
	}

	function handleProgressClick(e: MouseEvent): void {
		if (!wavesurfer || duration <= 0) return;
		const bar = e.currentTarget as HTMLElement;
		const rect = bar.getBoundingClientRect();
		wavesurfer.seekTo(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)));
	}

	function createWavesurfer(): void {
		if (!waveContainer) return;
		wavesurfer?.destroy();
		wavesurfer = WaveSurfer.create({
			container: waveContainer,
			height: 0,
			waveColor: 'transparent',
			progressColor: 'transparent',
			cursorColor: 'transparent',
			cursorWidth: 0,
			normalize: true,
			hideScrollbar: true,
			interact: false
		});
		wavesurfer.on('loading', () => {
			isLoading = true;
			isAudioBuffering.set(true);
		});
		wavesurfer.on('ready', () => {
			isLoading = false;
			isAudioBuffering.set(false);
			loadedFile = prevFile;
			duration = wavesurfer?.getDuration() ?? 0;
			playbackDuration.set(duration);
			connectAnalyser();
		});
		wavesurfer.on('timeupdate', (time: number) => {
			currentTime = time;
			playbackTime.set(time);
		});
		wavesurfer.on('finish', handleEnded);
		wavesurfer.on('play', () => {
			isPlaying = true;
			isAudioPlaying.set(true);
			startVisualizerLoop();
		});
		wavesurfer.on('pause', () => {
			isPlaying = false;
			isAudioPlaying.set(false);
			stopVisualizerLoop();
		});
	}

	let pendingAutoplay: (() => void) | null = null;

	$effect(() => {
		if (!gen || !waveContainer) return;
		if (gen.mp3_path !== prevFile) {
			prevFile = gen.mp3_path;
			isLoading = true;
			isAudioBuffering.set(true);
			if (!wavesurfer) createWavesurfer();
			wavesurfer?.pause();
			isPlaying = false;
			isAudioPlaying.set(false);
			if (pendingAutoplay) {
				wavesurfer?.un('ready', pendingAutoplay);
				pendingAutoplay = null;
			}
			try {
				wavesurfer?.load(`/audio/${gen.mp3_path}`);
			} catch {
				/* harmless */
			}
			if (pb?.autoplay) {
				pendingAutoplay = () => wavesurfer?.play();
				wavesurfer?.once('ready', pendingAutoplay);
			}
		}
	});

	let prevToggle = 0;
	$effect(() => {
		if (toggleRequest !== prevToggle) {
			prevToggle = toggleRequest;
			if (wavesurfer && !isLoading && loadedFile === gen?.mp3_path) {
				wavesurfer.playPause();
			}
		}
	});

	onDestroy(() => {
		viz.destroy();
		wavesurfer?.destroy();
		if (audioCtx) audioCtx.close();
	});

	function togglePlay(): void {
		if (!gen || !wavesurfer || isLoading) return;
		wavesurfer.playPause();
	}

	function handleEnded(): void {
		isPlaying = false;
		isAudioPlaying.set(false);
		stopVisualizerLoop();
		playNextGeneration();
	}
</script>

<footer class="player-bar" style={isPlaying ? boxShadowStyle(energyLevel, vizColors) : ''}>
	<div class="player-controls">
		<button
			class="nav-btn"
			onclick={playPrevSong}
			disabled={!prevSong}
			aria-label="Previous song"
			title="Previous song"
			><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"
				><rect x="3" y="5" width="3" height="14" /><polygon points="20,5 9,12 20,19" /></svg
			></button
		>
		<button
			class="nav-btn"
			onclick={playPrevGeneration}
			disabled={!prevGen}
			aria-label="Previous generation"
			title="Previous generation"
			><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"
				><polygon points="12,5 2,12 12,19" /><polygon points="22,5 12,12 22,19" /></svg
			></button
		>
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
		<button
			class="nav-btn"
			onclick={playNextGeneration}
			disabled={!nextGen}
			aria-label="Next generation"
			title="Next generation"
			><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"
				><polygon points="2,5 12,12 2,19" /><polygon points="12,5 22,12 12,19" /></svg
			></button
		>
		<button
			class="nav-btn"
			onclick={playNextSong}
			disabled={!nextSong}
			aria-label="Next song"
			title="Next song"
			><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"
				><polygon points="4,5 15,12 4,19" /><rect x="18" y="5" width="3" height="14" /></svg
			></button
		>
	</div>
	<button class="track-info" onclick={navigateToPlaying} aria-label="Go to playing song">
		{#if pb}
			<span
				class="track-title"
				class:glowing={isPlaying}
				style={isPlaying ? titleGlowStyle(bassLevel, vizColors) : ''}>{pb.songTitle}</span
			>
			<span class="track-detail"
				>{pb.artist} · gen{gen?.generation_number}{#if isLoading}<span class="loading-text"
						>Loading...</span
					>{/if}</span
			>
		{/if}
	</button>
	<span class="time">{formatTime(currentTime)}</span>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="viz-area" onclick={handleCanvasClick}>
		<div class="wave-hidden" bind:this={waveContainer}></div>
	</div>
	<span class="time">{formatTime(duration)}</span>
	<canvas class="viz-fullscreen" bind:this={vizCanvas}></canvas>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="progress-bar" onclick={handleProgressClick}>
		<div
			class="progress-fill"
			style="width: {duration > 0 ? (currentTime / duration) * 100 : 0}%"
		></div>
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
		gap: 12px;
		padding: 0 16px;
		z-index: 100;
		overflow: visible;
	}
	.player-controls {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
		z-index: 1;
	}
	.play-btn {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 2px solid var(--primary);
		background: transparent;
		color: var(--primary);
		font-size: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		cursor: pointer;
		position: relative;
		transition: border-color 0.3s;
	}
	.play-btn:hover:not(:disabled) {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		border-color: transparent;
		color: #fff;
	}
	.play-btn:disabled {
		opacity: 0.5;
		cursor: wait;
	}
	.play-btn.loading {
		border-color: var(--text-dim);
	}
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
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 14px;
		cursor: pointer;
		padding: 6px;
		display: flex;
		align-items: center;
		min-width: 32px;
		min-height: 32px;
		justify-content: center;
	}
	.nav-btn:hover:not(:disabled) {
		color: var(--text);
	}
	.nav-btn:disabled {
		color: var(--text-dim);
		cursor: default;
		opacity: 0.3;
	}
	.track-info {
		display: flex;
		flex-direction: column;
		min-width: 100px;
		max-width: 200px;
		overflow: hidden;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		padding: 4px 8px;
		border-radius: 4px;
		flex-shrink: 0;
	}
	.track-info {
		z-index: 1;
	}
	.track-info:hover {
		background: var(--surface-hover);
	}
	.track-title {
		font-family: var(--font-display);
		font-size: 13px;
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
		font-size: 10px;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.loading-text {
		color: var(--primary);
		margin-left: 4px;
	}
	.time {
		font-family: var(--font-display);
		font-size: 12px;
		color: var(--text-muted);
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
	.wave-hidden {
		position: absolute;
		width: 0;
		height: 0;
		overflow: hidden;
		pointer-events: none;
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
		background: color-mix(in srgb, var(--border) 30%, transparent);
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
		.player-bar {
			gap: 8px;
			padding: 0 8px;
		}
		.track-info {
			display: none;
		}
		.nav-btn {
			font-size: 12px;
			min-width: 28px;
			min-height: 28px;
			padding: 4px;
		}
		.time {
			font-size: 10px;
			min-width: 28px;
		}
	}
</style>
