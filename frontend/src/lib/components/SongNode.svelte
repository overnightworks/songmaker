<script lang="ts">
	import {
		songList,
		playback,
		playGeneration,
		togglePlayPause,
		isAudioPlaying,
		selectedGenerationId,
		ensureGenerationsLoaded
	} from '$lib/stores/player';
	import { selectedSongId, albumList } from '$lib/stores/player';
	import { selectSong, selectGeneration } from '$lib/stores/navigation';
	import { deleteGeneration, moveSong } from '$lib/api/client';
	import { addToast } from '$lib/stores/toast';
	import type { SongItem, GenerationItem } from '$lib/api/types';

	interface Props {
		song: SongItem;
		expanded: boolean;
		onexpandtoggle: (e: Event) => void;
	}

	let { song, expanded, onexpandtoggle }: Props = $props();

	const MAX_VISIBLE_GENS = 3;

	const activeSongId = $derived($selectedSongId);
	const activeGenId = $derived($selectedGenerationId);
	const pb = $derived($playback);
	const audioPlaying = $derived($isAudioPlaying);
	const albums = $derived($albumList);

	let showAllGens = $state(false);
	let confirmDeleteGenId: string | null = $state(null);
	let movingSong = $state(false);

	interface VersionGroup {
		label: string;
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	function groupByVersion(gens: GenerationItem[]): VersionGroup[] {
		const groups: Record<string, VersionGroup> = {};
		for (const gen of gens) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!groups[key]) {
				groups[key] = {
					label: gen.version_number !== null ? `v${gen.version_number}` : 'Unknown version',
					versionNumber: gen.version_number,
					generations: []
				};
			}
			groups[key].generations.push(gen);
		}
		const result = Object.values(groups);
		result.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
		return result;
	}

	function visibleGroups(): VersionGroup[] {
		const allGroups = groupByVersion(song.generations);
		if (showAllGens) return allGroups;
		let count = 0;
		const result: VersionGroup[] = [];
		for (const group of allGroups) {
			if (count >= MAX_VISIBLE_GENS) break;
			const remaining = MAX_VISIBLE_GENS - count;
			if (group.generations.length <= remaining) {
				result.push(group);
				count += group.generations.length;
			} else {
				result.push({ ...group, generations: group.generations.slice(0, remaining) });
				count = MAX_VISIBLE_GENS;
			}
		}
		return result;
	}

	function isPlaying(): boolean {
		return pb?.songId === song.id;
	}

	function isGenPlaying(gen: GenerationItem): boolean {
		return pb?.generation.id === gen.id;
	}

	function handleGenPlayToggle(e: Event, gen: GenerationItem): void {
		e.stopPropagation();
		if (isGenPlaying(gen)) togglePlayPause();
		else playGeneration(gen, song);
	}

	function handleGenDeleteClick(e: Event, genId: string): void {
		e.stopPropagation();
		confirmDeleteGenId = confirmDeleteGenId === genId ? null : genId;
	}

	async function handleGenDeleteConfirm(e: Event, gen: GenerationItem): Promise<void> {
		e.stopPropagation();
		try {
			await deleteGeneration(gen.id);
			songList.update((songs) =>
				songs.map((s) => ({
					...s,
					generations: s.generations.filter((g) => g.id !== gen.id),
					generation_count: s.generations.filter((g) => g.id !== gen.id).length
				}))
			);
		} catch (err) {
			addToast(err instanceof Error ? err.message : 'Delete failed', 'error');
		}
		confirmDeleteGenId = null;
	}

	async function handleMoveSong(targetAlbumId: string): Promise<void> {
		try {
			const updated = await moveSong(song.id, targetAlbumId);
			songList.update((list) => list.map((s) => (s.id === updated.id ? updated : s)));
			movingSong = false;
			addToast('Song moved', 'success');
		} catch (err) {
			addToast(err instanceof Error ? err.message : 'Move failed', 'error');
		}
	}
</script>

<div
	class="song-group"
	class:active={song.id === activeSongId}
	role="group"
