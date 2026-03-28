<script lang="ts">
	import {
		playAlbum,
		ensureGenerationsLoaded,
		expandedSongIds,
		toggleSongExpanded
	} from '$lib/stores/player';
	import { isAdmin } from '$lib/stores/auth';
	import { cleanupAlbum, shareAlbum, unshareAlbum, fetchSongs } from '$lib/api/client';
	import { albumList, songList } from '$lib/stores/player';
	import { addToast } from '$lib/stores/toast';
	import SongNode from './SongNode.svelte';
	import type { SongItem, AlbumItem } from '$lib/api/types';

	interface Props {
		album: AlbumItem;
		songs: SongItem[];
		expanded: boolean;
		ontoggle: () => void;
		ondeletealbum: (albumId: string) => void;
	}

	let { album, songs, expanded, ontoggle, ondeletealbum }: Props = $props();

	const admin = $derived($isAdmin);
	const songExpanded = $derived($expandedSongIds);

	let confirmCleanup = $state(false);
	let confirmDelete = $state(false);

	function handleExpandToggle(e: Event, songId: string): void {
		e.stopPropagation();
		toggleSongExpanded(songId);
		if (!songExpanded.has(songId)) ensureGenerationsLoaded(songId);
	}

	async function handleCleanup(): Promise<void> {
		try {
			const result = await cleanupAlbum(album.id);
			confirmCleanup = false;
			const refreshed = await fetchSongs();
			songList.set(refreshed.items);
			addToast(`Deleted ${result.deleted} generation${result.deleted !== 1 ? 's' : ''}`, 'success');
		} catch {
			addToast('Cleanup failed', 'error');
		}
	}

	async function handleShare(e: Event): Promise<void> {
		e.stopPropagation();
		try {
			if (album.is_shared) {
				await unshareAlbum(album.id);
				albumList.update((list) =>
					list.map((a) =>
						a.id === album.id ? { ...a, is_shared: false, share_slug: null } : a
					)
				);
				addToast('Sharing disabled', 'success');
			} else {
				const result = await shareAlbum(album.id);
				albumList.update((list) =>
					list.map((a) =>
						a.id === album.id
							? { ...a, is_shared: true, share_slug: result.share_slug }
							: a
					)
				);
				await navigator.clipboard.writeText(result.share_url);
				addToast('Link copied to clipboard', 'success');
			}
		} catch {
			addToast('Share failed', 'error');
		}
	}
</script>

<div class="album-group">
	<div
		class="album-header"
		class:expanded
		onclick={ontoggle}
		onkeydown={(e) => e.key === 'Enter' && ontoggle()}
		role="button"
		tabindex="0"
	>
		<span class="album-chevron">{expanded ? '▾' : '▸'}</span>
		<span class="album-title">{album.title}</span>
		<button
			class="album-play"
			onclick={(e) => {
				e.stopPropagation();
				playAlbum(album.id);
			}}
			title="Play album"
			aria-label="Play album {album.title}">▶</button
		>
		<span class="album-count">{songs.length}</span>
		{#if expanded}
			<button
				class="share-btn"
				class:active={album.is_shared}
				onclick={handleShare}
				title={album.is_shared ? 'Disable sharing' : 'Share album'}
				aria-label={album.is_shared ? 'Disable sharing' : 'Share album'}
			>
				{album.is_shared ? 'Shared' : 'Share'}
			</button>
		{/if}
		{#if admin && expanded}
			{#if confirmCleanup}
				<button
					class="cleanup-btn confirm"
					onclick={(e) => {
						e.stopPropagation();
						handleCleanup();
					}}>Delete unpicked?</button
				>
				<button
					class="cleanup-btn"
					onclick={(e) => {
						e.stopPropagation();
						confirmCleanup = false;
					}}>Cancel</button
				>
			{:else if confirmDelete}
				<button
					class="cleanup-btn confirm"
					onclick={(e) => {
						e.stopPropagation();
						ondeletealbum(album.id);
					}}>Delete album?</button
				>
				<button
					class="cleanup-btn"
					onclick={(e) => {
						e.stopPropagation();
						confirmDelete = false;
					}}>Cancel</button
				>
			{:else}
				<button
					class="cleanup-btn"
					onclick={(e) => {
						e.stopPropagation();
						confirmCleanup = true;
					}}
					title="Delete all non-picked generations">Clean up</button
				>
				<button
					class="cleanup-btn"
					onclick={(e) => {
						e.stopPropagation();
						confirmDelete = true;
					}}
					title="Delete album and all songs">Delete</button
				>
			{/if}
		{/if}
	</div>

	{#if expanded}
		{#each songs as song (song.id)}
			<SongNode
				{song}
				expanded={songExpanded.has(song.id)}
				onexpandtoggle={(e) => handleExpandToggle(e, song.id)}
			/>
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

	.share-btn {
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

	.share-btn:hover {
		color: var(--text-muted);
		border-color: var(--text-muted);
	}

	.share-btn.active {
		border-color: var(--accent);
		color: var(--accent);
		box-shadow: 0 0 6px rgba(160, 32, 240, 0.2);
	}
</style>
