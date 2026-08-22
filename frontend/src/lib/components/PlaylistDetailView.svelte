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
	import { ALBUM_ART_EMPTY_INITIALS } from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import CollectionHeader from './CollectionHeader.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';

	const playlistDetail = $derived($selectedPlaylistDetail);
	let reorderBusy = $state(false);
	let showDeleteConfirm = $state(false);
	const initials = $derived(
		playlistDetail ? titleInitials(playlistDetail.title) : ALBUM_ART_EMPTY_INITIALS
	);
	const subtitle = $derived(
		playlistDetail
			? `${playlistDetail.entries.length} track${playlistDetail.entries.length !== 1 ? 's' : ''}`
			: ''
	);

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
			{subtitle}
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
						<span class="entry-title">{entry.song_title}</span>
						<span class="entry-meta">
							{entry.artist} · Gen #{entry.generation_number}
						</span>
					</div>
					<div class="entry-actions">
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
									title="Move up"
									aria-label={`Move ${entry.song_title} up`}
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
									title="Move down"
									aria-label={`Move ${entry.song_title} down`}
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
							title="Remove from playlist"
							aria-label={`Remove ${entry.song_title} from playlist`}
						>
							<Icon name="x" size={14} />
						</button>
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
