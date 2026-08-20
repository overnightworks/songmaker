<script lang="ts">
	import {
		deleteAlbum,
		renameAlbum,
		restoreAlbum,
		shareAlbum,
		unshareAlbum
	} from '$lib/api/client';
	import { fetchSongs } from '$lib/api/songs';
	import {
		albumList,
		songList,
		selectedAlbumId,
		playAlbum,
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/player';
	import { deselectAlbum, selectSong } from '$lib/stores/navigation';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import ActionButton from './ActionButton.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	let playlistPickerFor = $state<string | null>(null);
	let showDeleteConfirm = $state(false);

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

	async function onRenameAlbum(newTitle: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			const updated = await renameAlbum(albumId, newTitle);
			updateAlbumInList(albumId, () => updated);
			addToast('Album renamed', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Rename failed', 'error');
			throw e;
		}
	}

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

	async function onAlbumDelete(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await deleteAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			addUndoToast('Album deleted', {
				label: 'Undo',
				handler: async () => {
					try {
						const restored = await restoreAlbum(albumId);
						addAlbumToList(restored);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast('Album restored', 'success');
					} catch {
						addToast('Restore failed', 'error');
					}
				}
			});
		} catch {
			addToast('Delete failed', 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistPickerFor) return;
		try {
			const result = await addAlbumToPlaylist(playlistId, playlistPickerFor);
			if (result.skipped.length > 0) {
				addToast(`Added ${result.added_count}, skipped ${result.skipped.length}`, 'info');
			} else {
				addToast('Added to playlist', 'success');
			}
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
				<h2 class="detail-title">
					<EditableTitle
						value={selectedAlbum.title}
						onsave={onRenameAlbum}
						ariaLabel="Album title"
					/>
				</h2>
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
					<ActionButton
						icon="list-plus"
						label="Add to Playlist"
						onclick={() => (playlistPickerFor = selectedAlbum.id)}
					/>
					{#if playlistPickerFor === selectedAlbum.id}
						<PlaylistPicker onselect={onAddToPlaylist} onclose={() => (playlistPickerFor = null)} />
					{/if}
				</div>
				<ActionButton
					icon="trash"
					label="Delete Album"
					destructive
					onclick={() => (showDeleteConfirm = true)}
				/>
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

{#if showDeleteConfirm && selectedAlbum}
	{@const totalGens = albumSongs.reduce((sum, s) => sum + s.generation_count, 0)}
	<ConfirmDeleteDialog
		title={`Delete "${selectedAlbum.title}"?`}
		items={[
			`${albumSongs.length} song${albumSongs.length !== 1 ? 's' : ''} (${albumSongs.map((s) => s.title).join(', ')})`,
			`${totalGens} generation${totalGens !== 1 ? 's' : ''}`,
			'All versions, scores, and chat history'
		]}
		confirmLabel="Delete Album"
		onconfirm={() => {
			showDeleteConfirm = false;
			onAlbumDelete();
		}}
		oncancel={() => (showDeleteConfirm = false)}
	/>
{/if}

<style>
	.detail-panel {
		padding: 1.2rem 1.5rem calc(var(--player-height) + 1.2rem);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.detail-title {
		font-family: var(--font-display);
		font-size: 1.73rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.detail-subtitle {
		font-size: 0.87rem;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 0.5rem;
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
		gap: 0.4rem;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.87rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0.5rem 1rem;
		cursor: pointer;
		border-bottom: 1px solid var(--border);
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 0.93rem;
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
		gap: 0.5rem;
		padding: 0.65rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font-size: 0.93rem;
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
		font-size: 0.75rem;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.empty-tab {
		color: var(--text-dim);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 0;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 0.5rem;
		}

		.detail-actions {
			flex-wrap: wrap;
		}

		.detail-panel {
			padding: 0.8rem 0.8rem calc(var(--player-height) + 0.8rem);
		}

		.detail-title {
			font-size: 1.2rem;
		}
	}
</style>
