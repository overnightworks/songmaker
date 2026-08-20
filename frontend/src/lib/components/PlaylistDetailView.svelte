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
	import { deselectPlaylistView } from '$lib/stores/navigation';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { addToast } from '$lib/stores/toast';
	import { pinQueueStream, unpinQueueStream } from '$lib/api/queue-streams';
	import {
		saveStream,
		removeStream,
		isStreamSaved,
		offlineStreamUrl,
		type StreamProgress
	} from '$lib/services/offline';
	import ActionButton from './ActionButton.svelte';
	import Icon from './Icon.svelte';
	import ShareButton from './ShareButton.svelte';

	const playlistDetail = $derived($selectedPlaylistDetail);

	async function onPlaylistShareEnable() {
		if (!playlistDetail) throw new Error('No playlist');
		const result = await sharePlaylist(playlistDetail.id);
		selectedPlaylistDetail.update((d) =>
			d ? { ...d, is_shared: true, share_slug: result.share_slug } : d
		);
		return result;
	}

	async function onPlaylistShareDisable() {
		if (!playlistDetail) return;
		await unsharePlaylist(playlistDetail.id);
		selectedPlaylistDetail.update((d) => (d ? { ...d, is_shared: false, share_slug: null } : d));
	}

	async function onPlaylistDelete(): Promise<void> {
		if (!playlistDetail) return;
		try {
			await deletePlaylist(playlistDetail.id);
			addToast('Playlist deleted', 'success');
		} catch {
			addToast('Delete failed', 'error');
		}
	}

	async function onPlaylistRename(): Promise<void> {
		if (!playlistDetail) return;
		const newTitle = prompt('Rename playlist:', playlistDetail.title);
		if (newTitle && newTitle.trim()) {
			try {
				await renamePlaylist(playlistDetail.id, newTitle.trim());
			} catch {
				addToast('Rename failed', 'error');
			}
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
		if (!playlistDetail) return;
		try {
			await movePlaylistEntry(playlistDetail.id, entryId, newPos);
		} catch {
			addToast('Reorder failed', 'error');
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

	function playSequential(): void {
		if (!playlistDetail || playlistDetail.entries.length === 0) return;
		setShuffle(false);
		playPlaylistEntries(playlistDetail.entries, 0, { restart: true });
	}

	function playShuffled(): void {
		if (!playlistDetail || playlistDetail.entries.length === 0) return;
		setShuffle(true);
		playPlaylistEntries(
			playlistDetail.entries,
			Math.floor(Math.random() * playlistDetail.entries.length),
			{ restart: true }
		);
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

	/** Re-checks the cache whenever the viewed playlist changes. */
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
		// Persist saved-stream URLs in sessionStorage keyed by playlist id so the
		// indicator survives component re-mounts within the same session.
		const stored = sessionStorage.getItem(`offline-stream:${detail.id}`);
		if (stored) {
			try {
				const { streamUrl, snapshotId } = JSON.parse(stored) as {
					streamUrl: string;
					snapshotId: string;
				};
				// Verify it is actually still in the cache.
				isStreamSaved(offlineStreamUrl(snapshotId)).then((saved) => {
					if (cancelled) return;
					if (saved) {
						offlineSavedStreamUrl = offlineStreamUrl(snapshotId);
						offlineSavedSnapshotId = snapshotId;
					} else {
						sessionStorage.removeItem(`offline-stream:${detail.id}`);
					}
				});
			} catch {
				sessionStorage.removeItem(`offline-stream:${detail.id}`);
			}
		}
		return () => {
			cancelled = true;
		};
	});

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
			sessionStorage.setItem(
				`offline-stream:${playlistDetail.id}`,
				JSON.stringify({
					streamUrl: offlineStreamUrl(manifest.snapshot_id),
					snapshotId: manifest.snapshot_id
				})
			);
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
			sessionStorage.removeItem(`offline-stream:${playlistDetail.id}`);
			offlineSavedStreamUrl = null;
			offlineSavedSnapshotId = null;
			addToast('Offline copy removed', 'info');
		} catch {
			addToast('Remove failed', 'error');
		}
	}
</script>

