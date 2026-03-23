<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		playingTrack,
		playback,
		playBrowsingTrack,
		nextTrack,
		albums,
		playbackTime,
		playbackDuration
	} from '$lib/stores/player';
	import { formatTime } from '$lib/utils/format';
	import WaveSurfer from 'wavesurfer.js';

	let waveContainer: HTMLDivElement | undefined = $state();
	let wavesurfer: WaveSurfer | undefined = $state();
	let isPlaying = $state(false);
	let currentTime = $state(0);
	let duration = $state(0);

	const track = $derived($playingTrack);
	const pb = $derived($playback);
	const allAlbums = $derived($albums);
	const albumArtist = $derived(pb ? (allAlbums[pb.albumIndex]?.artist ?? '') : '');

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
		wavesurfer.on('play', () => (isPlaying = true));
		wavesurfer.on('pause', () => (isPlaying = false));
	}

	$effect(() => {
		if (!track || !waveContainer) return;
		if (track.file !== prevFile) {
			prevFile = track.file;
			if (!wavesurfer) createWavesurfer();
			wavesurfer?.load(`/audio/${track.file}`);
			wavesurfer?.once('ready', () => wavesurfer?.play());
		}
	});

	onDestroy(() => {
		wavesurfer?.destroy();
	});

	function togglePlay(): void {
		if (!track) {
			playBrowsingTrack();
			return;
		}
		if (!wavesurfer) return;
		wavesurfer.playPause();
	}

	function handleEnded(): void {
		const advanced = nextTrack();
		if (advanced && wavesurfer) {
			wavesurfer.once('ready', () => wavesurfer?.play());
		}
	}
</script>

<footer class="player-bar">
	<button class="play-btn" onclick={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
		{isPlaying ? '⏸' : '▶'}
	</button>

	<div class="track-info">
		{#if track}
			<span class="track-title">{track.title}</span>
			<span class="track-artist">{albumArtist}</span>
		{:else}
			<span class="track-title">No track selected</span>
		{/if}
	</div>

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
