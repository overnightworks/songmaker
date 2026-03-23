<script lang="ts">
	import { albums, currentAlbumIndex, selectAlbum } from '$lib/stores/player';

	const albumList = $derived($albums);
	const activeIndex = $derived($currentAlbumIndex);
</script>

<nav class="album-nav" aria-label="Albums">
	{#each albumList as album, i (album.id)}
		<button class="album-btn" class:active={i === activeIndex} onclick={() => selectAlbum(i)}>
			{album.title}
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
</style>