>
	<div
		class="song-item"
		class:active={song.id === activeSongId}
		class:playing={isPlaying()}
		role="treeitem"
		aria-selected={song.id === activeSongId}
	>
		<button
			class="expand-toggle"
			onclick={onexpandtoggle}
			aria-label={expanded ? 'Collapse' : 'Expand'}
		>
			{expanded ? '▾' : '▸'}
		</button>
		<button class="song-name-btn" onclick={() => selectSong(song.id)}>
			<span class="song-name">{song.title}</span>
		</button>
		{#if movingSong}
			<select
				class="move-select"
				onchange={(e) => {
					const target = (e.target as HTMLSelectElement).value;
					if (target) handleMoveSong(target);
				}}
				onclick={(e) => e.stopPropagation()}
			>
				<option value="">Move to...</option>
				{#each albums.filter((a) => a.id !== song.album_id) as a (a.id)}
					<option value={a.id}>{a.title}</option>
				{/each}
			</select>
			<button
				class="move-cancel"
				onclick={(e) => {
					e.stopPropagation();
					movingSong = false;
				}}>✕</button
			>
		{:else}
			<button
				class="move-btn"
				onclick={(e) => {
					e.stopPropagation();
					movingSong = true;
				}}
				title="Move to another album">↷</button
			>
		{/if}
		<span class="song-meta">
			{song.generation_count} gen{song.generation_count !== 1 ? 's' : ''}
		</span>
	</div>

	{#if expanded}
		<div class="gen-list">
			{#each visibleGroups() as vg (vg.label)}
				<div class="version-group">
					<span class="version-label">{vg.label}</span>
					{#each vg.generations as gen (gen.id)}
						<div
							class="gen-row"
							class:playing={isGenPlaying(gen)}
							class:selected={gen.id === activeGenId}
							onclick={() => selectGeneration(gen, song)}
							onkeydown={(e) => e.key === 'Enter' && selectGeneration(gen, song)}
							role="button"
							tabindex="0"
						>
							<button
								class="gen-play-btn"
								onclick={(e) => handleGenPlayToggle(e, gen)}
								aria-label={isGenPlaying(gen) && audioPlaying ? 'Pause' : 'Play'}
							>
								{#if isGenPlaying(gen) && audioPlaying}⏸{:else}▶{/if}
							</button>
							<span class="gen-num">
								{#if gen.is_picked}<span class="picked">★</span>{/if}
								gen{gen.generation_number}
							</span>
							{#if gen.seed}
								<span class="gen-seed">seed:{gen.seed}</span>
							{/if}
							{#if confirmDeleteGenId === gen.id}
								<button
									class="gen-delete-confirm"
									onclick={(e) => handleGenDeleteConfirm(e, gen)}>Delete?</button
								>
							{:else}
								<button
									class="gen-delete-btn"
									onclick={(e) => handleGenDeleteClick(e, gen.id)}
									aria-label="Delete">✕</button
								>
							{/if}
						</div>
					{/each}
				</div>
			{/each}
			{#if song.generations.length === 0 && song.generation_count > 0}
				<span class="gen-empty loading">Loading...</span>
				{void ensureGenerationsLoaded(song.id)}
			{:else if song.generations.length === 0}
				<span class="gen-empty">No generations</span>
			{/if}
			{#if song.generations.length > MAX_VISIBLE_GENS && !showAllGens}
				<button class="show-all-btn" onclick={() => (showAllGens = true)}>
					Show all ({song.generations.length})
				</button>
			{/if}
			{#if showAllGens && song.generations.length > MAX_VISIBLE_GENS}
				<button class="show-all-btn" onclick={() => (showAllGens = false)}>
					Show less
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.song-group {
		border-top: 1px solid #1a1a1a;
	}

	.song-group.active {
		border-left: 3px solid var(--accent);
	}

	.song-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px 6px 24px;
		background: transparent;
		color: var(--text);
		font-size: 12px;
		cursor: pointer;
	}

	.song-item:hover {
		background: var(--surface-hover);
	}

	.song-item.active {
		background: #1a2a1a;
	}

	.song-item.playing {
		background: #1a1a2a;
	}

	.expand-toggle {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		padding: 0 2px;
		flex-shrink: 0;
		width: 16px;
		cursor: pointer;
	}

	.expand-toggle:hover {
		color: var(--text-muted);
	}

	.song-name-btn {
		flex: 1;
		display: flex;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
		padding: 0;
		min-width: 0;
		text-align: left;
	}

	.song-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.move-btn {
		background: none;
		border: none;
		color: transparent;
		font-size: 12px;
		cursor: pointer;
		padding: 0 2px;
		flex-shrink: 0;
	}

	.song-item:hover .move-btn {
		color: var(--text-dim);
	}

	.move-btn:hover {
		color: var(--primary) !important;
	}

	.move-select {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text);
		font-size: 10px;
		padding: 1px 4px;
		border-radius: 3px;
		max-width: 100px;
	}

	.move-cancel {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 9px;
		cursor: pointer;
		padding: 0 2px;
	}

	.move-cancel:hover {
		color: var(--text-muted);
	}

	.song-meta {
		font-size: 10px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.gen-list {
		display: flex;
		flex-direction: column;
		padding: 0 0 4px 40px;
	}

	.version-group {
		display: flex;
		flex-direction: column;
	}

	.version-label {
		font-size: 9px;
		color: var(--text-dim);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 4px 12px 2px;
	}

	.gen-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 3px 12px;
		color: var(--text);
		font-size: 11px;
		cursor: pointer;
		border-radius: 3px;
	}

	.gen-row:hover {
		background: var(--surface-hover);
	}

	.gen-row.playing {
		background: #1a1a2a;
	}

	.gen-row.selected {
		background: rgba(160, 32, 240, 0.08);
		border-left: 2px solid var(--accent);
	}

	.gen-play-btn {
		background: none;
		border: none;
		font-size: 10px;
		cursor: pointer;
		color: var(--text-muted);
		padding: 0 2px;
		flex-shrink: 0;
	}

	.gen-play-btn:hover {
		color: var(--primary);
	}

	.gen-num {
		font-family: var(--font-display);
		color: var(--text-muted);
		min-width: 32px;
	}

	.picked {
		color: var(--score-ok);
	}

	.gen-seed {
		font-size: 8px;
		color: var(--text-dim);
		margin-left: auto;
	}

	.gen-delete-btn {
		background: none;
		border: none;
		color: transparent;
		font-size: 9px;
		cursor: pointer;
		padding: 0 3px;
		flex-shrink: 0;
	}

	.gen-row:hover .gen-delete-btn {
		color: var(--text-dim);
	}

	.gen-delete-btn:hover {
		color: var(--score-bad) !important;
	}

	.gen-delete-confirm {
		background: none;
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
		font-size: 9px;
		padding: 1px 6px;
		border-radius: 3px;
		cursor: pointer;
		flex-shrink: 0;
	}

	.gen-delete-confirm:hover {
		background: var(--score-bad);
		color: #fff;
	}

	.gen-empty {
		font-size: 10px;
		color: var(--text-dim);
		font-style: italic;
		padding: 4px 12px;
	}

	.gen-empty.loading {
		animation: pulse 1.5s ease-in-out infinite;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 0.4;
		}
		50% {
			opacity: 1;
		}
	}

	.show-all-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		padding: 3px 12px;
		text-align: left;
		cursor: pointer;
	}

	.show-all-btn:hover {
		color: var(--primary);
	}
</style>
