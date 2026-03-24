<script lang="ts">
	import { albumList, songList, selectedAlbumId, selectAlbum } from '$lib/stores/player';
	import { cleanupAlbum, fetchSongs } from '$lib/api/client';

	const albums = $derived($albumList);
	const activeId = $derived($selectedAlbumId);

	let confirmCleanup = $state(false);
	let cleanupResult = $state('');

	async function handleCleanup(): Promise<void> {
		if (!activeId) return;
		try {
			const result = await cleanupAlbum(activeId);
			cleanupResult = `Deleted ${result.deleted} generation${result.deleted !== 1 ? 's' : ''}`;
			confirmCleanup = false;
			const songs = await fetchSongs();
			songList.set(songs);
			setTimeout(() => (cleanupResult = ''), 3000);
		} catch {
			cleanupResult = 'Cleanup failed';
			setTimeout(() => (cleanupResult = ''), 3000);
		}
	}
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
	{#if activeId}
		{#if confirmCleanup}
			<button class="cleanup-btn confirm" onclick={handleCleanup}>Delete unpicked?</button>
			<button class="cleanup-btn cancel" onclick={() => (confirmCleanup = false)}>Cancel</button>
		{:else}
			<button
				class="cleanup-btn"
				onclick={() => (confirmCleanup = true)}
				title="Delete all non-picked generations in this album"
			>
				Clean up
			</button>
		{/if}
	{/if}
	{#if cleanupResult}
		<span class="cleanup-result">{cleanupResult}</span>
	{/if}
</nav>

<style>
	.album-nav {
		display: flex;
		gap: 4px;
		padding: 8px 12px;
		flex-wrap: wrap;
		flex-shrink: 0;
		border-bottom: 1px solid var(--border);
		align-items: center;
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

	.cleanup-btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-dim);
		padding: 4px 10px;
		font-size: 10px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		border-radius: 3px;
		margin-left: auto;
	}

	.cleanup-btn:hover {
		color: var(--text-muted);
		border-color: var(--text-muted);
	}

	.cleanup-btn.confirm {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.cleanup-btn.confirm:hover {
		background: var(--score-bad);
		color: #fff;
	}

	.cleanup-btn.cancel {
		border-color: var(--border);
		color: var(--text-dim);
	}

	.cleanup-result {
		font-size: 10px;
		color: var(--success);
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}
</style>
