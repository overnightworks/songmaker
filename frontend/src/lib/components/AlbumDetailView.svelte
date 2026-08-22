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
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/player';
	import { selectSong } from '$lib/stores/navigation';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_ART_INITIAL_COUNT,
		ALBUM_COVER_ACCEPT,
		ALBUM_COVER_ALT_TYPE,
		ALBUM_COVER_REMOVE_LABEL,
		ALBUM_COVER_REPLACE_LABEL,
		ALBUM_COVER_UPLOAD_LABEL,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';
	import { hexToRgb } from '$lib/utils/contrast';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import ActionButton from './ActionButton.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	interface Props {
		albumId?: string;
	}

	let { albumId }: Props = $props();

	let playlistPickerFor = $state<string | null>(null);
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
	const albumGenCount = $derived(albumSongs.reduce((sum, s) => sum + s.generation_count, 0));
	const albumLoad = $derived(currentAlbumId ? $albumSongsLoad[currentAlbumId] : undefined);
	const coverUrl = $derived(selectedAlbum?.cover?.detail ?? null);
	const coverAlt = $derived(
		selectedAlbum ? `${ALBUM_COVER_ALT_TYPE} ${selectedAlbum.title}` : ALBUM_COVER_ALT_TYPE
	);
	const artFill = $derived(selectedAlbum ? usableAlbumPrimary(selectedAlbum.colors) : null);
	const initials = $derived(
		selectedAlbum ? albumTitleInitials(selectedAlbum.title) : ALBUM_ART_EMPTY_INITIALS
	);
	let coverFailed = $state(false);
	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);

	$effect(() => {
		void coverUrl;
		coverFailed = false;
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const coverActionLabel = $derived(
		showCover ? ALBUM_COVER_REPLACE_LABEL : ALBUM_COVER_UPLOAD_LABEL
	);

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

	function albumTitleInitials(title: string): string {
		const trimmed = title.trim();
		if (!trimmed) return ALBUM_ART_EMPTY_INITIALS;
		const words = trimmed.split(/\s+/);
		if (words.length === 1) {
			const letters = Array.from(words[0]).slice(0, ALBUM_ART_INITIAL_COUNT).join('');
			return letters.toUpperCase() || ALBUM_ART_EMPTY_INITIALS;
		}
		const first = Array.from(words[0])[0];
		const second = Array.from(words[1])[0];
		if (!first) return ALBUM_ART_EMPTY_INITIALS;
		return `${first}${second ?? ''}`.toUpperCase();
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
			coverFailed = false;
			addToast('Cover saved', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover upload failed', 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onCoverRemove(): Promise<void> {
		if (!selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await deleteAlbumCover(selectedAlbum.id);
			updateAlbumInList(selectedAlbum.id, () => updated);
			coverFailed = false;
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
		<div class="detail-header">
			<div class="detail-identity">
				<div class="cover-hero">
					{#if showCover && coverUrl}
						<img src={coverUrl} alt={coverAlt} onerror={() => (coverFailed = true)} />
					{:else if artFill}
						<span class="cover-fallback" style:background={artFill} aria-hidden="true"></span>
					{:else}
						<span class="cover-fallback cover-initials" aria-hidden="true">{initials}</span>
					{/if}
					<input
						bind:this={coverInput}
						class="cover-file-input"
						type="file"
						accept={ALBUM_COVER_ACCEPT}
						onchange={onCoverFile}
					/>
					<button
						type="button"
						class="cover-hit"
						onclick={() => coverInput?.click()}
						disabled={coverBusy}
						aria-label={coverActionLabel}
					></button>
					{#if showCover}
						<button
							type="button"
							class="cover-remove"
							onclick={onCoverRemove}
							disabled={coverBusy}
							aria-label={ALBUM_COVER_REMOVE_LABEL}
						>
							×
						</button>
					{/if}
				</div>
				<div class="detail-titles">
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
			</div>
			<div class="detail-actions">
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
					<button class="item-row" onclick={() => selectSong(s.id)}>
						<span class="item-title">{s.title}</span>
						<span class="item-meta">
							{s.generation_count} gen{s.generation_count !== 1 ? 's' : ''}
						</span>
					</button>
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
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.detail-identity {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		min-width: 0;
		flex: 1;
	}

	.detail-titles {
		min-width: 0;
	}

	.cover-hero {
		position: relative;
		width: 4.5rem;
		height: 4.5rem;
		flex-shrink: 0;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.cover-hero img,
	.cover-fallback {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.cover-fallback {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.cover-initials {
		font-family: var(--font-display);
		font-size: 1.1rem;
		letter-spacing: 0.06em;
		user-select: none;
	}

	.cover-file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.cover-hit {
		position: absolute;
		inset: 0;
		padding: 0;
		border: none;
		background: transparent;
		cursor: pointer;
	}

	.cover-hit:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.cover-remove {
		position: absolute;
		top: 0;
		right: 0;
		z-index: 1;
		width: 1.5rem;
		height: 1.5rem;
		padding: 0;
		border: none;
		background: color-mix(in srgb, var(--bg) 75%, transparent);
		color: var(--text);
		font-size: 1rem;
		line-height: 1;
		cursor: pointer;
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
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.empty-tab {
		color: var(--text-subtle);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 0;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 0.5rem;
		}

		.cover-hero {
			width: 3.5rem;
			height: 3.5rem;
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
