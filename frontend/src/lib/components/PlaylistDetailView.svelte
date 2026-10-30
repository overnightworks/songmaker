<script lang="ts">
	import { sharePlaylist, unsharePlaylist } from '#lib/api/client.ts';
	import { describeFailure } from '#lib/api/fetch.ts';
	import {
		isPlaylistEntryCurrent,
		playPlaylist,
		playPlaylistEntry,
		queueContext
	} from '#lib/stores/player.ts';
	import {
		selectedPlaylist,
		selectedPlaylistDetail,
		selectedPlaylistId,
		playlistDetailLoad,
		loadPlaylistDetail,
		deletePlaylist,
		renamePlaylist,
		removePlaylistEntry,
		movePlaylistEntry,
		updatePlaylistInList,
		uploadPlaylistCover,
		deletePlaylistCover
	} from '#lib/stores/playlists.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import { selectSong } from '#lib/stores/navigation.ts';
	import { historyLayerState } from '#lib/stores/layers.ts';
	import { handleFocusTrapKeydown } from '#lib/utils/focus-trap.ts';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ACCEPT,
		LIBRARY_RETRY_LABEL,
		PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
		PLAYLIST_ENTRY_MOVE_UP_LABEL,
		PLAYLIST_ENTRY_REMOVE_LABEL,
		playlistEntryOverflowLabel
	} from '#lib/constants.ts';
	import { nowPlayingTakeMeta } from '#lib/constants/now-playing.ts';
	import { songCountLabel, titleInitials } from '#lib/utils/format.ts';
	import CollectionHeader from './CollectionHeader.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';
	import SongRow from './SongRow.svelte';

	// The header prefers the lightweight playlist already in playlistList so
	// a slow or failed detail fetch never leaves the previous playlist's
	// header+rows mismatched under the new title (#139). playlistList is not
	// guaranteed populated when a playlist opens (Shares inventory, a deep
	// link, mobile without the Rail mounted, or a failed loadPlaylists) --
	// once the detail itself has loaded for the open id, its own fields
	// stand in for the list entry rather than rendering nothing.
	const listEntry = $derived($selectedPlaylist);
	const playlistDetail = $derived(
		$selectedPlaylistDetail && $selectedPlaylistDetail.id === $selectedPlaylistId
			? $selectedPlaylistDetail
			: null
	);
	const playlistMeta = $derived(
		listEntry ??
			(playlistDetail
				? {
						id: playlistDetail.id,
						title: playlistDetail.title,
						entry_count: playlistDetail.entry_count,
						is_shared: playlistDetail.is_shared,
						share_slug: playlistDetail.share_slug,
						cover: playlistDetail.cover,
						album_covers: playlistDetail.album_covers,
						created_at: playlistDetail.created_at
					}
				: null)
	);
	const detailLoad = $derived($playlistDetailLoad);
	let reorderBusy = $state(false);
	let showDeleteConfirm = $state(false);
	const overflowId = historyLayerState<string | null>('playlist-entry-menu', null);
	let overflowMenuEl: HTMLDivElement | undefined = $state();
	const initials = $derived(
		playlistMeta ? titleInitials(playlistMeta.title) : ALBUM_ART_EMPTY_INITIALS
	);
	const coverUrl = $derived(playlistMeta?.cover?.detail ?? null);
	const coverAlt = $derived(
		playlistMeta ? `Playlist cover for ${playlistMeta.title}` : 'Playlist cover'
	);
	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);

	function toggleOverflow(entryId: string, e: MouseEvent): void {
		e.stopPropagation();
		$overflowId = $overflowId === entryId ? null : entryId;
	}

	function openSongInEditor(songId: string): void {
		$overflowId = null;
		selectSong(songId);
	}

	$effect(() => {
		if (!$overflowId) return;
		function onClick(): void {
			$overflowId = null;
		}
		function onKeydown(event: KeyboardEvent): void {
			if (!overflowMenuEl) return;
			handleFocusTrapKeydown(overflowMenuEl, event);
		}
		document.addEventListener('click', onClick);
		document.addEventListener('keydown', onKeydown, true);
		return () => {
			document.removeEventListener('click', onClick);
			document.removeEventListener('keydown', onKeydown, true);
		};
	});

	async function onPlaylistShareEnable() {
		if (!playlistMeta) throw new Error('No playlist');
		const result = await sharePlaylist(playlistMeta.id);
		updatePlaylistInList(playlistMeta.id, (p) => ({
			...p,
			is_shared: true,
			share_slug: result.share_slug
		}));
		return result;
	}

	async function onPlaylistShareDisable() {
		if (!playlistMeta) return;
		await unsharePlaylist(playlistMeta.id);
		updatePlaylistInList(playlistMeta.id, (p) => ({ ...p, is_shared: false, share_slug: null }));
	}

	async function onPlaylistDelete(): Promise<void> {
		if (!playlistMeta) return;
		const playlistId = playlistMeta.id;
		try {
			await deletePlaylist(playlistId);
		} catch {
			addToast('Delete failed', 'error');
			return;
		}
		addToast('Playlist deleted', 'success');
	}

	async function onPlaylistRename(newTitle: string): Promise<void> {
		if (!playlistMeta) return;
		try {
			await renamePlaylist(playlistMeta.id, newTitle);
		} catch {
			addToast('Rename failed', 'error');
			throw new Error('Rename failed');
		}
	}

	async function onCoverFile(event: Event): Promise<void> {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !playlistMeta) return;
		coverBusy = true;
		try {
			await uploadPlaylistCover(playlistMeta.id, file);
			addToast('Cover saved', 'success');
		} catch (error) {
			addToast(describeFailure(error, 'Cover upload failed'), 'error');
		} finally {
			coverBusy = false;
		}
	}

	function onCoverAction(): void {
		coverInput?.click();
	}

	async function onCoverRemove(): Promise<void> {
		if (!playlistMeta) return;
		coverBusy = true;
		try {
			await deletePlaylistCover(playlistMeta.id);
			addToast('Cover removed', 'success');
		} catch (error) {
			addToast(describeFailure(error, 'Cover remove failed'), 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onRemoveEntry(entryId: string): Promise<void> {
		if (!playlistDetail) return;
		try {
			await removePlaylistEntry(playlistDetail.id, entryId);
		} catch {
			addToast('Remove failed', 'error');
		}
	}

	async function onMoveEntry(entryId: string, newPos: number): Promise<void> {
		if (!playlistDetail || reorderBusy) return;
		reorderBusy = true;
		try {
			await movePlaylistEntry(playlistDetail.id, entryId, newPos);
		} catch {
			addToast('Reorder failed', 'error');
		} finally {
			reorderBusy = false;
		}
	}

	// The header can show a newly opened playlist before its detail arrives;
	// until then, and while the playlist holds no entry, this view has nothing
	// to start, so the header plays nothing rather than the previously opened
	// playlist or the library.
	const playWhole = $derived(
		playlistDetail && playlistDetail.entries.length > 0 ? () => playPlaylist(playlistDetail) : null
	);

	// The row is the play target: a tap plays this take from here, with the
	// rest of the playlist queued behind it, and keeps the listener on the page.
	function playEntry(index: number): void {
		if (!playlistDetail) return;
		void playPlaylistEntry(playlistDetail, index);
	}
</script>

{#if $selectedPlaylistId}
	<div class="detail-panel">
		{#if playlistMeta}
			<CollectionHeader
				kind="playlist"
				collectionId={playlistMeta.id}
				title={playlistMeta.title}
				{coverUrl}
				{coverAlt}
				{initials}
				artFill={null}
				playlistCovers={playlistMeta.album_covers}
				playlistCover={playlistMeta.cover}
				onplay={playWhole}
				songCount={playlistMeta.entry_count}
				onrename={onPlaylistRename}
				isShared={playlistMeta.is_shared}
				shareSlug={playlistMeta.share_slug}
				onshare={onPlaylistShareEnable}
				onunshare={onPlaylistShareDisable}
				ondelete={() => (showDeleteConfirm = true)}
				oncover={onCoverAction}
				onremovecover={onCoverRemove}
			/>
			<input
				bind:this={coverInput}
				class="cover-file-input"
				type="file"
				accept={ALBUM_COVER_ACCEPT}
				disabled={coverBusy}
				onchange={onCoverFile}
			/>
		{/if}

		<div class="entry-list">
			{#if playlistDetail}
				<!-- The explicit role keeps the list semantics that `list-style: none`
				     strips in Safari/VoiceOver. -->
				<ul class="entry-rows" role="list">
					{#each playlistDetail.entries as entry, i (entry.id)}
						<li class="entry-row">
							<SongRow
								title={entry.song_title}
								detail={nowPlayingTakeMeta({
									artist: entry.artist,
									versionNumber: entry.version_number,
									generationNumber: entry.generation_number,
									durationSec: entry.audio_duration
								})}
								picked={entry.is_picked}
								current={isPlaylistEntryCurrent(entry, $queueContext)}
								onclick={() => playEntry(i)}
								onedit={() => openSongInEditor(entry.song_id)}
							>
								{#snippet menu()}
									<div class="entry-overflow-anchor">
										<button
											type="button"
											class="overflow-btn"
											data-hitbox="frequent"
											data-hitbox-face
											aria-haspopup="menu"
											aria-expanded={$overflowId === entry.id}
											aria-label={playlistEntryOverflowLabel(entry.song_title)}
											onclick={(e) => toggleOverflow(entry.id, e)}
										>
											<Icon name="more-horizontal" size={16} />
										</button>
										{#if $overflowId === entry.id}
											<div
												bind:this={overflowMenuEl}
												class="entry-overflow-menu"
												role="menu"
												tabindex="-1"
												onclick={(e) => e.stopPropagation()}
												onkeydown={(e) => e.stopPropagation()}
											>
												{#if i > 0}
													<button
														type="button"
														role="menuitem"
														class="entry-overflow-item"
														data-hitbox="frequent"
														disabled={reorderBusy}
														onclick={() => {
															$overflowId = null;
															void onMoveEntry(entry.id, i - 1);
														}}
													>
														{PLAYLIST_ENTRY_MOVE_UP_LABEL}
													</button>
												{/if}
												{#if i < playlistDetail.entries.length - 1}
													<button
														type="button"
														role="menuitem"
														class="entry-overflow-item"
														data-hitbox="frequent"
														disabled={reorderBusy}
														onclick={() => {
															$overflowId = null;
															void onMoveEntry(entry.id, i + 1);
														}}
													>
														{PLAYLIST_ENTRY_MOVE_DOWN_LABEL}
													</button>
												{/if}
												<button
													type="button"
													role="menuitem"
													class="entry-overflow-item"
													data-hitbox="frequent"
													onclick={() => {
														$overflowId = null;
														void onRemoveEntry(entry.id);
													}}
												>
													{PLAYLIST_ENTRY_REMOVE_LABEL}
												</button>
											</div>
										{/if}
									</div>
								{/snippet}
							</SongRow>
						</li>
					{/each}
				</ul>
				{#if playlistDetail.entries.length === 0}
					<p class="empty-tab">No songs in this playlist yet.</p>
				{/if}
			{:else if detailLoad.status === 'error'}
				<p class="empty-tab" role="alert">{detailLoad.error}</p>
				<button
					class="retry-btn"
					onclick={() => $selectedPlaylistId && loadPlaylistDetail($selectedPlaylistId)}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if detailLoad.status !== 'unreachable'}
				<p class="empty-tab" role="status">Loading playlist…</p>
			{/if}
		</div>
	</div>
{/if}

{#if showDeleteConfirm && playlistMeta}
	<ConfirmDeleteDialog
		title={`Delete "${playlistMeta.title}"?`}
		items={[songCountLabel(playlistMeta.entry_count)]}
		confirmLabel="Delete Playlist"
		onconfirm={() => {
			showDeleteConfirm = false;
			onPlaylistDelete();
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

	.entry-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0 1.5rem;
	}

	.entry-rows {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.entry-overflow-anchor {
		position: relative;
	}

	.overflow-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		padding: 0.15rem 0.3rem;
		cursor: pointer;
	}

	.overflow-btn:hover,
	.overflow-btn[aria-expanded='true'] {
		border-color: var(--primary);
		color: var(--primary);
	}

	.entry-overflow-menu {
		position: absolute;
		right: 0;
		top: calc(100% + 4px);
		z-index: 5;
		min-width: 10rem;
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.25rem;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
	}

	.entry-overflow-item {
		display: flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		background: none;
		border: none;
		text-align: left;
		padding: 0.4rem 0.55rem;
		color: var(--text-muted);
		font-size: 0.75rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
		border-radius: 3px;
	}

	.entry-overflow-item:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.empty-tab {
		color: var(--text-subtle);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 0;
	}

	.retry-btn {
		display: block;
		margin: 0.4rem 0 0.8rem;
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
		.entry-list {
			padding: 0 0.8rem;
		}
	}
</style>
