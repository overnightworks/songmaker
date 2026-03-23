<script lang="ts">
	import { albumList, selectedAlbumId, selectAlbum } from '$lib/stores/player';

	const albums = $derived($albumList);
	const activeId = $derived($selectedAlbumId);
</script>

<nav class="album-nav" aria-label="Albums">
	<button class="album-btn" class:active={activeId === null} onclick={() => selectAlbum(null)}>
		All
	</button>
	{#each albums as album (album.id)}
		<button
			class="album-btn"
			class:active={album.id === activeId}
			onclick={() => selectAlbum(album.id)}
		>
			{album.title} <span class="count">({album.song_count})</span>
		</button>
	{/each}
</nav>

<style>
	.album-nav {
		display: flex;
		gap: 4px;
		padding: 8px 12px;
		flex-wrap: wrap;
		flex-shrink: 0;
		border-bottom: 1px solid var(--border);
	}

	.album-btn {
		background: #1a1a1a;
		border: 2px solid var(--border);
		color: #aaa;
		padding: 5px 16px;
		font-family: var(--font-display);
		font-size: 14px;
		text-transform: uppercase;
		letter-spacing: 1px;
		transition: all 0.2s;
	}

	.album-btn:hover {
		border-color: var(--primary);
		color: #fff;
	}

	.album-btn.active {
		background: var(--primary);
		border-color: var(--primary);
		color: #fff;
	}

	.count {
		font-size: 10px;
		opacity: 0.7;
	}
</style>
