<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		playingGeneration,
		playback,
		playbackTime,
		playbackDuration,
		navigateToPlaying,
		isAudioPlaying,
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
	import WaveSurfer from 'wavesurfer.js';

	let waveContainer: HTMLDivElement | undefined = $state();
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

	function createWavesurfer(): void {
		if (!waveContainer) return;
		wavesurfer?.destroy();
		wavesurfer = WaveSurfer.create({
			container: waveContainer,
			height: 40,
			waveColor: '#444',
			progressColor: '#ff3220',
			cursorColor: '#ff3220',
			cursorWidth: 1,
			barWidth: 2,
			barGap: 1,
			barRadius: 1,
			normalize: true,
			hideScrollbar: true,
			interact: true
		});

		wavesurfer.on('loading', () => {
			isLoading = true;
		});

		wavesurfer.on('ready', () => {
			isLoading = false;
			duration = wavesurfer?.getDuration() ?? 0;
			playbackDuration.set(duration);
		});

		wavesurfer.on('timeupdate', (time: number) => {
			currentTime = time;
			playbackTime.set(time);
		});

		wavesurfer.on('finish', handleEnded);
		wavesurfer.on('play', () => {
			isPlaying = true;
			isAudioPlaying.set(true);
		});
		wavesurfer.on('pause', () => {
			isPlaying = false;
			isAudioPlaying.set(false);
		});
	}

	$effect(() => {
		if (!gen || !waveContainer) return;
		if (gen.mp3_path !== prevFile) {
			prevFile = gen.mp3_path;
			isLoading = true;
			if (!wavesurfer) createWavesurfer();
			try {
				wavesurfer?.load(`/audio/${gen.mp3_path}`);
			} catch {
				// AbortError when rapidly switching tracks — harmless
			}
			if (pb?.autoplay) {
				wavesurfer?.once('ready', () => wavesurfer?.play());
			}
		}
	});

	let prevToggle = 0;
	$effect(() => {
		if (toggleRequest !== prevToggle) {
			prevToggle = toggleRequest;
			if (wavesurfer) wavesurfer.playPause();
		}
	});

	onDestroy(() => {
		wavesurfer?.destroy();
	});

	function togglePlay(): void {
		if (!gen || !wavesurfer || isLoading) return;
		wavesurfer.playPause();
	}

	function handleEnded(): void {
		isPlaying = false;
		isAudioPlaying.set(false);
		playNextGeneration();
	}
</script>

<footer class="player-bar">
	<div class="player-controls">
		<button
			class="nav-btn"
			onclick={playPrevSong}
			disabled={!prevSong}
			aria-label="Previous song"
			title="Previous song">⏮</button
		>
		<button
			class="nav-btn"
			onclick={playPrevGeneration}
			disabled={!prevGen}
			aria-label="Previous generation"
			title="Previous generation">⏪</button
		>
		<button
			class="play-btn"
			class:loading={isLoading}
			onclick={togglePlay}
			disabled={isLoading}
			aria-label={isPlaying ? 'Pause' : 'Play'}
		>
			{#if isLoading}
				<span class="spinner"></span>
			{:else}
				{isPlaying ? '⏸' : '▶'}
			{/if}
		</button>
		<button
			class="nav-btn"
			onclick={playNextGeneration}
			disabled={!nextGen}
			aria-label="Next generation"
			title="Next generation">⏩</button
		>
		<button
			class="nav-btn"
			onclick={playNextSong}
			disabled={!nextSong}
			aria-label="Next song"
			title="Next song">⏭</button
		>
	</div>

	<button class="track-info" onclick={navigateToPlaying} aria-label="Go to playing song">
		{#if pb}
			<span class="track-title">{pb.songTitle}</span>
			<span class="track-detail">
				{pb.artist} · gen{gen?.generation_number}
				{#if isLoading}<span class="loading-text">Loading...</span>{/if}
			</span>
		{/if}
	</button>

	<span class="time">{formatTime(currentTime)}</span>
	<div class="waveform" bind:this={waveContainer}></div>
	<span class="time">{formatTime(duration)}</span>
</footer>

<style>
	.player-bar {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		height: var(--player-height);
		background: #0a0a0a;
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 16px;
		z-index: 100;
	}

	.player-controls {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
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

	.spinner {
		width: 16px;
		height: 16px;
		border: 2px solid var(--text-dim);
		border-top-color: var(--primary);
		border-radius: 50%;
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

	.track-info:hover {
		background: var(--surface-hover);
	}

	.track-title {
		font-family: var(--font-display);
		font-size: 13px;
		color: #fff;
		text-transform: uppercase;
		letter-spacing: 1px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
	}

	.waveform {
		flex: 1;
		min-width: 80px;
		height: 40px;
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
