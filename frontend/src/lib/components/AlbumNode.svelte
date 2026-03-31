<script lang="ts">
	import SongNode from './SongNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';

	interface Props {
		album: AlbumItem;
		songs: SongItem[];
		expanded: boolean;
		selected: boolean;
		ontoggle: () => void;
		onselect: () => void;
	}

	let { album, songs, expanded, selected, ontoggle, onselect }: Props = $props();

	function handleClick(): void {
		if (!expanded) ontoggle();
		onselect();
	}
</script>

<div class="album-group">
	<div
		class="album-header"
		class:expanded
		class:selected
		onclick={handleClick}
		onkeydown={(e) => e.key === 'Enter' && handleClick()}
		role="button"
		tabindex="0"
	>
		<button
			class="album-chevron"
			onclick={(e) => {
				e.stopPropagation();
				ontoggle();
			}}
			aria-label={expanded ? 'Collapse' : 'Expand'}
		>
			{expanded ? '▾' : '▸'}
		</button>
		<span class="album-title">{album.title}</span>
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

	.album-header.selected {
		background: rgba(160, 32, 240, 0.06);
		border-left: 3px solid var(--accent);
		padding-left: 9px;
	}

	.album-chevron {
		background: none;
		border: none;
		font-size: 10px;
		color: var(--text-dim);
		width: 16px;
		flex-shrink: 0;
		cursor: pointer;
		padding: 0;
	}

	.album-chevron:hover {
		color: var(--text-muted);
	}

	.album-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
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
