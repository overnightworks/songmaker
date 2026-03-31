<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import { albumList, songList } from '$lib/stores/player';
	import { deleteAlbum } from '$lib/api/client';
	import { searchQuery } from '$lib/stores/filter';
	import { addToast } from '$lib/stores/toast';
	import AlbumNode from './AlbumNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';
	import { SvelteSet } from 'svelte/reactivity';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const search = $derived($searchQuery);

	let expandedAlbums = new SvelteSet<string>();

	$effect(() => {
		if (albums.length > 0 && expandedAlbums.size === 0) {
			for (const a of albums) expandedAlbums.add(a.id);
		}
	});

	interface AlbumGroup {
		album: AlbumItem;
		songs: SongItem[];
	}

	const albumGroups = $derived.by(() => {
		let filtered = songs;
		if (search) {
			const q = search.toLowerCase();
			filtered = filtered.filter((s) => s.title.toLowerCase().includes(q));
		}

		const groups: AlbumGroup[] = [];
		for (const album of albums) {
			const albumSongs = filtered
				.filter((s) => s.album_id === album.id)
				.sort((a, b) => a.track_number - b.track_number);
			if (albumSongs.length > 0) {
				groups.push({ album, songs: albumSongs });
			}
		}
		return groups;
	});

	function toggleAlbum(albumId: string): void {
		if (expandedAlbums.has(albumId)) expandedAlbums.delete(albumId);
		else expandedAlbums.add(albumId);
	}

	async function handleDeleteAlbum(albumId: string): Promise<void> {
		try {
			await deleteAlbum(albumId);
			albumList.update((list) => list.filter((a) => a.id !== albumId));
			songList.update((list) => list.filter((s) => s.album_id !== albumId));
			addToast('Album deleted', 'success');
		} catch (err) {
			addToast(err instanceof Error ? err.message : 'Delete failed', 'error');
		}
	}
</script>

<div class="search-bar">
	<input
		class="search"
		type="text"
		placeholder="Search songs..."
		value={search}
		oninput={(e: Event) => searchQuery.set((e.target as HTMLInputElement).value)}
		aria-label="Search songs"
	/>
	{#if onNewSong}
		<button class="new-btn" onclick={onNewSong} title="New Song" aria-label="New Song">+</button>
	{/if}
</div>

<div class="tree" role="tree" aria-label="Albums and songs">
	{#each albumGroups as group (group.album.id)}
		<AlbumNode
			album={group.album}
			songs={group.songs}
			expanded={expandedAlbums.has(group.album.id)}
			ontoggle={() => toggleAlbum(group.album.id)}
			ondeletealbum={handleDeleteAlbum}
		/>
	{/each}

	{#if albumGroups.length === 0}
		<p class="empty">{search ? 'No songs match' : 'No songs yet'}</p>
	{/if}
</div>

<style>
	.search-bar {
		padding: 8px 12px;
		flex-shrink: 0;
		display: flex;
		gap: 6px;
	}

	.search {
		flex: 1;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		outline: none;
		min-width: 0;
	}

	.new-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		width: 30px;
		height: 30px;
		font-size: 16px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		font-family: var(--font-body);
	}

	.new-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.search:focus {
		border-color: var(--accent);
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.search::placeholder {
		color: var(--text-dim);
	}

	.tree {
		flex: 1;
		overflow-y: auto;
		padding: 0;
	}

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
		font-size: 12px;
	}

	@media (max-width: 768px) {
		.search {
			font-size: 14px;
			padding: 8px 12px;
		}

		.new-btn {
			width: 36px;
			height: 36px;
		}
	}
</style>
