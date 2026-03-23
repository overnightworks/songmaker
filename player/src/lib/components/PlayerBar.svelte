<script lang="ts">
	import { currentTrack, currentAlbum, nextTrack } from '$lib/stores/player';
	import { formatTime } from '$lib/utils/format';

	let audioEl: HTMLAudioElement | undefined = $state();
	let isPlaying = $state(false);
	let currentTime = $state(0);
	let duration = $state(0);

	const track = $derived($currentTrack);
	const album = $derived($currentAlbum);

	let audioSrc = $derived(track ? `/audio/${track.file}` : '');

	let prevFile = $state('');

	$effect(() => {
		if (!audioEl || !track) return;
		if (track.file !== prevFile) {
			prevFile = track.file;
			audioEl.src = audioSrc;
			audioEl.load();
		}
	});

	function togglePlay(): void {
		if (!audioEl) return;
		if (isPlaying) {
			audioEl.pause();
		} else {
			audioEl.play();
		}
	}

	function seek(e: Event): void {
		if (!audioEl) return;
		const input = e.target as HTMLInputElement;
		audioEl.currentTime = parseFloat(input.value);
	}

	function handleEnded(): void {
		const advanced = nextTrack();
		if (advanced && audioEl) {
			audioEl.addEventListener('canplay', function onCanPlay() {
				audioEl?.removeEventListener('canplay', onCanPlay);
				audioEl?.play();
			});
		}
	}
</script>

<footer class="player-bar">
	<audio
		bind:this={audioEl}
		onplay={() => (isPlaying = true)}
		onpause={() => (isPlaying = false)}
		ontimeupdate={() => {
			if (audioEl) currentTime = audioEl.currentTime;
		}}
		onloadedmetadata={() => {
			if (audioEl) duration = audioEl.duration;
		}}
		onended={handleEnded}
		preload="auto"
	></audio>

	<button class="play-btn" onclick={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
		{isPlaying ? '⏸' : '▶'}
	</button>

	<div class="track-info">
		{#if track}
			<span class="track-title">{track.title}</span>
			<span class="track-artist">{album?.artist ?? ''}</span>
		{:else}
			<span class="track-title">No track selected</span>
		{/if}
	</div>

	<div class="progress-group">
		<span class="time">{formatTime(currentTime)}</span>
		<input
			type="range"
			class="progress-bar"
			min="0"
			max={duration || 0}
			step="0.1"
			value={currentTime}
			oninput={seek}
			aria-label="Seek"
		/>
		<span class="time">{formatTime(duration)}</span>
	</div>
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

	.progress-group {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.time {
		font-family: var(--font-display);
		font-size: 12px;
		color: var(--text-muted);
		min-width: 36px;
		text-align: center;
	}

	.progress-bar {
		flex: 1;
		-webkit-appearance: none;
		appearance: none;
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		outline: none;
	}

	.progress-bar::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--primary);
		cursor: pointer;
	}

	@media (max-width: 600px) {
		.track-info {
			display: none;
		}
	}
</style>