{#if playlistDetail}
	<div class="detail-panel">
		<button class="back-btn" onclick={deselectPlaylistView}>
			<span class="back-arrow">←</span>
			Playlists
		</button>
		<div class="detail-header">
			<div>
				<h2 class="detail-title">{playlistDetail.title}</h2>
				<span class="detail-subtitle">
					{playlistDetail.entries.length} track{playlistDetail.entries.length !== 1 ? 's' : ''}
				</span>
			</div>
			<div class="detail-actions">
				{#if playlistDetail.entries.length > 0}
					<button
						class="action-btn-primary"
						onclick={playSequential}
					>
						<Icon name="play" size={15} />
						Play
					</button>
					<button class="action-btn-secondary" onclick={playShuffled}>
						<Icon name="shuffle" size={15} />
						Shuffle
					</button>
				{/if}
				{#if offlineSavedStreamUrl}
					<button class="action-btn-offline saved" onclick={onRemoveOffline}>
						Saved ✓ · Remove
					</button>
				{:else}
					<button
						class="action-btn-offline"
						onclick={onSaveForOffline}
						disabled={offlineSaving || playlistDetail.entries.length === 0}
					>
						{#if offlineSaving && offlineProgress && offlineProgress.total}
							Saving… {Math.round((offlineProgress.downloaded / offlineProgress.total) * 100)}%
						{:else if offlineSaving}
							Saving…
						{:else}
							Save offline
						{/if}
					</button>
				{/if}
				<ShareButton
					isShared={playlistDetail.is_shared}
					shareSlug={playlistDetail.share_slug}
					onshare={onPlaylistShareEnable}
					onunshare={onPlaylistShareDisable}
				/>
				<ActionButton icon="pencil" label="Rename" onclick={onPlaylistRename} />
				<ActionButton
					icon="trash"
					label="Delete Playlist"
					destructive
					confirm
					onclick={onPlaylistDelete}
				/>
			</div>
		</div>

		{#if playlistDetail.is_shared && playlistDetail.share_slug}
			<button
				class="share-link"
				onclick={() => {
					const url = `${window.location.origin}/share/playlist/${playlistDetail.share_slug}`;
					navigator.clipboard.writeText(url);
					addToast('Link copied', 'success');
				}}
				title="Click to copy share link"
			>
				{window.location.origin}/share/playlist/{playlistDetail.share_slug}
			</button>
		{/if}

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
									onclick={(e) => {
										e.stopPropagation();
										void onMoveEntry(entry.id, i - 1);
									}}
									title="Move up"
									aria-label={`Move ${entry.song_title} up`}
									><Icon name="chevron-up" size={14} /></button
								>
							{/if}
							{#if i < playlistDetail.entries.length - 1}
								<button
									class="move-btn"
									onclick={(e) => {
										e.stopPropagation();
										void onMoveEntry(entry.id, i + 1);
									}}
									title="Move down"
									aria-label={`Move ${entry.song_title} down`}
									><Icon name="chevron-down" size={14} /></button
								>
							{/if}
						</div>
						<button
							class="remove-btn"
							onclick={(e) => {
								e.stopPropagation();
								void onRemoveEntry(entry.id);
							}}
							title="Remove from playlist"
							aria-label={`Remove ${entry.song_title} from playlist`}
							><Icon name="x" size={14} /></button
						>
					</div>
				</div>
			{/each}
			{#if playlistDetail.entries.length === 0}
				<p class="empty-tab">No tracks in this playlist yet.</p>
			{/if}
		</div>
	</div>
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

	.action-btn-primary,
	.action-btn-secondary {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: var(--btn-padding-pill);
		border-radius: var(--btn-radius-pill);
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
		transition:
			box-shadow 0.2s,
			border-color 0.15s,
			color 0.15s,
			background 0.15s;
	}

	.action-btn-primary {
		border: none;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.action-btn-secondary {
		border: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface) 75%, transparent);
		color: var(--text-muted);
	}

	.action-btn-primary:hover {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

	.action-btn-offline {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: var(--btn-padding-pill);
		border-radius: var(--btn-radius-pill);
		font-family: var(--font-display);
		font-size: var(--btn-font-size-sm);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
		border: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface) 75%, transparent);
		color: var(--text-muted);
		transition:
			box-shadow 0.2s,
			border-color 0.15s,
			color 0.15s,
			background 0.15s;
	}

	.action-btn-offline:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 10%, var(--surface));
	}

	.action-btn-offline:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.action-btn-offline.saved {
		border-color: var(--success);
		color: var(--success);
	}

	.action-btn-offline.saved:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
		background: color-mix(in srgb, var(--score-bad) 8%, var(--surface));
	}

	.action-btn-secondary:hover {
		border-color: var(--accent);
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 10%, var(--surface));
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

	.entry-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
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
		min-width: 28px;
	}

	.move-btn {
		background: color-mix(in srgb, var(--surface) 80%, transparent);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		width: 28px;
		height: 24px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		line-height: 1;
		opacity: 0.7;
		transition:
			opacity 0.15s,
			border-color 0.15s,
			color 0.15s;
	}

	.entry-row:hover .move-btn {
		opacity: 1;
	}

	.move-btn:hover {
		border-color: var(--primary);
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
		color: var(--text-dim);
	}

	.entry-actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
	}

	.remove-btn {
		background: color-mix(in srgb, var(--surface) 80%, transparent);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		width: 30px;
		height: 30px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		padding: 0;
		line-height: 1;
		transition:
			background 0.15s,
			border-color 0.15s,
			color 0.15s;
	}

	.remove-btn:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
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
