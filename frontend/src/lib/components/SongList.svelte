<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import {
		albumList,
		songList,
		selectedSongId,
		selectSong,
		playback,
		playGeneration,
		playAlbum,
		togglePlayPause,
		isAudioPlaying,
		expandedSongIds,
		toggleSongExpanded,
		selectedGenerationId,
		selectGenerationInSidebar,
		ensureGenerationsLoaded
	} from '$lib/stores/player';
	import { deleteGeneration, cleanupAlbum, fetchSongs } from '$lib/api/client';
	import { searchQuery } from '$lib/stores/filter';
	import { isAdmin } from '$lib/stores/auth';
	import type { SongItem, GenerationItem, AlbumItem } from '$lib/api/types';
	import { closeSidebar } from '$lib/stores/ui';
	import { SvelteSet } from 'svelte/reactivity';
	import NewAlbumForm from '$lib/components/NewAlbumForm.svelte';

	const MAX_VISIBLE_GENS = 3;

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const activeSongId = $derived($selectedSongId);
	const activeGenId = $derived($selectedGenerationId);
	const pb = $derived($playback);
	const audioPlaying = $derived($isAudioPlaying);
	const expanded = $derived($expandedSongIds);
	const search = $derived($searchQuery);
	const admin = $derived($isAdmin);

	let expandedAlbums = new SvelteSet<string>();
	let showAllGens: Record<string, boolean> = $state({});
	let confirmDeleteGenId: string | null = $state(null);
	let deleteError = $state('');
	let confirmCleanup: string | null = $state(null);
	let cleanupResult = $state('');
	let showNewAlbum = $state(false);

	// Auto-expand all albums on first load
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

	interface VersionGroup {
		label: string;
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	function groupByVersion(gens: GenerationItem[]): VersionGroup[] {
		const groups: Record<string, VersionGroup> = {};
		for (const gen of gens) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!groups[key]) {
				groups[key] = {
					label: gen.version_number !== null ? `v${gen.version_number}` : 'Unknown version',
					versionNumber: gen.version_number,
					generations: []
				};
			}
			groups[key].generations.push(gen);
		}
		const result = Object.values(groups);
		result.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
		return result;
	}

	function visibleGroups(song: SongItem): VersionGroup[] {
		const allGroups = groupByVersion(song.generations);
		if (showAllGens[song.id]) return allGroups;
		let count = 0;
		const result: VersionGroup[] = [];
		for (const group of allGroups) {
			if (count >= MAX_VISIBLE_GENS) break;
			const remaining = MAX_VISIBLE_GENS - count;
			if (group.generations.length <= remaining) {
				result.push(group);
				count += group.generations.length;
			} else {
				result.push({ ...group, generations: group.generations.slice(0, remaining) });
				count = MAX_VISIBLE_GENS;
			}
		}
		return result;
	}

	function isPlaying(song: SongItem): boolean {
		return pb?.songId === song.id;
	}

	function isGenPlaying(gen: GenerationItem): boolean {
		return pb?.generation.id === gen.id;
	}

	function handleSongClick(song: SongItem): void {
		selectSong(song.id);
		if (!expanded.has(song.id)) toggleSongExpanded(song.id);
		ensureGenerationsLoaded(song.id);
		closeSidebar();
	}

	function handleExpandToggle(e: Event, songId: string): void {
		e.stopPropagation();
		toggleSongExpanded(songId);
		if (!expanded.has(songId)) ensureGenerationsLoaded(songId);
	}

	function handleGenPlayToggle(e: Event, gen: GenerationItem, song: SongItem): void {
		e.stopPropagation();
		if (isGenPlaying(gen)) togglePlayPause();
		else playGeneration(gen, song);
	}

	function handleGenSelect(gen: GenerationItem, song: SongItem): void {
		selectGenerationInSidebar(gen, song);
	}

	function handleGenDeleteClick(e: Event, genId: string): void {
		e.stopPropagation();
		confirmDeleteGenId = confirmDeleteGenId === genId ? null : genId;
	}

	async function handleGenDeleteConfirm(e: Event, gen: GenerationItem): Promise<void> {
		e.stopPropagation();
		deleteError = '';
		try {
			await deleteGeneration(gen.id);
			songList.update((songs) =>
				songs.map((s) => ({
					...s,
					generations: s.generations.filter((g) => g.id !== gen.id),
					generation_count: s.generations.filter((g) => g.id !== gen.id).length
				}))
			);
		} catch (err) {
			deleteError = err instanceof Error ? err.message : 'Delete failed';
			setTimeout(() => (deleteError = ''), 3000);
		}
		confirmDeleteGenId = null;
	}

	async function handleCleanup(albumId: string): Promise<void> {
		try {
			const result = await cleanupAlbum(albumId);
			cleanupResult = `Deleted ${result.deleted} generation${result.deleted !== 1 ? 's' : ''}`;
			confirmCleanup = null;
			const refreshed = await fetchSongs();
			songList.set(refreshed);
			setTimeout(() => (cleanupResult = ''), 3000);
		} catch {
			cleanupResult = 'Cleanup failed';
			setTimeout(() => (cleanupResult = ''), 3000);
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
	<button
		class="new-btn"
		onclick={() => (showNewAlbum = !showNewAlbum)}
		title="New Album"
		aria-label="New Album">📁</button
	>
	{#if onNewSong}
		<button class="new-btn" onclick={onNewSong} title="New Song" aria-label="New Song">+</button>
	{/if}
</div>

{#if showNewAlbum}
	<NewAlbumForm onclose={() => (showNewAlbum = false)} />
{/if}

<div
	class="tree"
	role="tree"
	aria-label="Albums and songs"
	onclick={() => (confirmDeleteGenId = null)}
	onkeydown={(e) => e.key === 'Escape' && (confirmDeleteGenId = null)}
	tabindex="-1"
>
	{#each albumGroups as group (group.album.id)}
		<div class="album-group">
			<div
				class="album-header"
				class:expanded={expandedAlbums.has(group.album.id)}
				onclick={() => toggleAlbum(group.album.id)}
				onkeydown={(e) => e.key === 'Enter' && toggleAlbum(group.album.id)}
				role="button"
				tabindex="0"
			>
				<span class="album-chevron">{expandedAlbums.has(group.album.id) ? '▾' : '▸'}</span>
				<span class="album-title">{group.album.title}</span>
				<button
					class="album-play"
					onclick={(e) => {
						e.stopPropagation();
						playAlbum(group.album.id);
					}}
					title="Play album"
					aria-label="Play album {group.album.title}">▶</button
				>
				<span class="album-count">{group.songs.length}</span>
				{#if admin && expandedAlbums.has(group.album.id)}
					{#if confirmCleanup === group.album.id}
						<button
							class="cleanup-btn confirm"
							onclick={(e) => {
								e.stopPropagation();
								handleCleanup(group.album.id);
							}}>Delete unpicked?</button
						>
						<button
							class="cleanup-btn"
							onclick={(e) => {
								e.stopPropagation();
								confirmCleanup = null;
							}}>Cancel</button
						>
					{:else}
						<button
							class="cleanup-btn"
							onclick={(e) => {
								e.stopPropagation();
								confirmCleanup = group.album.id;
							}}
							title="Delete all non-picked generations">Clean up</button
						>
					{/if}
				{/if}
			</div>

			{#if expandedAlbums.has(group.album.id)}
				{#each group.songs as song (song.id)}
					<div class="song-group" class:active={song.id === activeSongId}>
						<div
							class="song-item"
							class:active={song.id === activeSongId}
							class:playing={isPlaying(song)}
							role="treeitem"
							aria-selected={song.id === activeSongId}
						>
							<button
								class="expand-toggle"
								onclick={(e) => handleExpandToggle(e, song.id)}
								aria-label={expanded.has(song.id) ? 'Collapse' : 'Expand'}
							>
								{expanded.has(song.id) ? '▾' : '▸'}
							</button>
							<button class="song-name-btn" onclick={() => handleSongClick(song)}>
								<span class="song-name">{song.title}</span>
							</button>
							<span class="song-meta">
								{song.generation_count} gen{song.generation_count !== 1 ? 's' : ''}
							</span>
						</div>

						{#if expanded.has(song.id)}
							<div class="gen-list">
								{#each visibleGroups(song) as vg (vg.label)}
									<div class="version-group">
										<span class="version-label">{vg.label}</span>
										{#each vg.generations as gen (gen.id)}
											<div
												class="gen-row"
												class:playing={isGenPlaying(gen)}
												class:selected={gen.id === activeGenId}
												onclick={() => handleGenSelect(gen, song)}
												onkeydown={(e) => e.key === 'Enter' && handleGenSelect(gen, song)}
												role="button"
												tabindex="0"
											>
												<button
													class="gen-play-btn"
													onclick={(e) => handleGenPlayToggle(e, gen, song)}
													aria-label={isGenPlaying(gen) && audioPlaying ? 'Pause' : 'Play'}
												>
													{#if isGenPlaying(gen) && audioPlaying}⏸{:else}▶{/if}
												</button>
												<span class="gen-num">
													{#if gen.is_picked}<span class="picked">★</span>{/if}
													gen{gen.generation_number}
												</span>
												{#if gen.seed}
													<span class="gen-seed">seed:{gen.seed}</span>
												{/if}
												{#if confirmDeleteGenId === gen.id}
													<button
														class="gen-delete-confirm"
														onclick={(e) => handleGenDeleteConfirm(e, gen)}>Delete?</button
													>
												{:else}
													<button
														class="gen-delete-btn"
														onclick={(e) => handleGenDeleteClick(e, gen.id)}
														aria-label="Delete">✕</button
													>
												{/if}
											</div>
										{/each}
									</div>
								{/each}
								{#if song.generations.length === 0}
									<span class="gen-empty">No generations</span>
								{/if}
								{#if song.generations.length > MAX_VISIBLE_GENS && !showAllGens[song.id]}
									<button class="show-all-btn" onclick={() => (showAllGens[song.id] = true)}>
										Show all ({song.generations.length})
									</button>
								{/if}
								{#if showAllGens[song.id] && song.generations.length > MAX_VISIBLE_GENS}
									<button class="show-all-btn" onclick={() => (showAllGens[song.id] = false)}>
										Show less
									</button>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	{/each}

	{#if albumGroups.length === 0}
		<p class="empty">{search ? 'No songs match' : 'No songs yet'}</p>
	{/if}
	{#if deleteError}<div class="delete-error">{deleteError}</div>{/if}
	{#if cleanupResult}<div class="cleanup-result">{cleanupResult}</div>{/if}
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
		border-color: var(--primary);
	}

	.search::placeholder {
		color: var(--text-dim);
	}

	.tree {
		flex: 1;
		overflow-y: auto;
		padding: 0;
	}

	/* Album level */
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

	.cleanup-btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-dim);
		padding: 1px 6px;
		font-size: 8px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		border-radius: 3px;
		flex-shrink: 0;
		cursor: pointer;
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

	/* Song level */
	.song-group {
		border-top: 1px solid #1a1a1a;
	}

	.song-group.active {
		border-left: 3px solid var(--primary);
	}

	.song-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px 6px 24px;
		background: transparent;
		color: var(--text);
		font-size: 12px;
		cursor: pointer;
	}

	.song-item:hover {
		background: var(--surface-hover);
	}

	.song-item.active {
		background: #1a2a1a;
	}

	.song-item.playing {
		background: #1a1a2a;
	}

	.expand-toggle {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		padding: 0 2px;
		flex-shrink: 0;
		width: 16px;
		cursor: pointer;
	}

	.expand-toggle:hover {
		color: var(--text-muted);
	}

	.song-name-btn {
		flex: 1;
		display: flex;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
		padding: 0;
		min-width: 0;
		text-align: left;
	}

	.song-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.song-meta {
		font-size: 10px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	/* Generation level */
	.gen-list {
		display: flex;
		flex-direction: column;
		padding: 0 0 4px 40px;
	}

	.version-group {
		display: flex;
		flex-direction: column;
	}

	.version-label {
		font-size: 9px;
		color: var(--text-dim);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 4px 12px 2px;
	}

	.gen-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 3px 12px;
		color: var(--text);
		font-size: 11px;
		cursor: pointer;
		border-radius: 3px;
	}

	.gen-row:hover {
		background: var(--surface-hover);
	}

	.gen-row.playing {
		background: #1a1a2a;
	}

	.gen-row.selected {
		background: #1a2a2a;
		border-left: 2px solid var(--primary);
	}

	.gen-play-btn {
		background: none;
		border: none;
		font-size: 10px;
		cursor: pointer;
		color: var(--text-muted);
		padding: 0 2px;
		flex-shrink: 0;
	}

	.gen-play-btn:hover {
		color: var(--primary);
	}

	.gen-num {
		font-family: var(--font-display);
		color: var(--text-muted);
		min-width: 32px;
	}

	.picked {
		color: var(--score-ok);
	}

	.gen-seed {
		font-size: 8px;
		color: var(--text-dim);
		margin-left: auto;
	}

	.gen-delete-btn {
		background: none;
		border: none;
		color: transparent;
		font-size: 9px;
		cursor: pointer;
		padding: 0 3px;
		flex-shrink: 0;
	}

	.gen-row:hover .gen-delete-btn {
		color: var(--text-dim);
	}

	.gen-delete-btn:hover {
		color: var(--score-bad) !important;
	}

	.gen-delete-confirm {
		background: none;
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
		font-size: 9px;
		padding: 1px 6px;
		border-radius: 3px;
		cursor: pointer;
		flex-shrink: 0;
	}

	.gen-delete-confirm:hover {
		background: var(--score-bad);
		color: #fff;
	}

	.gen-empty {
		font-size: 10px;
		color: var(--text-dim);
		font-style: italic;
		padding: 4px 12px;
	}

	.show-all-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		padding: 3px 12px;
		text-align: left;
		cursor: pointer;
	}

	.show-all-btn:hover {
		color: var(--primary);
	}

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
		font-size: 12px;
	}

	.delete-error {
		font-size: 10px;
		color: var(--score-bad);
		padding: 4px 12px;
	}

	.cleanup-result {
		font-size: 10px;
		color: var(--success);
		padding: 4px 12px;
	}
</style>
