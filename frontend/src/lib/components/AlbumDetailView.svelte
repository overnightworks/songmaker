<script lang="ts">
	import {
		deleteAlbum,
		deleteAlbumCover,
		renameAlbum,
		restoreAlbum,
		shareAlbum,
		unshareAlbum,
		uploadAlbumCover
	} from '$lib/api/client';
	import { fetchSongs } from '$lib/api/songs';
	import {
		albumList,
		albumSongsLoad,
		songList,
		selectedAlbumId,
		loadSongsForAlbum,
		playAlbum,
		playAlbumFromGeneration,
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/player';
	import { selectSong } from '$lib/stores/navigation';
	import { setOpenCollection } from '$lib/stores/collection';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ACCEPT,
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { hexToRgb } from '$lib/utils/contrast';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import type { GenerationItem, SongItem } from '$lib/api/types';
	import CollectionHeader from './CollectionHeader.svelte';
	import Icon from './Icon.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	interface Props {
		albumId?: string;
	}

	let { albumId }: Props = $props();

	let playlistPickerOpen = $state(false);
	let showDeleteConfirm = $state(false);

	const albums = $derived($albumList);
	const allSongs = $derived($songList);
	const currentAlbumId = $derived(albumId ?? $selectedAlbumId);

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
	const albumSongCount = $derived(selectedAlbum?.song_count ?? albumSongs.length);
	const albumPickCount = $derived(
		albumSongs.filter((s) => s.generations.some((g) => g.is_picked)).length
	);
	const albumLoad = $derived(currentAlbumId ? $albumSongsLoad[currentAlbumId] : undefined);
	const coverUrl = $derived(selectedAlbum?.cover?.detail ?? null);
	const coverAlt = $derived(
		selectedAlbum ? `${ALBUM_COVER_ALT_TYPE} ${selectedAlbum.title}` : ALBUM_COVER_ALT_TYPE
	);
	const artFill = $derived(selectedAlbum ? usableAlbumPrimary(selectedAlbum.colors) : null);
	const initials = $derived(
		selectedAlbum ? titleInitials(selectedAlbum.title) : ALBUM_ART_EMPTY_INITIALS
	);
	const subtitle = $derived(
		`${albumSongCount} song${albumSongCount !== 1 ? 's' : ''} · ${albumPickCount} pick${albumPickCount !== 1 ? 's' : ''}`
	);
	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);

	function usableAlbumPrimary(colors: Record<string, string>): string | null {
		const primary = colors.primary;
		if (typeof primary !== 'string') return null;
		const value = primary.trim();
		if (!value) return null;
		try {
			hexToRgb(value);
		} catch {
			return null;
		}
		return value;
	}

	function bestGeneration(song: SongItem): GenerationItem | undefined {
		return song.generations.find((g) => g.is_picked) ?? song.generations[0];
	}

	async function onCoverFile(event: Event): Promise<void> {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await uploadAlbumCover(selectedAlbum.id, file);
			updateAlbumInList(selectedAlbum.id, () => updated);
			addToast('Cover saved', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover upload failed', 'error');
		} finally {
			coverBusy = false;
		}
	}

	function onCoverAction(): void {
		coverInput?.click();
	}

	async function onCoverRemove(): Promise<void> {
		if (!selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await deleteAlbumCover(selectedAlbum.id);
			updateAlbumInList(selectedAlbum.id, () => updated);
			addToast('Cover removed', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover remove failed', 'error');
		} finally {
			coverBusy = false;
		}
	}

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
		await refreshSharesAfterMutation();
		return result;
	}

	async function onAlbumShareDisable() {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		await unshareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: false, share_slug: null }));
		await refreshSharesAfterMutation();
	}

	async function onAlbumDelete(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await deleteAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
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
		if (!currentAlbumId) return;
		try {
			const result = await addAlbumToPlaylist(playlistId, currentAlbumId);
			if (result.skipped.length > 0) {
				addToast(`Added ${result.added_count}, skipped ${result.skipped.length}`, 'info');
			} else {
				addToast('Added to playlist', 'success');
			}
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistPickerOpen = false;
		}
	}

	function onRowPlay(song: SongItem): void {
		if (!currentAlbumId) return;
		const gen = bestGeneration(song);
		if (!gen) return;
		void playAlbumFromGeneration(currentAlbumId, song, gen);
	}
</script>

{#if selectedAlbum}
	<div class="detail-panel">
		<CollectionHeader
			kind="album"
			title={selectedAlbum.title}
			{subtitle}
			{coverUrl}
			{coverAlt}
			{initials}
			{artFill}
			onplay={() => currentAlbumId && playAlbum(currentAlbumId)}
			onrename={onRenameAlbum}
			isShared={selectedAlbum.is_shared}
			shareSlug={selectedAlbum.share_slug}
			onshare={onAlbumShareEnable}
			onunshare={onAlbumShareDisable}
			ondelete={() => (showDeleteConfirm = true)}
			oncover={onCoverAction}
			onremovecover={onCoverRemove}
			onaddtoplaylist={() => (playlistPickerOpen = true)}
		/>
		<input
			bind:this={coverInput}
			class="cover-file-input"
			type="file"
			accept={ALBUM_COVER_ACCEPT}
			disabled={coverBusy}
			onchange={onCoverFile}
		/>

		{#if playlistPickerOpen}
			<div class="picker-anchor">
				<PlaylistPicker onselect={onAddToPlaylist} onclose={() => (playlistPickerOpen = false)} />
			</div>
		{/if}

		<div class="item-list">
			{#if albumLoad?.status === 'loading' && albumSongs.length === 0}
				<p class="empty-tab" role="status">{LIBRARY_ALBUMS_LOADING}</p>
			{:else if albumLoad?.status === 'error' && albumSongs.length === 0}
				<p class="empty-tab" role="alert">{albumLoad.error}</p>
				<button
					class="retry-btn"
					onclick={() => currentAlbumId && loadSongsForAlbum(currentAlbumId)}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if albumSongs.length === 0}
				<p class="empty-tab">No songs in this album yet.</p>
			{:else}
				{#each albumSongs as s (s.id)}
					<div
						class="item-row"
						role="button"
						tabindex="0"
						onclick={() => selectSong(s.id)}
						onkeydown={(e) => e.key === 'Enter' && selectSong(s.id)}
					>
						<button
							class="item-play"
							data-hitbox="frequent"
							disabled={s.generation_count === 0}
							onclick={(e) => {
								e.stopPropagation();
								onRowPlay(s);
							}}
							aria-label={`Play ${s.title}`}
						>
							<Icon name="play" size={14} />
						</button>
						<span class="item-title">{s.title}</span>
						<span class="item-meta">
							{s.generation_count} gen{s.generation_count !== 1 ? 's' : ''}
						</span>
					</div>
				{/each}
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
		padding-bottom: var(--player-height);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.cover-file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.picker-anchor {
		position: relative;
		margin: 0 1.5rem;
	}

	.item-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0 1.5rem;
	}

	.item-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
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

	.item-play {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 1.9rem;
		height: 1.9rem;
		flex-shrink: 0;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: none;
		color: var(--text-muted);
	}

	.item-play:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.item-play:disabled {
		opacity: 0.35;
		cursor: default;
	}

	.item-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item-meta {
		font-size: 0.75rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.empty-tab {
		color: var(--text-subtle);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 1.5rem;
	}

	@media (max-width: 768px) {
		.item-list,
		.picker-anchor {
			padding-left: 0.8rem;
			padding-right: 0.8rem;
		}

		.empty-tab {
			padding: 0.8rem;
		}
	}
</style>
