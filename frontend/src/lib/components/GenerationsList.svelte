<script lang="ts">
	import type { SongItem, GenerationItem } from '$lib/api/types';
	import {
		EXPIRY_WARN_DAYS,
		LIBRARY_RETRY_LABEL,
		NOW_PLAYING_TAKE_PREFIX,
		SONG_SURFACE_RECIPE,
		TAKE_AGAIN_LABEL,
		TAKE_AUDIO_COVER_LABEL,
		TAKE_COPY_LINK_LABEL,
		TAKE_DELETE_LABEL,
		TAKE_KEEP_LABEL,
		TAKE_OVERFLOW_LABEL,
		TAKE_PICK_LABEL,
		TAKE_PLAYLIST_LABEL,
		TAKE_REMASTER_LABEL,
		TAKE_REPAINT_LABEL,
		TAKE_RESTORE_LABEL,
		TAKE_SHARE_LABEL,
		TAKE_UNSHARE_LABEL,
		TAKES_EMPTY,
		TAKES_ERROR,
		TAKES_LOADING
	} from '$lib/constants';
	import {
		playGeneration,
		playAlbumFromGeneration,
		playLibraryFromGeneration,
		queueContext,
		selectedAlbumId,
		removeGenerationFromSong,
		replaceSongInList
	} from '$lib/stores/player';
	import { clearGenerationSelection, persistLibraryHistory } from '$lib/stores/navigation';
	import { queuePlaybackMode, shouldUseQueueStream } from '$lib/stores/playbackSettings';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { scoreColor } from '$lib/utils/scores';
	import { getGenerationActions } from '$lib/contexts/generation-actions';
	import {
		selectionMode,
		selectedIds,
		toggleSelection,
		selectAllUnkept,
		clearSelection,
		selectionCount
	} from '$lib/stores/selection';
	import { addToast } from '$lib/stores/toast';
	import {
		bulkDeleteGenerations,
		fetchSong,
		remasterGeneration,
		unarchiveGeneration
	} from '$lib/api/client';
	import AgeStamp from './AgeStamp.svelte';
	import Icon from './Icon.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	interface Props {
		song: SongItem;
		selectedId?: string | null;
		loadStatus?: 'loading' | 'ready' | 'error';
		loadError?: string | null;
		onselect: (gen: GenerationItem) => void;
		onagain?: (gen: GenerationItem) => void;
		onrepaint?: (gen: GenerationItem) => void;
		onaudiocover?: (gen: GenerationItem) => void;
		onretry?: () => void;
	}

	let {
		song,
		selectedId = null,
		loadStatus = 'ready',
		loadError = null,
		onselect,
		onagain,
		onrepaint,
		onaudiocover,
		onretry
	}: Props = $props();

	const actions = getGenerationActions();

	const playingGenId = $derived(audioPlayer.current?.generation.id ?? null);
	const buffering = $derived(
		audioPlayer.status === 'loading' || audioPlayer.status === 'buffering'
	);

	let overflowId = $state<string | null>(null);
	let playlistFor = $state<string | null>(null);
	let deleteFor = $state<GenerationItem | null>(null);
	let remasteringId = $state<string | null>(null);

	interface VersionGroup {
		label: string;
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	const groups = $derived.by((): VersionGroup[] => {
		const map: Record<string, VersionGroup> = {};
		for (const gen of song.generations) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!map[key]) {
				map[key] = {
					label:
						gen.version_number !== null
							? `${SONG_SURFACE_RECIPE} ${gen.version_number}`
							: 'Unknown recipe',
					versionNumber: gen.version_number,
					generations: []
				};
			}
			map[key].generations.push(gen);
		}
		const result = Object.values(map);
		result.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
		return result;
	});

	function daysUntilExpiry(gen: GenerationItem): number | null {
		if (gen.is_picked || gen.is_kept || !gen.expires_at) return null;
		const ms = new Date(gen.expires_at).getTime() - Date.now();
		return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
	}

	function isGenPlaying(gen: GenerationItem): boolean {
		return playingGenId === gen.id;
	}

	function isGenLoading(gen: GenerationItem): boolean {
		return isGenPlaying(gen) && buffering;
	}

	function playOrToggle(gen: GenerationItem): void {
		if (isGenPlaying(gen) && audioPlayer.status === 'playing') {
			audioPlayer.toggle();
			return;
		}
		const albumId = $selectedAlbumId;
		if (shouldUseQueueStream($queuePlaybackMode)) {
			if (albumId) {
				void playAlbumFromGeneration(albumId, song, gen);
				return;
			}
			void playLibraryFromGeneration(gen);
			return;
		}
		queueContext.set(albumId ? { type: 'album', albumId } : { type: 'library' });
		playGeneration(gen, song, { restart: true });
	}

	function handleCardClick(gen: GenerationItem, e: MouseEvent): void {
		if (e.ctrlKey || e.metaKey) {
			toggleSelection(gen.id);
			return;
		}
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		onselect(gen);
		playOrToggle(gen);
	}

	function handleCardKeydown(gen: GenerationItem, e: KeyboardEvent): void {
		if (e.target !== e.currentTarget) return;
		if (e.key !== 'Enter' && e.key !== ' ') return;
		e.preventDefault();
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		onselect(gen);
		playOrToggle(gen);
	}

	function toggleOverflow(genId: string, e: MouseEvent): void {
		e.stopPropagation();
		overflowId = overflowId === genId ? null : genId;
		playlistFor = null;
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

	async function handleBulkDelete(): Promise<void> {
		const ids = [...$selectedIds];
		if (ids.length === 0) return;
		const inspectedTakeId = selectedId;
		try {
			await bulkDeleteGenerations(ids);
			for (const id of ids) {
				removeGenerationFromSong(song.id, id);
			}
			if (inspectedTakeId !== null && ids.includes(inspectedTakeId)) {
				clearGenerationSelection();
				persistLibraryHistory();
			}
			clearSelection();
			addToast(`Deleted ${ids.length} take${ids.length !== 1 ? 's' : ''}`, 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Bulk delete failed', 'error');
		}
	}

	async function copyShareUrl(gen: GenerationItem): Promise<void> {
		if (!gen.share_slug) return;
		await navigator.clipboard.writeText(`${window.location.origin}/share/gen/${gen.share_slug}`);
		addToast('Link copied', 'success');
	}

	async function onShare(gen: GenerationItem): Promise<void> {
		try {
			const result = await actions.share(gen.id);
			await navigator.clipboard.writeText(result.share_url);
			addToast('Link copied', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Share failed', 'error');
		}
	}

	async function onUnshare(gen: GenerationItem): Promise<void> {
		try {
			await actions.unshare(gen.id);
			addToast('Sharing disabled', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Unshare failed', 'error');
		}
	}

	async function onRemaster(gen: GenerationItem): Promise<void> {
		if (remasteringId) return;
		remasteringId = gen.id;
		try {
			await remasterGeneration(gen.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast('Remastered', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Remaster failed', 'error');
		} finally {
			remasteringId = null;
		}
	}

	async function onRestore(gen: GenerationItem): Promise<void> {
		try {
			await unarchiveGeneration(gen.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast('Take restored', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Restore failed', 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistFor) return;
		try {
			await actions.addToPlaylist(playlistId, playlistFor);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistFor = null;
		}
	}
</script>

{#if loadStatus === 'error' && song.generations.length === 0}
	<div class="empty" role="alert">
		<p>{loadError || TAKES_ERROR}</p>
		{#if onretry}
			<button type="button" class="retry-btn" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
		{/if}
	</div>
{:else if loadStatus === 'loading' && song.generations.length === 0}
	<div class="empty" role="status">{TAKES_LOADING}</div>
{:else if song.generations.length === 0}
	<div class="empty">{TAKES_EMPTY}</div>
{:else}
	<div class="gen-list">
		{#if loadStatus === 'error'}
			<div class="load-error" role="alert">
				<span>{loadError || TAKES_ERROR}</span>
				{#if onretry}
					<button type="button" class="retry-btn" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
				{/if}
			</div>
		{/if}
		{#each groups as group (group.label)}
			<div class="version-section">
				<div class="version-header">{group.label}</div>
				{#each group.generations as gen (gen.id)}
					<div
						class="gen-card"
						class:playing={isGenPlaying(gen)}
						class:buffering={isGenLoading(gen)}
						class:selected={$selectedIds.has(gen.id)}
						class:inspected={selectedId === gen.id}
						onclick={(e) => handleCardClick(gen, e)}
						onkeydown={(e) => handleCardKeydown(gen, e)}
						role="button"
						tabindex="0"
						aria-pressed={selectedId === gen.id}
					>
						{#if $selectionMode}
							<span class="selection-checkbox">
								<Icon name={$selectedIds.has(gen.id) ? 'check-square' : 'square'} size={16} />
							</span>
						{/if}

						<div class="gen-info">
							<span class="gen-name">
								{#if gen.is_picked}<span class="picked-star">★</span>{/if}
								{`${NOW_PLAYING_TAKE_PREFIX} ${gen.generation_number}`}
							</span>
							<AgeStamp createdAt={gen.created_at} />
							{#if gen.seed}
								<span class="gen-seed">seed:{gen.seed}</span>
							{/if}
							{#if gen.model_mode}
								<span class="model-badge">{gen.model_mode}</span>
							{/if}
							{#if gen.is_archived}
								<span class="expiry-badge archived" title="Archived — will be hard-deleted">
									archived
								</span>
							{:else}
								{@const daysLeft = daysUntilExpiry(gen)}
								{#if daysLeft !== null && daysLeft <= EXPIRY_WARN_DAYS}
									<span
										class="expiry-badge warn"
										title="Expires in {daysLeft} day{daysLeft === 1
											? ''
											: 's'} — pick or keep to preserve"
									>
										⏳ {daysLeft}d
									</span>
								{/if}
							{/if}
						</div>

						<div class="gen-actions">
							{#if gen.scores?.user_rating !== undefined}
								<span class="score-badge {scoreColor('user_rating', gen.scores.user_rating)}">
									{gen.scores.user_rating.toFixed(0)}
								</span>
							{/if}
							{#if gen.scores?.audiobox_quality !== undefined}
								<span
									class="score-mini {scoreColor('audiobox_quality', gen.scores.audiobox_quality)}"
								>
									Q:{gen.scores.audiobox_quality.toFixed(1)}
								</span>
							{/if}
							{#if gen.scores?.audiobox_enjoyment !== undefined}
								<span
									class="score-mini {scoreColor(
										'audiobox_enjoyment',
										gen.scores.audiobox_enjoyment
									)}"
								>
									E:{gen.scores.audiobox_enjoyment.toFixed(1)}
								</span>
							{/if}
							<button
								type="button"
								class="pick-btn"
								class:picked={gen.is_picked}
								data-hitbox="frequent"
								onclick={(e) => {
									e.stopPropagation();
									actions.pick(gen.id, !gen.is_picked);
								}}
								aria-pressed={gen.is_picked}
								aria-label={gen.is_picked ? 'Unpick' : TAKE_PICK_LABEL}
							>
								{TAKE_PICK_LABEL}
							</button>
							<button
								type="button"
								class="keep-btn"
								class:kept={gen.is_kept}
								data-hitbox="frequent"
								onclick={(e) => {
									e.stopPropagation();
									actions.keep(gen.id, !gen.is_kept);
								}}
								aria-pressed={gen.is_kept}
								aria-label={gen.is_kept ? 'Unkeep' : TAKE_KEEP_LABEL}
							>
								{TAKE_KEEP_LABEL}
							</button>
							{#if !$selectionMode}
								<button
									type="button"
									class="continue-btn"
									onclick={(e) => {
										e.stopPropagation();
										onagain?.(gen);
									}}>{TAKE_AGAIN_LABEL}</button
								>
								<button
									type="button"
									class="continue-btn"
									onclick={(e) => {
										e.stopPropagation();
										onrepaint?.(gen);
									}}>{TAKE_REPAINT_LABEL}</button
								>
								<button
									type="button"
									class="continue-btn"
									onclick={(e) => {
										e.stopPropagation();
										onaudiocover?.(gen);
									}}>{TAKE_AUDIO_COVER_LABEL}</button
								>
								<div class="overflow-anchor">
									<button
										type="button"
										class="overflow-btn"
										aria-haspopup="menu"
										aria-expanded={overflowId === gen.id}
										aria-label={TAKE_OVERFLOW_LABEL}
										onclick={(e) => toggleOverflow(gen.id, e)}
									>
										<Icon name="more-horizontal" size={16} />
									</button>
									{#if overflowId === gen.id}
										<div
											class="overflow-menu"
											role="menu"
											data-escape-overlay="true"
											tabindex="-1"
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => e.stopPropagation()}
										>
											{#if gen.is_shared}
												<button
													type="button"
													role="menuitem"
													class="overflow-item"
													onclick={() => {
														overflowId = null;
														void copyShareUrl(gen);
													}}>{TAKE_COPY_LINK_LABEL}</button
												>
												<button
													type="button"
													role="menuitem"
													class="overflow-item"
													onclick={() => {
														overflowId = null;
														void onUnshare(gen);
													}}>{TAKE_UNSHARE_LABEL}</button
												>
											{:else}
												<button
													type="button"
													role="menuitem"
													class="overflow-item"
													onclick={() => {
														overflowId = null;
														void onShare(gen);
													}}>{TAKE_SHARE_LABEL}</button
												>
											{/if}
											<button
												type="button"
												role="menuitem"
												class="overflow-item"
												onclick={() => {
													overflowId = null;
													playlistFor = gen.id;
												}}>{TAKE_PLAYLIST_LABEL}</button
											>
											<button
												type="button"
												role="menuitem"
												class="overflow-item"
												disabled={remasteringId === gen.id}
												onclick={() => {
													overflowId = null;
													void onRemaster(gen);
												}}>{TAKE_REMASTER_LABEL}</button
											>
											{#if gen.is_archived}
												<button
													type="button"
													role="menuitem"
													class="overflow-item"
													onclick={() => {
														overflowId = null;
														void onRestore(gen);
													}}>{TAKE_RESTORE_LABEL}</button
												>
											{/if}
											<button
												type="button"
												role="menuitem"
												class="overflow-item destructive"
												onclick={() => {
													overflowId = null;
													deleteFor = gen;
												}}>{TAKE_DELETE_LABEL}</button
											>
										</div>
									{/if}
									{#if playlistFor === gen.id}
										<PlaylistPicker
											onselect={onAddToPlaylist}
											onclose={() => (playlistFor = null)}
										/>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/each}

		{#if $selectionMode}
			<div class="selection-toolbar">
				<button type="button" class="toolbar-btn" onclick={() => selectAllUnkept(song.generations)}>
					Select All Unkept
				</button>
				<span class="toolbar-count">{$selectionCount} selected</span>
				<button type="button" class="toolbar-btn destructive" onclick={handleBulkDelete}>
					Delete Selected
				</button>
				<button type="button" class="toolbar-btn" onclick={clearSelection}> Cancel </button>
			</div>
		{/if}
	</div>
{/if}

{#if deleteFor}
	<ConfirmDeleteDialog
		title={`Delete ${NOW_PLAYING_TAKE_PREFIX} #${deleteFor.generation_number}?`}
		items={['Audio files will be permanently deleted']}
		confirmLabel="Delete Take"
		onconfirm={() => {
			const id = deleteFor?.id;
			deleteFor = null;
			if (id) actions.del(id);
		}}
		oncancel={() => (deleteFor = null)}
	/>
{/if}

<style>
	.gen-list {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.version-section {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.version-header {
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0.3rem 0;
	}

	.gen-card {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.7rem;
		padding: 0.7rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font: inherit;
		width: 100%;
	}

	.gen-card:hover {
		border-color: rgba(160, 32, 240, 0.3);
		background: var(--surface-hover);
	}

	.gen-card.playing {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.gen-card.buffering {
		border-color: var(--accent);
		animation: buffer-pulse 1.5s ease-in-out infinite;
	}

	.gen-card.selected,
	.gen-card.inspected {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.05);
	}

	@keyframes buffer-pulse {
		0%,
		100% {
			border-color: rgba(160, 32, 240, 0.2);
			box-shadow: 0 0 0 rgba(160, 32, 240, 0);
		}
		50% {
			border-color: var(--accent);
			box-shadow: 0 0 12px rgba(160, 32, 240, 0.15);
		}
	}

	.gen-info {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.gen-name {
		font-family: var(--font-display);
		font-size: 0.93rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.picked-star {
		color: var(--accent);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.gen-seed {
		font-size: 0.7rem;
		color: var(--text-subtle);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.model-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.3rem;
		border-radius: 3px;
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.expiry-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
	}

	.expiry-badge.warn {
		background: rgba(220, 140, 20, 0.15);
		border: 1px solid rgba(220, 140, 20, 0.5);
		color: #f0a030;
	}

	.expiry-badge.archived {
		background: rgba(200, 60, 60, 0.15);
		border: 1px solid rgba(200, 60, 60, 0.5);
		color: #e07070;
		text-transform: uppercase;
	}

	.gen-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem;
		flex-shrink: 0;
	}

	.score-badge {
		font-family: var(--font-display);
		font-size: 1.07rem;
		min-width: 28px;
		text-align: center;
	}

	.score-badge.good {
		color: var(--score-good);
	}

	.score-badge.ok {
		color: var(--score-ok);
	}

	.score-badge.bad {
		color: var(--score-bad);
	}

	.score-mini {
		font-size: 0.7rem;
		font-family: var(--font-display);
	}

	.score-mini.good {
		color: var(--score-good);
	}

	.score-mini.ok {
		color: var(--score-ok);
	}

	.score-mini.bad {
		color: var(--score-bad);
	}

	.pick-btn,
	.keep-btn,
	.continue-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		padding: 0.15rem 0.45rem;
		font-size: 0.7rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		color: var(--text-muted);
		cursor: pointer;
		line-height: 1.2;
	}

	.pick-btn:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.pick-btn.picked {
		color: var(--accent);
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.keep-btn:hover {
		color: var(--keep);
		border-color: var(--keep);
	}

	.keep-btn.kept {
		color: var(--keep);
		border-color: var(--keep);
		background: color-mix(in srgb, var(--keep) 12%, transparent);
	}

	.continue-btn:hover {
		color: var(--primary);
		border-color: var(--primary);
	}

	.overflow-anchor {
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

	.overflow-menu {
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

	.overflow-item {
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

	.overflow-item:hover:not(:disabled) {
		background: var(--surface-hover);
		color: var(--text);
	}

	.overflow-item.destructive:hover:not(:disabled) {
		color: var(--score-bad);
	}

	.overflow-item:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.selection-checkbox {
		display: flex;
		align-items: center;
		color: var(--text-decoration);
		flex-shrink: 0;
	}

	.gen-card.selected .selection-checkbox {
		color: var(--accent);
	}

	.selection-toolbar {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.7rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--accent);
		border-radius: var(--card-radius);
		position: sticky;
		bottom: 0;
	}

	.toolbar-btn {
		padding: 0.3rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.toolbar-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.toolbar-btn.destructive {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.toolbar-btn.destructive:hover {
		background: rgba(255, 68, 68, 0.1);
	}

	.toolbar-count {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.empty,
	.load-error {
		padding: 2.7rem 1.3rem;
		text-align: center;
		color: var(--text-subtle);
		font-style: italic;
		font-size: 0.87rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.7rem;
	}

	.load-error {
		padding: 0.6rem 0.8rem;
		font-style: normal;
		color: var(--score-bad);
		flex-direction: row;
		justify-content: space-between;
	}

	.retry-btn {
		padding: 0.3rem 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
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
		.gen-card {
			padding: 0.55rem 0.7rem;
			gap: 0.55rem;
		}

		.score-mini {
			display: none;
		}

		.gen-name {
			font-size: 0.93rem;
		}

		.gen-seed {
			font-size: 0.75rem;
		}

		.gen-actions {
			flex-basis: 100%;
			justify-content: flex-end;
		}
	}
</style>
