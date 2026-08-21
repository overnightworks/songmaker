<script lang="ts">
	import AgeStamp from './AgeStamp.svelte';
	import SongNode from './SongNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';
	import { LIBRARY_ALBUMS_LOADING, LIBRARY_RETRY_LABEL } from '$lib/constants';
	import type { AlbumSongsLoadState } from '$lib/stores/player';

	interface Props {
		album: AlbumItem;
		songs: SongItem[];
		expanded: boolean;
		selected: boolean;
		loadState?: AlbumSongsLoadState;
		ontoggle: () => void;
		onselect: () => void;
		onretry?: () => void;
	}

	let { album, songs, expanded, selected, loadState, ontoggle, onselect, onretry }: Props =
		$props();

	function handleClick(): void {
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
		<span class="album-text">
			<span class="album-title">{album.title}</span>
			{#if album.artist}
				<span class="album-artist">{album.artist}</span>
			{/if}
		</span>
		<AgeStamp createdAt={album.created_at} />
		<span class="album-count">{album.song_count}</span>
	</div>

	{#if expanded}
		{#if loadState?.status === 'loading' && songs.length === 0}
			<p class="album-status" role="status">{LIBRARY_ALBUMS_LOADING}</p>
		{:else if loadState?.status === 'error'}
			<p class="album-status" role="alert">{loadState.error}</p>
			{#if onretry}
				<button class="album-retry" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
			{/if}
		{/if}
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
		font-size: var(--label-font-size);
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
		font-size: 0.7rem;
		color: var(--text-decoration);
		width: 16px;
		flex-shrink: 0;
		cursor: pointer;
		padding: 0;
	}

	.album-chevron:hover {
		color: var(--text-muted);
	}

	.album-text {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.album-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.album-artist {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-body);
		font-size: 0.72rem;
		letter-spacing: 0;
		text-transform: none;
		color: var(--text-muted);
	}

	.album-count {
		font-size: 0.6rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.album-status {
		margin: 0;
		padding: 8px 12px 8px 28px;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.album-retry {
		margin: 0 12px 8px 28px;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--border);
		color: var(--text);
		font-size: 0.75rem;
		cursor: pointer;
	}

	@media (max-width: 768px) {
		.album-header {
			padding: 10px 12px;
			font-size: var(--label-font-size);
		}
	}
</style>
