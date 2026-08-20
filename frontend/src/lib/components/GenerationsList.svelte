<script lang="ts">
	import type { SongItem, GenerationItem } from '$lib/api/types';
	import { EXPIRY_WARN_DAYS } from '$lib/constants';
	import {
		playGeneration,
		playAlbumFromGeneration,
		playLibraryFromGeneration,
		queueContext,
		selectedAlbumId,
		removeGenerationFromSong
	} from '$lib/stores/player';
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
	import { bulkDeleteGenerations } from '$lib/api/client';
	import AgeStamp from './AgeStamp.svelte';
	import Icon from './Icon.svelte';

	interface Props {
		song: SongItem;
		onselect: (gen: GenerationItem) => void;
	}

	let { song, onselect }: Props = $props();

	const actions = getGenerationActions();

	const playingGenId = $derived(audioPlayer.current?.generation.id ?? null);
	const audioPlaying = $derived(audioPlayer.status === 'playing');
	const buffering = $derived(
		audioPlayer.status === 'loading' || audioPlayer.status === 'buffering'
	);

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
					label: gen.version_number !== null ? `Version ${gen.version_number}` : 'Unknown version',
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
		if (isGenPlaying(gen) && audioPlaying) {
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

	function handlePlay(e: Event, gen: GenerationItem): void {
		e.stopPropagation();
		playOrToggle(gen);
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

	async function handleBulkDelete(): Promise<void> {
		const ids = [...$selectedIds];
		if (ids.length === 0) return;
		try {
			await bulkDeleteGenerations(ids);
			for (const id of ids) {
				removeGenerationFromSong(song.id, id);
			}
			clearSelection();
			addToast(`Deleted ${ids.length} generation${ids.length !== 1 ? 's' : ''}`, 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Bulk delete failed', 'error');
		}
	}
</script>

{#if song.generations.length === 0}
	<div class="empty">No generations yet — hit Generate to create some</div>
{:else}
	<div class="gen-list">
		{#each groups as group (group.label)}
			<div class="version-section">
				<div class="version-header">{group.label}</div>
				{#each group.generations as gen (gen.id)}
					<div
						class="gen-card"
						class:playing={isGenPlaying(gen)}
						class:buffering={isGenLoading(gen)}
						class:selected={$selectedIds.has(gen.id)}
						onclick={(e) => handleCardClick(gen, e)}
						onkeydown={(e) => handleCardKeydown(gen, e)}
						role="button"
						tabindex="0"
					>
						{#if $selectionMode}
							<span class="selection-checkbox">
								<Icon name={$selectedIds.has(gen.id) ? 'check-square' : 'square'} size={16} />
							</span>
						{/if}

						<button
							class="play-btn"
							class:loading={isGenLoading(gen)}
							onclick={(e) => handlePlay(e, gen)}
							aria-label={isGenPlaying(gen) && audioPlaying
								? 'Pause'
								: isGenLoading(gen)
									? 'Loading'
									: 'Play'}
						>
							{#if isGenLoading(gen)}<span class="spinner"
								></span>{:else if isGenPlaying(gen) && audioPlaying}⏸{:else}▶{/if}
						</button>

						<div class="gen-info">
							<span class="gen-name">
								{#if gen.is_picked}<span class="picked-star">★</span>{/if}
								gen{gen.generation_number}
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
								class="pick-btn"
								class:picked={gen.is_picked}
								onclick={(e) => {
									e.stopPropagation();
									actions.pick(gen.id, !gen.is_picked);
								}}
								aria-label={gen.is_picked ? 'Unpick' : 'Pick for album'}
							>
								{gen.is_picked ? '★' : '☆'}
							</button>
							<button
								class="keep-btn"
								class:kept={gen.is_kept}
								onclick={(e) => {
									e.stopPropagation();
									actions.keep(gen.id, !gen.is_kept);
								}}
								aria-label={gen.is_kept ? 'Unkeep' : 'Keep'}
							>
								{gen.is_kept ? '♥' : '♡'}
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/each}

		{#if $selectionMode}
			<div class="selection-toolbar">
				<button class="toolbar-btn" onclick={() => selectAllUnkept(song.generations)}>
					Select All Unkept
				</button>
				<span class="toolbar-count">{$selectionCount} selected</span>
				<button class="toolbar-btn destructive" onclick={handleBulkDelete}>
					Delete Selected
				</button>
				<button class="toolbar-btn" onclick={clearSelection}> Cancel </button>
			</div>
		{/if}
	</div>
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

	.gen-card.selected {
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

	.play-btn.loading {
		border-color: var(--accent);
		cursor: wait;
	}

	.spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
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

	.play-btn {
		width: 2.4rem;
		height: 2.4rem;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		font-size: 0.93rem;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.play-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.gen-card.playing .play-btn {
		border-color: var(--accent);
		color: var(--accent);
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

	.pick-btn {
		background: none;
		border: none;
		font-size: 1.07rem;
		cursor: pointer;
		color: var(--text-decoration);
		padding: 2px;
	}

	.pick-btn:hover {
		color: var(--accent);
	}

	.pick-btn.picked {
		color: var(--accent);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.keep-btn {
		background: none;
		border: none;
		font-size: 1.07rem;
		cursor: pointer;
		color: var(--text-decoration);
		padding: 2px;
	}

	.keep-btn:hover {
		color: var(--keep);
	}

	.keep-btn.kept {
		color: var(--keep);
		text-shadow: 0 0 6px color-mix(in srgb, var(--keep) 40%, transparent);
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

	.empty {
		padding: 2.7rem 1.3rem;
		text-align: center;
		color: var(--text-subtle);
		font-style: italic;
		font-size: 0.87rem;
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

		.play-btn {
			width: 2.7rem;
			height: 2.7rem;
		}
	}
</style>
