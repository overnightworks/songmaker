<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import { albumList, songList, selectedAlbumId } from '$lib/stores/player';
	import { selectAlbumOverview, selectPlaylistView, selectSong } from '$lib/stores/navigation';
	import { searchQuery } from '$lib/stores/filter';
	import { createNewPlaylist, playlistList, selectedPlaylistId } from '$lib/stores/playlists';
	import {
		changeLibrarySort,
		groupSearchHits,
		libraryBrowse,
		librarySearch,
		librarySort,
		loadLibraryBrowse,
		loadMoreLibrarySearch,
		retryLibrarySearch,
		syncLibrarySearch
	} from '$lib/stores/librarySearch';
	import { addToast } from '$lib/stores/toast';
	import AlbumNode from './AlbumNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';
	import { CREATED_SORT_LABELS, CREATED_SORTS, compareByCreatedAt } from '$lib/utils/recency';
	import {
		LIBRARY_BROWSE_EMPTY,
		LIBRARY_LOAD_MORE,
		LIBRARY_RETRY_LABEL,
		LIBRARY_SEARCH_EMPTY,
		LIBRARY_SEARCH_ERROR,
		LIBRARY_SEARCH_LOADING,
		LIBRARY_SEARCH_PLACEHOLDER
	} from '$lib/constants';
	import { SvelteSet } from 'svelte/reactivity';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const search = $derived($searchQuery);
	const currentAlbumId = $derived($selectedAlbumId);
	const playlists = $derived($playlistList);
	const currentPlaylistId = $derived($selectedPlaylistId);
	const createdSort = $derived($librarySort);
	const searchState = $derived($librarySearch);
	const browseState = $derived($libraryBrowse);
	const searching = $derived(search.trim().length > 0);

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

	$effect(() => {
		syncLibrarySearch(search);
	});

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
		if (searching) {
			return groupSearchHits(searchState.items);
		}

		const orderedAlbums = [...albums].sort((a, b) => compareByCreatedAt(a, b, createdSort));
		const groups: AlbumGroup[] = [];
		for (const album of orderedAlbums) {
			const albumSongs = songs
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

	function hydrateAndOpenAlbum(album: AlbumItem): void {
		albumList.update((list) =>
			list.some((item) => item.id === album.id) ? list : [...list, album]
		);
		selectAlbumOverview(album.id);
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
		placeholder={LIBRARY_SEARCH_PLACEHOLDER}
		value={search}
		oninput={(e: Event) => searchQuery.set((e.target as HTMLInputElement).value)}
		aria-label={LIBRARY_SEARCH_PLACEHOLDER}
		aria-busy={searching && searchState.status === 'loading'}
	/>
	<div class="sort-strip" role="radiogroup" aria-label="List sort" tabindex="-1">
		{#each CREATED_SORTS as option (option)}
			<button
				class="sort-btn"
				class:active={createdSort === option}
				role="radio"
				aria-checked={createdSort === option}
				aria-label={CREATED_SORT_LABELS[option]}
				onclick={() => changeLibrarySort(option, search)}
			>
				{CREATED_SORT_LABELS[option]}
			</button>
		{/each}
	</div>
	{#if onNewSong}
		<button
			class="new-btn"
			data-hitbox="frequent"
			data-hitbox-face
			onclick={onNewSong}
			title="New Song"
			aria-label="New Song">+</button
		>
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
				data-hitbox="frequent"
				data-hitbox-face
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
			onselect={() => hydrateAndOpenAlbum(group.album)}
		/>
	{/each}

	{#if searching && searchState.status === 'loading' && searchState.items.length === 0}
		<p class="empty" role="status">{LIBRARY_SEARCH_LOADING}</p>
	{:else if searching && searchState.status === 'error'}
		<p class="empty" role="alert">{searchState.error || LIBRARY_SEARCH_ERROR}</p>
		<button class="retry-btn" onclick={() => retryLibrarySearch()}>{LIBRARY_RETRY_LABEL}</button>
	{:else if albumGroups.length === 0}
		<p class="empty">{searching ? LIBRARY_SEARCH_EMPTY : LIBRARY_BROWSE_EMPTY}</p>
	{/if}

	{#if searching && searchState.hasMore}
		<button
			class="load-more"
			onclick={() => loadMoreLibrarySearch()}
			disabled={searchState.status === 'loading'}
		>
			{LIBRARY_LOAD_MORE}
		</button>
	{:else if !searching && (browseState.albumHasMore || browseState.songHasMore)}
		<button
			class="load-more"
			onclick={() => loadLibraryBrowse({ reset: false })}
			disabled={browseState.status === 'loading'}
		>
			{LIBRARY_LOAD_MORE}
		</button>
	{/if}

	{#if !searching && browseState.status === 'error'}
		<p class="empty" role="alert">{browseState.error || LIBRARY_SEARCH_ERROR}</p>
		<button class="retry-btn" onclick={() => loadLibraryBrowse({ reset: true })}
			>{LIBRARY_RETRY_LABEL}</button
		>
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
		color: var(--text-muted);
		font-size: 1rem;
		font-family: var(--font-body);
		line-height: 1;
	}

	.new-btn:hover {
		color: var(--primary);
	}

	.search:focus {
		border-color: var(--accent);
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.search::placeholder {
		color: var(--text-subtle);
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
		color: var(--text-subtle);
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
		color: var(--text-subtle);
		flex-shrink: 0;
		margin-left: 8px;
	}

	.empty {
		padding: 20px;
		color: var(--text-subtle);
		text-align: center;
		font-size: var(--label-font-size);
	}

	.retry-btn,
	.load-more {
		display: block;
		margin: 0 auto 16px;
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover,
	.load-more:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.load-more:disabled {
		opacity: 0.5;
		cursor: default;
	}

	@media (max-width: 768px) {
		.search {
			font-size: 1rem;
			padding: 8px 12px;
		}
	}
</style>
