<script lang="ts">
	import AgeStamp from './AgeStamp.svelte';
	import { selectedSongId } from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { selectSong } from '$lib/stores/navigation';
	import type { SongItem } from '$lib/api/types';

	interface Props {
		song: SongItem;
	}

	let { song }: Props = $props();

	const activeSongId = $derived($selectedSongId);

	const isPlaying = $derived(
		audioPlayer.current?.songId === song.id && audioPlayer.status === 'playing'
	);
</script>

<div
	class="song-row"
	class:active={song.id === activeSongId}
	class:playing={isPlaying}
	onclick={() => selectSong(song.id)}
	onkeydown={(e) => e.key === 'Enter' && selectSong(song.id)}
	role="button"
	tabindex="0"
>
	<span class="song-name">{song.title}</span>
	<AgeStamp createdAt={song.created_at} />
	<span class="song-meta">
		{song.generation_count} gen{song.generation_count !== 1 ? 's' : ''}
	</span>
</div>

<style>
	.song-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px 8px 28px;
		color: var(--text);
		font-size: 0.87rem;
		cursor: pointer;
		border-top: 1px solid var(--surface-hover);
	}

	.song-row:hover {
		background: var(--surface-hover);
	}

	.song-row.active {
		background: rgba(160, 32, 240, 0.06);
		border-left: 3px solid var(--accent);
		padding-left: 25px;
	}

	.song-row.playing {
		background: rgba(160, 32, 240, 0.1);
	}

	@media (prefers-reduced-motion: no-preference) {
		.song-row.active {
			animation: select-flash 0.4s ease-out;
		}
	}

	@keyframes select-flash {
		0% {
			background: rgba(160, 32, 240, 0.2);
		}
		100% {
			background: rgba(160, 32, 240, 0.06);
		}
	}

	.song-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.song-meta {
		font-size: 0.7rem;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	@media (max-width: 768px) {
		.song-row {
			padding: 10px 12px 10px 24px;
			font-size: 1rem;
		}
	}
</style>
