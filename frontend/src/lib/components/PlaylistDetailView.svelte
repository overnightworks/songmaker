<script lang="ts">
	import { sharePlaylist, unsharePlaylist } from '$lib/api/client';
	import { playPlaylistEntries } from '$lib/stores/player';
	import {
		selectedPlaylistDetail,
		deletePlaylist,
		renamePlaylist,
		removePlaylistEntry,
		movePlaylistEntry
	} from '$lib/stores/playlists';
	import { deselectPlaylistView } from '$lib/stores/navigation';
	import { addToast } from '$lib/stores/toast';
	import OverflowMenu from './OverflowMenu.svelte';
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
						onclick={() => playPlaylistEntries(playlistDetail.entries)}
					>
						Play
					</button>
				{/if}
				<ShareButton
					isShared={playlistDetail.is_shared}
					shareSlug={playlistDetail.share_slug}
					onshare={onPlaylistShareEnable}
					onunshare={onPlaylistShareDisable}
				/>
				<OverflowMenu
					items={[
						{ label: 'Rename', onclick: onPlaylistRename },
						{
							label: 'Delete Playlist',
							confirmLabel: 'Confirm Delete',
							destructive: true,
							onclick: onPlaylistDelete
						}
					]}
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
				<div class="entry-row">
					<div class="entry-controls">
						{#if i > 0}
							<button class="move-btn" onclick={() => onMoveEntry(entry.id, i - 1)} title="Move up"
								>↑</button
							>
						{/if}
						{#if i < playlistDetail.entries.length - 1}
							<button
								class="move-btn"
								onclick={() => onMoveEntry(entry.id, i + 1)}
								title="Move down">↓</button
							>
						{/if}
					</div>
					<div class="entry-info">
						<span class="entry-title">{entry.song_title}</span>
						<span class="entry-meta">
							{entry.artist} · Gen #{entry.generation_number}
						</span>
					</div>
					<button
						class="remove-btn"
						onclick={() => onRemoveEntry(entry.id)}
						title="Remove from playlist">×</button
					>
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
		padding: 16px 20px calc(var(--player-height) + 16px);
		display: flex;
		flex-direction: column;
		gap: 12px;
		flex: 1;
		max-width: 1000px;
		width: 100%;
		min-width: 0;
		min-height: 0;
		margin: 0 auto;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.detail-title {
		font-family: var(--font-display);
		font-size: 22px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.detail-subtitle {
		font-size: 12px;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 8px;
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
		gap: 6px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 11px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 8px 16px;
		cursor: pointer;
		border-bottom: 1px solid var(--border);
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 14px;
	}

	.entry-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.entry-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.entry-controls {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex-shrink: 0;
	}

	.move-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		font-size: 10px;
		width: 18px;
		height: 16px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		line-height: 1;
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
	}

	.entry-meta {
		font-size: 11px;
		color: var(--text-dim);
	}

	.remove-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		font-size: 14px;
		width: 22px;
		height: 22px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		padding: 0;
		line-height: 1;
	}

	.remove-btn:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.empty-tab {
		color: var(--text-dim);
		font-size: 13px;
		font-style: italic;
		padding: 12px 0;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 8px;
		}

		.detail-actions {
			flex-wrap: wrap;
		}

		.detail-panel {
			padding: 12px 12px calc(var(--player-height) + 12px);
		}

		.detail-title {
			font-size: 18px;
		}
	}
</style>
