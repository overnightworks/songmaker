<script lang="ts">
	import { fetchSongs, deleteAlbum, cleanupAlbum, shareAlbum, unshareAlbum } from '$lib/api/client';
	import {
		albumList,
		songList,
		selectedAlbumId,
		playAlbum,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/player';
	import { deselectAlbum, selectSong } from '$lib/stores/navigation';
	import { addToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import OverflowMenu from './OverflowMenu.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';

	let playlistPickerFor = $state<string | null>(null);

	const albums = $derived($albumList);
	const allSongs = $derived($songList);
	const currentAlbumId = $derived($selectedAlbumId);

	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const albumSongs = $derived(
		currentAlbumId
			? allSongs
					.filter((s) => s.album_id === currentAlbumId)
					.sort((a, b) => a.track_number - b.track_number)
			: []
	);
	const albumSongCount = $derived(albumSongs.length);
	const albumGenCount = $derived(albumSongs.reduce((sum, s) => sum + s.generation_count, 0));

	async function onAlbumShareEnable() {
		if (!selectedAlbum) throw new Error('No album');
		const albumId = selectedAlbum.id;
		const result = await shareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: true, share_slug: result.share_slug }));
		return result;
	}

	async function onAlbumShareDisable() {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		await unshareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: false, share_slug: null }));
	}

	async function onAlbumCleanup(): Promise<void> {
		if (!selectedAlbum) return;
		try {
			const result = await cleanupAlbum(selectedAlbum.id);
			const refreshed = await fetchSongs();
			songList.set(refreshed.items);
			addToast(`Deleted ${result.deleted} generation${result.deleted !== 1 ? 's' : ''}`, 'success');
		} catch {
			addToast('Cleanup failed', 'error');
		}
	}

	async function onAlbumDelete(): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			await deleteAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			addToast('Album deleted', 'success');
		} catch {
			addToast('Delete failed', 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistPickerFor) return;
		try {
			await addAlbumToPlaylist(playlistId, playlistPickerFor);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistPickerFor = null;
		}
	}
</script>

{#if selectedAlbum}
	<div class="detail-panel">
		<button class="back-btn" onclick={deselectAlbum}>
			<span class="back-arrow">←</span>
			Albums
		</button>
		<div class="detail-header">
			<div>
				<h2 class="detail-title">{selectedAlbum.title}</h2>
				<span class="detail-subtitle">
					{albumSongCount} song{albumSongCount !== 1 ? 's' : ''} · {albumGenCount} generation{albumGenCount !==
					1
						? 's'
						: ''}
				</span>
			</div>
			<div class="detail-actions">
				<button class="action-btn-primary" onclick={() => playAlbum(selectedAlbum.id)}>
					Play Album
				</button>
				<ShareButton
					isShared={selectedAlbum.is_shared}
					shareSlug={selectedAlbum.share_slug}
					onshare={onAlbumShareEnable}
					onunshare={onAlbumShareDisable}
				/>
				<div class="picker-anchor">
					<OverflowMenu
						items={[
							{
								label: 'Add to Playlist',
								onclick: () => (playlistPickerFor = selectedAlbum.id)
							},
							{
								label: 'Clean Up Generations',
								confirmLabel: 'Confirm Clean Up',
								onclick: onAlbumCleanup
							},
							{
								label: 'Delete Album',
								confirmLabel: 'Confirm Delete',
								destructive: true,
								onclick: onAlbumDelete
							}
						]}
					/>
					{#if playlistPickerFor === selectedAlbum.id}
						<PlaylistPicker onselect={onAddToPlaylist} onclose={() => (playlistPickerFor = null)} />
					{/if}
				</div>
			</div>
		</div>

		{#if selectedAlbum.is_shared && selectedAlbum.share_slug}
			<button
				class="share-link"
				onclick={() => {
					const url = `${window.location.origin}/share/${selectedAlbum.share_slug}`;
					navigator.clipboard.writeText(url);
					addToast('Link copied', 'success');
				}}
				title="Click to copy share link"
			>
				{window.location.origin}/share/{selectedAlbum.share_slug}
			</button>
		{/if}

		<div class="item-list">
			{#each albumSongs as s (s.id)}
				<button class="item-row" onclick={() => selectSong(s.id)}>
					<span class="item-title">{s.title}</span>
					<span class="item-meta">
						{s.generation_count} gen{s.generation_count !== 1 ? 's' : ''}
					</span>
				</button>
			{/each}
			{#if albumSongs.length === 0}
				<p class="empty-tab">No songs in this album yet.</p>
			{/if}
		</div>
	</div>
{/if}

<style>
	.detail-panel {
		padding: 16px 20px calc(var(--player-height) + 16px);
		display: flex;
		flex-direction: column;
		gap: 12px;
		flex: 1;
		max-width: 1000px;
		width: 100%;
		min-width: 0;
		min-height: 0;
		margin: 0 auto;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.detail-title {
		font-family: var(--font-display);
		font-size: 22px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.detail-subtitle {
		font-size: 12px;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.action-btn-primary {
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
		transition: box-shadow 0.2s;
	}

	.action-btn-primary:hover {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

	.back-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 11px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 8px 16px;
		cursor: pointer;
		border-bottom: 1px solid var(--border);
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 14px;
	}

	.picker-anchor {
		position: relative;
	}

	.item-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.item-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font-size: 14px;
	}

	.item-row:hover {
		border-color: var(--primary);
		background: var(--surface-hover);
	}

	.item-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item-meta {
		font-size: 11px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.empty-tab {
		color: var(--text-dim);
		font-size: 13px;
		font-style: italic;
		padding: 12px 0;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 8px;
		}

		.detail-actions {
			flex-wrap: wrap;
		}

		.detail-panel {
			padding: 12px 12px calc(var(--player-height) + 12px);
		}

		.detail-title {
			font-size: 18px;
		}
	}
</style>
