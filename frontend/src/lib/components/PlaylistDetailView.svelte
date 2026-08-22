<script lang="ts">
	import { sharePlaylist, unsharePlaylist, createQueueStreamSnapshot } from '$lib/api/client';
	import { playPlaylistEntries, setShuffle } from '$lib/stores/player';
	import {
		selectedPlaylistDetail,
		deletePlaylist,
		renamePlaylist,
		removePlaylistEntry,
		movePlaylistEntry
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
		PLAYLIST_ENTRY_MOVE_DOWN_LABEL,
		PLAYLIST_ENTRY_MOVE_UP_LABEL,
		PLAYLIST_ENTRY_OPEN_SONG_LABEL,
		PLAYLIST_ENTRY_OVERFLOW_LABEL,
		PLAYLIST_ENTRY_REMOVE_LABEL
	} from '$lib/constants';
	import { formatTime, titleInitials } from '$lib/utils/format';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import CollectionHeader from './CollectionHeader.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';

	const playlistDetail = $derived($selectedPlaylistDetail);
	let reorderBusy = $state(false);
	let showDeleteConfirm = $state(false);
	let overflowId = $state<string | null>(null);
	let compact = $state(false);
	const initials = $derived(
		playlistDetail ? titleInitials(playlistDetail.title) : ALBUM_ART_EMPTY_INITIALS
	);

	$effect(() => {
		return subscribeCompactLayout((value) => {
			compact = value;
		});
	});

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
		if (!playlistDetail) throw new Error('No playlist');
		const result = await sharePlaylist(playlistDetail.id);
		selectedPlaylistDetail.update((d) =>
			d ? { ...d, is_shared: true, share_slug: result.share_slug } : d
		);
		await refreshSharesAfterMutation();
		return result;
	}

	async function onPlaylistShareDisable() {
		if (!playlistDetail) return;
		await unsharePlaylist(playlistDetail.id);
		selectedPlaylistDetail.update((d) => (d ? { ...d, is_shared: false, share_slug: null } : d));
		await refreshSharesAfterMutation();
	}

	async function onPlaylistDelete(): Promise<void> {
		if (!playlistDetail) return;
		const playlistId = playlistDetail.id;
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
		if (!playlistDetail) return;
		try {
			await renamePlaylist(playlistDetail.id, newTitle);
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
		const detail = $selectedPlaylistDetail;
		if (!detail) {
			offlineProgress = null;
			return () => {
				cancelled = true;
			};
		}
		void loadSavedOfflinePlaylist(detail.id).then((meta) => {
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
		if (!playlistDetail || !offlineSavedStreamUrl || !offlineSavedSnapshotId) return;
		try {
			await unpinQueueStream(offlineSavedSnapshotId).catch(() => {
				addToast('Server unpin failed — the download is removed locally.', 'info');
			});
			await removeStream(offlineSavedStreamUrl, offlineSavedSnapshotId);
			await forgetPlaylistOfflineStream(playlistDetail.id);
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

{#if playlistDetail}
	<div class="detail-panel">
		<CollectionHeader
			kind="playlist"
			title={playlistDetail.title}
			coverUrl={null}
			coverAlt=""
			{initials}
			artFill={null}
			onplay={() => playEntry(0)}
			onrename={onPlaylistRename}
			isShared={playlistDetail.is_shared}
			shareSlug={playlistDetail.share_slug}
			onshare={onPlaylistShareEnable}
			onunshare={onPlaylistShareDisable}
			ondelete={() => (showDeleteConfirm = true)}
			onsaveoffline={onSaveOfflineToggle}
			offlineSaved={Boolean(offlineSavedStreamUrl)}
			{offlineSaving}
			{offlineProgressLabel}
		/>

		<div class="entry-list">
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
							{entry.artist} · Gen #{entry.generation_number}{#if entry.version_number !== null}
								· v{entry.version_number}{/if}{#if entry.audio_duration !== null && entry.audio_duration > 0}
								· {formatTime(entry.audio_duration)}{/if}
						</span>
					</div>
					<div class="entry-actions">
						{#if !compact}
							<div class="entry-controls">
								{#if i > 0}
									<button
										class="move-btn"
										data-hitbox="frequent"
										data-hitbox-face
										onclick={(e) => {
											e.stopPropagation();
											void onMoveEntry(entry.id, i - 1);
										}}
										disabled={reorderBusy}
										title={PLAYLIST_ENTRY_MOVE_UP_LABEL}
										aria-label={`${PLAYLIST_ENTRY_MOVE_UP_LABEL} ${entry.song_title}`}
									>
										<Icon name="chevron-up" size={14} />
									</button>
								{/if}
								{#if i < playlistDetail.entries.length - 1}
									<button
										class="move-btn"
										data-hitbox="frequent"
										data-hitbox-face
										onclick={(e) => {
											e.stopPropagation();
											void onMoveEntry(entry.id, i + 1);
										}}
										disabled={reorderBusy}
										title={PLAYLIST_ENTRY_MOVE_DOWN_LABEL}
										aria-label={`${PLAYLIST_ENTRY_MOVE_DOWN_LABEL} ${entry.song_title}`}
									>
										<Icon name="chevron-down" size={14} />
									</button>
								{/if}
							</div>
							<button
								class="remove-btn"
								data-hitbox="frequent"
								data-hitbox-face
								onclick={(e) => {
									e.stopPropagation();
									void onRemoveEntry(entry.id);
								}}
								title={PLAYLIST_ENTRY_REMOVE_LABEL}
								aria-label={`${PLAYLIST_ENTRY_REMOVE_LABEL}: ${entry.song_title}`}
							>
								<Icon name="x" size={14} />
							</button>
						{/if}
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
									{#if compact}
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
									{/if}
								</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
			{#if playlistDetail.entries.length === 0}
				<p class="empty-tab">No tracks in this playlist yet.</p>
			{/if}
		</div>
	</div>
{/if}

{#if showDeleteConfirm && playlistDetail}
	<ConfirmDeleteDialog
		title={`Delete "${playlistDetail.title}"?`}
		items={[
			`${playlistDetail.entries.length} track${playlistDetail.entries.length !== 1 ? 's' : ''}`
		]}
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

	.entry-controls {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex-shrink: 0;
	}

	@media (any-pointer: coarse) {
		.entry-controls {
			flex-direction: row;
		}
	}

	:global(html[data-pointer='coarse']) .entry-controls {
		flex-direction: row;
	}

	.move-btn {
		color: var(--text-muted);
		line-height: 1;
		opacity: 0.7;
		transition:
			opacity 0.15s,
			color 0.15s;
	}

	.entry-row:hover .move-btn {
		opacity: 1;
	}

	.move-btn:hover {
		color: var(--primary);
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

	.remove-btn {
		color: var(--text-muted);
		line-height: 1;
		transition: color 0.15s;
	}

	.remove-btn:hover {
		color: var(--score-bad);
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
