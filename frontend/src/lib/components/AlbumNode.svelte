<script lang="ts">
	import { playAlbum } from '$lib/stores/player';
	import SongNode from './SongNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';

	interface Props {
		album: AlbumItem;
		songs: SongItem[];
		expanded: boolean;
		ontoggle: () => void;
	}

	let { album, songs, expanded, ontoggle }: Props = $props();
</script>

<div class="album-group">
	<div
		class="album-header"
		class:expanded
		onclick={ontoggle}
		onkeydown={(e) => e.key === 'Enter' && ontoggle()}
		role="button"
		tabindex="0"
	>
		<span class="album-chevron">{expanded ? '▾' : '▸'}</span>
		<span class="album-title">{album.title}</span>
		<button
			class="album-play"
			onclick={(e) => {
				e.stopPropagation();
				playAlbum(album.id);
			}}
			title="Play album"
			aria-label="Play album {album.title}">▶</button
		>
		<span class="album-count">{songs.length}</span>
	</div>

	{#if expanded}
		{#each songs as song (song.id)}
			<SongNode {song} />
		{/each}
	{/if}
</div>

<style>
	.album-group {
		border-bottom: 1px solid var(--border);
	}

	.album-header {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 8px 12px;
		background: var(--surface);
		border: none;
		color: var(--text);
		font-size: 11px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
		cursor: pointer;
		text-align: left;
	}

	.album-header:hover {
		background: var(--surface-hover);
	}

	.album-chevron {
		font-size: 10px;
		color: var(--text-dim);
		width: 12px;
		flex-shrink: 0;
	}

	.album-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.album-play {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		cursor: pointer;
		padding: 2px 4px;
		flex-shrink: 0;
		opacity: 0;
		transition: opacity 0.15s;
	}

	.album-header:hover .album-play {
		opacity: 1;
	}

	.album-play:hover {
		color: var(--primary);
	}

	.album-count {
		font-size: 9px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	@media (max-width: 768px) {
		.album-header {
			padding: 10px 12px;
			font-size: 12px;
		}
	}
</style>
