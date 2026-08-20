<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import { albumList, songList, selectedAlbumId } from '$lib/stores/player';
	import { selectAlbumOverview, selectPlaylistView, selectSong } from '$lib/stores/navigation';
	import { searchQuery } from '$lib/stores/filter';
	import { createNewPlaylist, playlistList, selectedPlaylistId } from '$lib/stores/playlists';
	import { addToast } from '$lib/stores/toast';
	import AlbumNode from './AlbumNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';
	import {
		CREATED_SORT_LABELS,
		CREATED_SORTS,
		compareByCreatedAt,
		type CreatedSort
	} from '$lib/utils/recency';
	import { SvelteSet } from 'svelte/reactivity';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const search = $derived($searchQuery);
	const currentAlbumId = $derived($selectedAlbumId);
	const playlists = $derived($playlistList);
	const currentPlaylistId = $derived($selectedPlaylistId);

	interface SharedItem {
		id: string;
		type: 'album' | 'song' | 'generation' | 'playlist';
		label: string;
		parentSongId?: string;
	}

	const sharedItems = $derived.by(() => {
		const items: SharedItem[] = [];
		for (const a of albums) {
			if (a.is_shared) items.push({ id: a.id, type: 'album', label: a.title });
		}
		for (const s of songs) {
			if (s.is_shared) items.push({ id: s.id, type: 'song', label: s.title });
			for (const g of s.generations) {
				if (g.is_shared) {
					items.push({
						id: g.id,
						type: 'generation',
						label: `Gen #${g.generation_number} — ${s.title}`,
						parentSongId: s.id
					});
				}
			}
		}
		for (const p of playlists) {
			if (p.is_shared) items.push({ id: p.id, type: 'playlist', label: p.title });
		}
		return items;
	});

	let expandedAlbums = new SvelteSet<string>();
	let playlistsExpanded = $state(true);
	let sharedExpanded = $state(true);
	let createdSort = $state<CreatedSort>('newest');

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

		const orderedAlbums = [...albums].sort((a, b) => compareByCreatedAt(a, b, createdSort));
		const groups: AlbumGroup[] = [];
		for (const album of orderedAlbums) {
			const albumSongs = filtered
				.filter((s) => s.album_id === album.id)
				.sort((a, b) => compareByCreatedAt(a, b, createdSort));
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

	async function onCreatePlaylist(): Promise<void> {
		try {
			const playlist = await createNewPlaylist('Playlist');
			selectPlaylistView(playlist.id);
		} catch {
			addToast('Create failed', 'error');
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
	<div class="sort-strip" role="radiogroup" aria-label="List sort" tabindex="-1">
		{#each CREATED_SORTS as option (option)}
			<button
				class="sort-btn"
				class:active={createdSort === option}
				role="radio"
				aria-checked={createdSort === option}
				aria-label={CREATED_SORT_LABELS[option]}
				onclick={() => (createdSort = option)}
			>
				{CREATED_SORT_LABELS[option]}
			</button>
		{/each}
	</div>
	{#if onNewSong}
		<button class="new-btn" onclick={onNewSong} title="New Song" aria-label="New Song">+</button>
	{/if}
</div>

<div class="tree" role="tree" aria-label="Albums and songs">
	{#if sharedItems.length > 0}
		<div class="section-group">
			<button class="section-header" onclick={() => (sharedExpanded = !sharedExpanded)}>
				<span class="section-arrow" class:collapsed={!sharedExpanded}>▸</span>
				<span class="section-label">Shared</span>
				<span class="section-count">{sharedItems.length}</span>
			</button>
			{#if sharedExpanded}
				{#each sharedItems as item (item.type + item.id)}
					<button
						class="playlist-row"
						onclick={() => {
							if (item.type === 'album') selectAlbumOverview(item.id);
							else if (item.type === 'song') selectSong(item.id);
							else if (item.type === 'playlist') selectPlaylistView(item.id);
							else if (item.parentSongId) selectSong(item.parentSongId);
						}}
					>
						<span class="shared-icon">&#128279;</span>
						<span class="playlist-title">{item.label}</span>
						<span class="playlist-count">{item.type}</span>
					</button>
				{/each}
			{/if}
		</div>
	{/if}

	<div class="section-group">
		<div class="section-header-row">
			<button class="section-header" onclick={() => (playlistsExpanded = !playlistsExpanded)}>
				<span class="section-arrow" class:collapsed={!playlistsExpanded}>▸</span>
				<span class="section-label">Playlists</span>
				<span class="section-count">{playlists.length}</span>
			</button>
			<button
				class="new-btn"
				onclick={onCreatePlaylist}
				title="New playlist"
				aria-label="New playlist">+</button
			>
		</div>
		{#if playlistsExpanded}
			{#if playlists.length === 0}
				<p class="empty">No playlists</p>
			{:else}
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
		{/if}
	</div>

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
		flex-wrap: wrap;
		gap: 6px;
	}

	.sort-strip {
		display: flex;
		gap: 2px;
		flex-shrink: 0;
	}

	.sort-btn {
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text-muted);
		border-radius: 999px;
		padding: 0.15rem 0.5rem;
		font-size: 0.68rem;
		font-family: var(--font-body);
		cursor: pointer;
	}

	.sort-btn.active {
		color: var(--text);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}

	.search {
		flex: 1;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: var(--label-font-size);
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
		font-size: 1rem;
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

	.section-header-row {
		display: flex;
		align-items: center;
		padding-right: 8px;
	}
	.section-header {
		display: flex;
		align-items: center;
		gap: 6px;
		flex: 1;
		min-width: 0;
		padding: 6px 12px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.7rem;
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
		font-size: 0.6rem;
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
		font-size: 0.6rem;
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
		font-size: var(--label-font-size);
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

	.shared-icon {
		font-size: 0.7rem;
		flex-shrink: 0;
	}

	.playlist-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.playlist-count {
		font-size: 0.7rem;
		color: var(--text-dim);
		flex-shrink: 0;
		margin-left: 8px;
	}

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
		font-size: var(--label-font-size);
	}

	@media (max-width: 768px) {
		.search {
			font-size: 1rem;
			padding: 8px 12px;
		}

		.new-btn {
			width: 36px;
			height: 36px;
		}
	}
</style>
