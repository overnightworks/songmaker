<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		playingGeneration,
		playback,
		playbackTime,
		playbackDuration,
		navigateToPlaying,
		isAudioPlaying,
		requestTogglePlay
	} from '$lib/stores/player';
	import { formatTime } from '$lib/utils/format';
	import WaveSurfer from 'wavesurfer.js';

	let waveContainer: HTMLDivElement | undefined = $state();
	let wavesurfer: WaveSurfer | undefined = $state();
	let isPlaying = $state(false);
	const toggleRequest = $derived($requestTogglePlay);
	let currentTime = $state(0);
	let duration = $state(0);

	const gen = $derived($playingGeneration);
	const pb = $derived($playback);

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

		wavesurfer.on('timeupdate', (time: number) => {
			currentTime = time;
			playbackTime.set(time);
		});

		wavesurfer.on('ready', () => {
			duration = wavesurfer?.getDuration() ?? 0;
			playbackDuration.set(duration);
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
			if (!wavesurfer) createWavesurfer();
			wavesurfer?.load(`/audio/${gen.mp3_path}`);
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
		if (!gen || !wavesurfer) return;
		wavesurfer.playPause();
	}

	function handleEnded(): void {
		isPlaying = false;
		isAudioPlaying.set(false);
	}
</script>

<footer class="player-bar">
	<button class="play-btn" onclick={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
		{isPlaying ? '⏸' : '▶'}
	</button>

	<button class="track-info" onclick={navigateToPlaying} aria-label="Go to playing song">
		{#if pb}
			<span class="track-title">{pb.songTitle}</span>
			<span class="track-artist">{pb.artist}</span>
		{:else}
			<span class="track-title">No track selected</span>
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
		border-top: 1px solid var(--border);
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 16px;
		z-index: 100;
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
	}

	.play-btn:hover {
		background: var(--primary);
		color: #fff;
	}

	.track-info {
		display: flex;
		flex-direction: column;
		min-width: 120px;
		max-width: 200px;
		overflow: hidden;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		padding: 4px 8px;
		border-radius: 4px;
	}

	.track-info:hover {
		background: var(--surface-hover);
	}

	.track-title {
		font-family: var(--font-display);
		font-size: 14px;
		color: #fff;
		text-transform: uppercase;
		letter-spacing: 1px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.track-artist {
		font-size: 11px;
		color: var(--text-muted);
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
		min-width: 100px;
		height: 40px;
	}

	@media (max-width: 600px) {
		.track-info {
			display: none;
		}
	}
</style>
