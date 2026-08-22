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
	import { ALBUM_ART_EMPTY_INITIALS, ALBUM_ART_INITIAL_COUNT } from '$lib/constants';
	import ActionButton from './ActionButton.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import Icon from './Icon.svelte';
	import ShareButton from './ShareButton.svelte';

	const playlistDetail = $derived($selectedPlaylistDetail);
	let reorderBusy = $state(false);
	const initials = $derived(
		playlistDetail ? playlistTitleInitials(playlistDetail.title) : ALBUM_ART_EMPTY_INITIALS
	);

	function playlistTitleInitials(title: string): string {
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
</script>

{#if playlistDetail}
	<div class="detail-panel">
		<div class="detail-header">
			<div class="detail-identity">
				<div class="cover-hero">
					<span class="cover-fallback cover-initials" aria-hidden="true">{initials}</span>
				</div>
				<div class="detail-titles">
					<h2 class="detail-title">
						<EditableTitle
							value={playlistDetail.title}
							onsave={onPlaylistRename}
							ariaLabel="Playlist title"
						/>
					</h2>
					<span class="detail-subtitle">
						{playlistDetail.entries.length} track{playlistDetail.entries.length !== 1 ? 's' : ''}
					</span>
				</div>
			</div>
			<div class="detail-actions">
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

	.cover-fallback {
		width: 100%;
		height: 100%;
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
