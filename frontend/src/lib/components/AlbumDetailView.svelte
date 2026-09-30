<script lang="ts">
	import {
		archiveAlbum,
		deleteAlbum,
		deleteAlbumCover,
		restoreAlbum,
		shareAlbum,
		unarchiveAlbum,
		unshareAlbum,
		updateAlbum,
		uploadAlbumCover
	} from '$lib/api/client';
	import { describeFailure } from '$lib/api/fetch';
	import { fetchSongs } from '$lib/api/songs';
	import {
		albumList,
		albumSongsLoad,
		albumSongsLoadFailure,
		songList,
		loadSongsForAlbum,
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/libraryData';
	import { curateAlbum, isSongCurrent, selectedAlbumId, playAlbum } from '$lib/stores/player';
	import { historyLayerState, selectSong } from '$lib/stores/navigation';
	import { setOpenCollection } from '$lib/stores/collection';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ACCEPT,
		ALBUM_COVER_ALT_TYPE,
		ALBUM_NO_SONGS,
		ALBUM_YEAR_MAX,
		ALBUM_YEAR_MIN,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_RETRY_LABEL,
		NEW_SONG_ROW_LABEL
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import AlbumCoverEditor from './AlbumCoverEditor.svelte';
	import AlbumMetaEditor from './AlbumMetaEditor.svelte';
	import CollectionHeader from './CollectionHeader.svelte';
	import PlayingMark from './PlayingMark.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';
	import NewSongCard from './NewSongCard.svelte';

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
	// Nothing to play is decided here once, from the songs the view shows: an
	// album without songs, or whose songs have no take yet, gives the header
	// nothing to start, so neither of its controls can reach the running queue.
	const albumHasTakes = $derived(albumSongs.some((s) => s.generation_count > 0));
	const albumLoad = $derived(currentAlbumId ? $albumSongsLoad[currentAlbumId] : undefined);
	const albumLoadFailure = $derived(currentAlbumId ? albumSongsLoadFailure(currentAlbumId) : null);
	const coverUrl = $derived(selectedAlbum?.cover?.detail ?? null);
	const coverAlt = $derived(
		selectedAlbum ? `${ALBUM_COVER_ALT_TYPE} ${selectedAlbum.title}` : ALBUM_COVER_ALT_TYPE
	);
	const artFill = $derived(selectedAlbum ? usableAlbumPrimary(selectedAlbum.colors) : null);
	const initials = $derived(
		selectedAlbum ? titleInitials(selectedAlbum.title) : ALBUM_ART_EMPTY_INITIALS
	);
	// Holds the album the card adds to, so a card opened on one album never
	// shows on the next one this view is reused for.
	const newSongIn = historyLayerState<string | null>('album-new-song', null);
	const newSongOpen = $derived(currentAlbumId !== undefined && $newSongIn === currentAlbumId);
	let newSongRow: HTMLButtonElement | undefined = $state();
	let newSongShown = false;
	let focusRowOnFold = true;

	$effect(() => {
		if (newSongShown && !newSongOpen && focusRowOnFold) newSongRow?.focus();
		focusRowOnFold = true;
		newSongShown = newSongOpen;
	});

	function startNewSong(): void {
		$newSongIn = currentAlbumId ?? null;
	}

	function cancelNewSong(): void {
		$newSongIn = null;
	}

	function foldCreatedSong(): void {
		focusRowOnFold = false;
		$newSongIn = null;
	}

	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);

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
			addToast(describeFailure(e, 'Cover upload failed'), 'error');
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
			addToast(describeFailure(e, 'Cover remove failed'), 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onRenameAlbum(newTitle: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			const updated = await updateAlbum(albumId, { title: newTitle });
			updateAlbumInList(albumId, () => updated);
			addToast('Album renamed', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Rename failed'), 'error');
			throw e;
		}
	}

	async function onSaveAlbumSubtitle(newSubtitle: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			const updated = await updateAlbum(albumId, { subtitle: newSubtitle });
			updateAlbumInList(albumId, () => updated);
		} catch (e) {
			addToast(describeFailure(e, 'Update failed'), 'error');
			throw e;
		}
	}

	async function onSaveAlbumYear(newYear: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		const year = newYear ? Number(newYear) : null;
		if (newYear && !Number.isInteger(year)) {
			addToast('Year must be a whole number', 'error');
			throw new Error('Year must be a whole number');
		}
		if (year !== null && (year < ALBUM_YEAR_MIN || year > ALBUM_YEAR_MAX)) {
			addToast(`Year must be between ${ALBUM_YEAR_MIN} and ${ALBUM_YEAR_MAX}`, 'error');
			throw new Error('Year out of range');
		}
		try {
			const updated = await updateAlbum(albumId, { year });
			updateAlbumInList(albumId, () => updated);
		} catch (e) {
			addToast(describeFailure(e, 'Update failed'), 'error');
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

	async function onAlbumArchive(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await archiveAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
			addUndoToast('Album archived', {
				label: 'Undo',
				handler: async () => {
					try {
						const restored = await unarchiveAlbum(albumId);
						addAlbumToList(restored);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast('Album unarchived', 'success');
					} catch {
						addToast('Unarchive failed', 'error');
					}
				}
			});
		} catch {
			addToast('Archive failed', 'error');
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
			addToast(describeFailure(e, 'Failed to add'), 'error');
		} finally {
			playlistPickerOpen = false;
		}
	}

	function onCurate(): void {
		if (!currentAlbumId) return;
		void curateAlbum(currentAlbumId);
	}
</script>

{#if selectedAlbum}
	<div class="detail-panel">
		<CollectionHeader
			kind="album"
			collectionId={selectedAlbum.id}
			title={selectedAlbum.title}
			{coverUrl}
			{coverAlt}
			{initials}
			{artFill}
			onplay={currentAlbumId && albumHasTakes ? (start) => playAlbum(currentAlbumId, start) : null}
			onrename={onRenameAlbum}
			isShared={selectedAlbum.is_shared}
			shareSlug={selectedAlbum.share_slug}
			onshare={onAlbumShareEnable}
			onunshare={onAlbumShareDisable}
			ondelete={() => (showDeleteConfirm = true)}
			onarchive={onAlbumArchive}
			oncover={onCoverAction}
			onremovecover={onCoverRemove}
			onaddtoplaylist={() => (playlistPickerOpen = true)}
			oncurate={onCurate}
		>
			{#snippet metaEditor()}
				<AlbumMetaEditor
					subtitle={selectedAlbum.subtitle}
					year={selectedAlbum.year}
					onsavesubtitle={onSaveAlbumSubtitle}
					onsaveyear={onSaveAlbumYear}
				/>
			{/snippet}
			{#snippet coverEditor(close: () => void)}
				<AlbumCoverEditor
					album={selectedAlbum}
					onclose={close}
					onupload={onCoverAction}
					onremove={onCoverRemove}
				/>
			{/snippet}
		</CollectionHeader>
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
			{#if albumLoad === 'loading' && albumSongs.length === 0}
				<p class="empty-tab" role="status">{LIBRARY_ALBUMS_LOADING}</p>
			{:else if $albumLoadFailure && albumSongs.length === 0}
				<p class="empty-tab" role="alert">{$albumLoadFailure}</p>
				<button
					class="retry-btn"
					onclick={() => currentAlbumId && loadSongsForAlbum(currentAlbumId)}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if albumSongs.length > 0 || albumLoad !== 'unreachable'}
				{#if albumSongs.length === 0}
					<p class="empty-tab">{ALBUM_NO_SONGS}</p>
				{/if}
				{#each albumSongs as s (s.id)}
					{@const current = isSongCurrent(s.id)}
					<div class="item-row" class:current>
						<button class="item-body" data-hitbox="text" onclick={() => selectSong(s.id)}>
							<PlayingMark {current} />
							<span class="item-title">{s.title}</span>
							<span class="item-meta">
								{s.generation_count} take{s.generation_count !== 1 ? 's' : ''}
							</span>
						</button>
					</div>
				{/each}
				{#if newSongOpen}
					<NewSongCard album={selectedAlbum} oncancel={cancelNewSong} oncreated={foldCreatedSong} />
				{:else}
					<div class="item-row new-song-row">
						<button
							bind:this={newSongRow}
							class="item-body"
							data-hitbox="text"
							onclick={startNewSong}
						>
							<Icon name="plus" size={16} />
							<span class="item-title">{NEW_SONG_ROW_LABEL}</span>
						</button>
					</div>
				{/if}
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
			`${totalGens} take${totalGens !== 1 ? 's' : ''}`,
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
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		font-size: 0.93rem;
	}

	.item-row:hover {
		border-color: var(--primary);
		background: var(--surface-hover);
	}

	.new-song-row {
		color: var(--text-muted);
	}

	.new-song-row,
	.new-song-row:hover {
		border-color: transparent;
		background: none;
	}

	.new-song-row:hover {
		color: var(--text);
	}

	.item-row.current {
		border-color: var(--primary);
	}

	.item-row.current .item-title {
		color: var(--primary);
	}

	.item-body {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex: 1;
		min-width: 0;
		background: none;
		border: none;
		padding: 0.65rem 0.8rem;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	/* The global press scale would shrink the target mid-press and send a release
	   near the row's edge to the row. */
	.item-row .item-body:active:not(:disabled) {
		transform: none;
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

	.retry-btn {
		display: block;
		margin: 0.4rem 1.5rem 0.8rem;
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	@media (max-width: 768px) {
		.item-list,
		.picker-anchor {
			padding-left: 0.8rem;
			padding-right: 0.8rem;
		}

		.item-row {
			min-height: 62px;
		}

		.empty-tab {
			padding: 0.8rem;
		}

		.retry-btn {
			margin-inline: 0.8rem;
		}
	}
</style>
