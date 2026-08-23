<script lang="ts">
	import { sharePlaylist, unsharePlaylist, createQueueStreamSnapshot } from '$lib/api/client';
	import { playPlaylistEntries, setShuffle } from '$lib/stores/player';
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
		updatePlaylistInList
	} from '$lib/stores/playlists';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { addToast } from '$lib/stores/toast';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import { pinQueueStream, unpinQueueStream } from '$lib/api/queue-streams';
	import {
		saveStream,
		removeStream,
		offlineStreamUrl,
		rememberPlaylistOfflineStream,
		forgetPlaylistOfflineStream,
		loadSavedOfflinePlaylist,
		type StreamProgress
	} from '$lib/services/offline';
	import { selectSong } from '$lib/stores/navigation';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		LIBRARY_RETRY_LABEL,
		PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
		PLAYLIST_ENTRY_MOVE_UP_LABEL,
		PLAYLIST_ENTRY_OPEN_SONG_LABEL,
		PLAYLIST_ENTRY_OVERFLOW_LABEL,
		PLAYLIST_ENTRY_REMOVE_LABEL
	} from '$lib/constants';
	import { nowPlayingTakeLabel } from '$lib/constants/now-playing';
	import { formatTime, titleInitials } from '$lib/utils/format';
	import CollectionHeader from './CollectionHeader.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';

	// The header prefers the lightweight playlist already in playlistList so
	// a slow or failed detail fetch never leaves the previous playlist's
	// header+rows mismatched under the new title (#139). playlistList is not
	// guaranteed populated when a playlist opens (Shares inventory, a deep
	// link, mobile without the Rail mounted, or a failed loadPlaylists) --
	// once the detail itself has loaded for the open id, its own fields
	// stand in for the list entry rather than rendering nothing.
	//
	// The id match only matters while a *different* playlist id is open --
	// that is the one case a stale detail could render under the wrong
	// header. loadPlaylistDetail always sets selectedPlaylistId before its
	// async fetch, so during real navigation this is never null while a
	// fetch for a new id is in flight. When no collection is open at all
	// (selectedPlaylistId is null, e.g. a caller that renders this view
	// directly off selectedPlaylistDetail without going through
	// navigation), there is no "wrong id" to guard against, so the detail
	// is trusted as-is.
	const listEntry = $derived($selectedPlaylist);
	const playlistDetail = $derived(
		$selectedPlaylistId === null
			? $selectedPlaylistDetail
			: $selectedPlaylistDetail && $selectedPlaylistDetail.id === $selectedPlaylistId
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
						created_at: playlistDetail.created_at
					}
				: null)
	);
	const detailLoad = $derived($playlistDetailLoad);
	let reorderBusy = $state(false);
	let showDeleteConfirm = $state(false);
	let overflowId = $state<string | null>(null);
	const initials = $derived(
		playlistMeta ? titleInitials(playlistMeta.title) : ALBUM_ART_EMPTY_INITIALS
	);

	function toggleOverflow(entryId: string, e: MouseEvent): void {
		e.stopPropagation();
		overflowId = overflowId === entryId ? null : entryId;
	}

	function openSongInEditor(songId: string): void {
		overflowId = null;
		selectSong(songId);
	}

	$effect(() => {
		if (!overflowId) return;
		function onClick(): void {
			overflowId = null;
		}
		function onKeydown(event: KeyboardEvent): void {
			if (event.key !== 'Escape') return;
			event.preventDefault();
			overflowId = null;
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
		await refreshSharesAfterMutation();
		return result;
	}

	async function onPlaylistShareDisable() {
		if (!playlistMeta) return;
		await unsharePlaylist(playlistMeta.id);
		updatePlaylistInList(playlistMeta.id, (p) => ({ ...p, is_shared: false, share_slug: null }));
		await refreshSharesAfterMutation();
	}

	async function onPlaylistDelete(): Promise<void> {
		if (!playlistMeta) return;
		const playlistId = playlistMeta.id;
		const saved = await loadSavedOfflinePlaylist(playlistId).catch(() => null);
		try {
			await deletePlaylist(playlistId);
		} catch {
			addToast('Delete failed', 'error');
			return;
		}
		if (saved) {
			try {
				await unpinQueueStream(saved.snapshot_id).catch(() => undefined);
				await removeStream(saved.stream_url, saved.snapshot_id);
				await forgetPlaylistOfflineStream(playlistId);
			} catch {
				addToast('Playlist deleted; offline cleanup failed', 'error');
				return;
			}
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

	function playEntry(index: number): void {
		if (!playlistDetail) return;
		const entry = playlistDetail.entries[index];
		if (entry && isEntryCurrent(entry)) {
			audioPlayer.toggle();
			return;
		}
		setShuffle(false);
		playPlaylistEntries(playlistDetail.entries, index, { restart: true });
	}

	function isEntryCurrent(entry: { generation_id: string; mp3_path: string }): boolean {
		return (
			audioPlayer.current?.generation.id === entry.generation_id &&
			audioPlayer.current?.generation.mp3_path === entry.mp3_path
		);
	}

	function isEntryPlaying(entry: { generation_id: string; mp3_path: string }): boolean {
		return isEntryCurrent(entry) && audioPlayer.status === 'playing';
	}

	function isEntryLoading(entry: { generation_id: string; mp3_path: string }): boolean {
		return (
			isEntryCurrent(entry) &&
			(audioPlayer.status === 'loading' || audioPlayer.status === 'buffering')
		);
	}

	function onEntryKeydown(e: KeyboardEvent, index: number): void {
		if (e.target !== e.currentTarget) return;
		if (e.key !== 'Enter' && e.key !== ' ') return;
		e.preventDefault();
		playEntry(index);
	}

	// ── Offline / Save for offline ──────────────────────────────────────────

	let offlineSaving = $state(false);
	let offlineProgress = $state<StreamProgress | null>(null);
	let offlineSavedStreamUrl = $state<string | null>(null);
	let offlineSavedSnapshotId = $state<string | null>(null);

	$effect(() => {
		let cancelled = false;
		offlineSavedStreamUrl = null;
		offlineSavedSnapshotId = null;
		const id = playlistMeta?.id;
		if (!id) {
			offlineProgress = null;
			return () => {
				cancelled = true;
			};
		}
		void loadSavedOfflinePlaylist(id).then((meta) => {
			if (cancelled || !meta) return;
			offlineSavedStreamUrl = meta.stream_url;
			offlineSavedSnapshotId = meta.snapshot_id;
		});
		return () => {
			cancelled = true;
		};
	});

	const offlineProgressLabel = $derived(
		offlineSaving && offlineProgress && offlineProgress.total
			? `Saving… ${Math.round((offlineProgress.downloaded / offlineProgress.total) * 100)}%`
			: null
	);

	async function onSaveForOffline(): Promise<void> {
		if (!playlistDetail || offlineSaving) return;
		offlineSaving = true;
		offlineProgress = null;
		try {
			const tracks = playlistDetail.entries.map((e) => ({
				generation_id: e.generation_id,
				entry_id: e.id
			}));
			const manifest = await createQueueStreamSnapshot(tracks);
			await saveStream(
				manifest,
				(progress) => {
					offlineProgress = progress;
				},
				(snapshotId) => pinQueueStream(snapshotId).then(() => undefined)
			);
			offlineSavedStreamUrl = offlineStreamUrl(manifest.snapshot_id);
			offlineSavedSnapshotId = manifest.snapshot_id;
			await rememberPlaylistOfflineStream(playlistDetail.id, manifest.snapshot_id);
			addToast('Saved for offline', 'success');
		} catch (err) {
			const msg = err instanceof Error ? err.message : 'Save failed';
			addToast(`Offline save failed: ${msg}`, 'error');
		} finally {
			offlineSaving = false;
			offlineProgress = null;
		}
	}

	async function onRemoveOffline(): Promise<void> {
		if (!playlistMeta || !offlineSavedStreamUrl || !offlineSavedSnapshotId) return;
		try {
			await unpinQueueStream(offlineSavedSnapshotId).catch(() => {
				addToast('Server unpin failed — the download is removed locally.', 'info');
			});
			await removeStream(offlineSavedStreamUrl, offlineSavedSnapshotId);
			await forgetPlaylistOfflineStream(playlistMeta.id);
			offlineSavedStreamUrl = null;
			offlineSavedSnapshotId = null;
			addToast('Offline copy removed', 'info');
		} catch {
			addToast('Remove failed', 'error');
		}
	}

	function onSaveOfflineToggle(): void {
		if (offlineSavedStreamUrl) void onRemoveOffline();
		else void onSaveForOffline();
	}
</script>

{#if $selectedPlaylistId || playlistDetail}
	<div class="detail-panel">
		{#if playlistMeta}
			<CollectionHeader
				kind="playlist"
				title={playlistMeta.title}
				coverUrl={null}
				coverAlt=""
				{initials}
				artFill={null}
				onplay={() => playEntry(0)}
				onrename={onPlaylistRename}
				isShared={playlistMeta.is_shared}
				shareSlug={playlistMeta.share_slug}
				onshare={onPlaylistShareEnable}
				onunshare={onPlaylistShareDisable}
				ondelete={() => (showDeleteConfirm = true)}
				onsaveoffline={onSaveOfflineToggle}
				offlineSaved={Boolean(offlineSavedStreamUrl)}
				{offlineSaving}
				{offlineProgressLabel}
			/>
		{/if}

		<div class="entry-list">
			{#if playlistDetail}
				{#each playlistDetail.entries as entry, i (entry.id)}
					<div
						class="entry-row"
						class:playing={isEntryCurrent(entry)}
						onclick={() => playEntry(i)}
						onkeydown={(e) => onEntryKeydown(e, i)}
						role="button"
						tabindex="0"
						aria-label={`${isEntryPlaying(entry) ? 'Pause' : 'Play'} ${entry.song_title}`}
					>
						<span
							class="entry-play"
							class:playing={isEntryPlaying(entry)}
							class:loading={isEntryLoading(entry)}
							aria-hidden="true"
						>
							{#if isEntryLoading(entry)}
								<span class="spinner"></span>
							{:else}
								<Icon name={isEntryPlaying(entry) ? 'pause' : 'play'} size={16} />
							{/if}
						</span>
						<div class="entry-info">
							<span class="entry-title">
								{#if entry.is_picked}<span class="picked-star">★</span>{/if}
								{entry.song_title}
							</span>
							<span class="entry-meta">
								{entry.artist} · {nowPlayingTakeLabel(
									entry.version_number,
									entry.generation_number
								)}{#if entry.audio_duration !== null && entry.audio_duration > 0}
									· {formatTime(entry.audio_duration)}{/if}
							</span>
						</div>
						<div class="entry-actions">
							<div class="entry-overflow-anchor">
								<button
									type="button"
									class="overflow-btn"
									data-hitbox="frequent"
									data-hitbox-face
									aria-haspopup="menu"
									aria-expanded={overflowId === entry.id}
									aria-label={`${PLAYLIST_ENTRY_OVERFLOW_LABEL} for ${entry.song_title}`}
									onclick={(e) => toggleOverflow(entry.id, e)}
								>
									<Icon name="more-horizontal" size={16} />
								</button>
								{#if overflowId === entry.id}
									<div
										class="entry-overflow-menu"
										role="menu"
										data-escape-overlay="true"
										tabindex="-1"
										onclick={(e) => e.stopPropagation()}
										onkeydown={(e) => e.stopPropagation()}
									>
										<button
											type="button"
											role="menuitem"
											class="entry-overflow-item"
											data-hitbox="frequent"
											onclick={() => openSongInEditor(entry.song_id)}
										>
											{PLAYLIST_ENTRY_OPEN_SONG_LABEL}
										</button>
										{#if i > 0}
											<button
												type="button"
												role="menuitem"
												class="entry-overflow-item"
												data-hitbox="frequent"
												disabled={reorderBusy}
												onclick={() => {
													overflowId = null;
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
													overflowId = null;
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
												overflowId = null;
												void onRemoveEntry(entry.id);
											}}
										>
											{PLAYLIST_ENTRY_REMOVE_LABEL}
										</button>
									</div>
								{/if}
							</div>
						</div>
					</div>
				{/each}
				{#if playlistDetail.entries.length === 0}
					<p class="empty-tab">No tracks in this playlist yet.</p>
				{/if}
			{:else if detailLoad.status === 'error'}
				<p class="empty-tab" role="alert">{detailLoad.error}</p>
				<button
					class="retry-btn"
					onclick={() => $selectedPlaylistId && loadPlaylistDetail($selectedPlaylistId)}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else}
				<p class="empty-tab" role="status">Loading playlist…</p>
			{/if}
		</div>
	</div>
{/if}

{#if showDeleteConfirm && playlistMeta}
	<ConfirmDeleteDialog
		title={`Delete "${playlistMeta.title}"?`}
		items={[`${playlistMeta.entry_count} track${playlistMeta.entry_count !== 1 ? 's' : ''}`]}
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

	.entry-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0 1.5rem;
	}

	.entry-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-height: 64px;
		padding: 0.65rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		color: var(--text);
		cursor: pointer;
		text-align: left;
		transition:
			background 0.15s,
			border-color 0.15s,
			box-shadow 0.15s;
	}

	.entry-row:hover {
		border-color: rgba(160, 32, 240, 0.3);
		background: var(--surface-hover);
		box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 7%, transparent);
	}

	.entry-row.playing {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.entry-play {
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: color-mix(in srgb, var(--bg) 30%, transparent);
		color: var(--text-muted);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		transition:
			border-color 0.15s,
			color 0.15s,
			background 0.15s;
	}

	.entry-row:hover .entry-play {
		border-color: var(--primary);
		color: var(--primary);
	}

	.entry-play.playing,
	.entry-play.loading {
		border-color: var(--accent);
		color: var(--accent);
	}

	.spinner {
		display: inline-block;
		width: 0.95rem;
		height: 0.95rem;
		border: 2px solid var(--accent);
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.entry-info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.entry-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 1rem;
	}

	.picked-star {
		color: var(--accent);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.entry-meta {
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.entry-actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
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

		.entry-row {
			align-items: flex-start;
			gap: 0.6rem;
			padding: 0.7rem;
		}

		.entry-actions {
			gap: 0.35rem;
		}
	}
</style>
