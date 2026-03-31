<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import { albumList, songList, selectedAlbumId } from '$lib/stores/player';
	import { selectAlbumOverview, selectPlaylistView } from '$lib/stores/navigation';
	import { searchQuery } from '$lib/stores/filter';
	import { playlistList, selectedPlaylistId } from '$lib/stores/playlists';
	import AlbumNode from './AlbumNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';
	import { SvelteSet } from 'svelte/reactivity';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const search = $derived($searchQuery);
	const currentAlbumId = $derived($selectedAlbumId);
	const playlists = $derived($playlistList);
	const currentPlaylistId = $derived($selectedPlaylistId);

	let expandedAlbums = new SvelteSet<string>();
	let playlistsExpanded = $state(true);

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
	{#if playlists.length > 0}
		<div class="section-group">
			<button class="section-header" onclick={() => (playlistsExpanded = !playlistsExpanded)}>
				<span class="section-arrow" class:collapsed={!playlistsExpanded}>▸</span>
				<span class="section-label">Playlists</span>
				<span class="section-count">{playlists.length}</span>
			</button>
			{#if playlistsExpanded}
				{#each playlists as p (p.id)}
					<button
						class="playlist-row"
						class:selected={p.id === currentPlaylistId}
						onclick={() => selectPlaylistView(p.id)}
					>
						<span class="playlist-title">{p.title}</span>
						<span class="playlist-count">{p.entry_count}</span>
					</button>
				{/each}
			{/if}
		</div>
	{/if}

	{#each albumGroups as group (group.album.id)}
		<AlbumNode
			album={group.album}
			songs={group.songs}
			expanded={expandedAlbums.has(group.album.id)}
			selected={group.album.id === currentAlbumId}
			ontoggle={() => toggleAlbum(group.album.id)}
			onselect={() => selectAlbumOverview(group.album.id)}
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

	.section-group {
		border-bottom: 1px solid var(--border);
		padding-bottom: 4px;
		margin-bottom: 4px;
	}

	.section-header {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 6px 12px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 10px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
		cursor: pointer;
		text-align: left;
	}

	.section-header:hover {
		color: var(--text);
	}

	.section-arrow {
		font-size: 9px;
		transition: transform 0.15s;
		display: inline-block;
	}

	.section-arrow:not(.collapsed) {
		transform: rotate(90deg);
	}

	.section-label {
		flex: 1;
	}

	.section-count {
		font-size: 9px;
		color: var(--text-dim);
	}

	.playlist-row {
		display: flex;
		align-items: center;
		width: 100%;
		padding: 5px 12px 5px 26px;
		background: none;
		border: none;
		color: var(--text-light);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.playlist-row:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.playlist-row.selected {
		color: var(--primary);
		background: var(--surface-hover);
	}

	.playlist-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.playlist-count {
		font-size: 10px;
		color: var(--text-dim);
		flex-shrink: 0;
		margin-left: 8px;
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
