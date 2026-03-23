<script lang="ts">
	import {
		filteredSongs,
		selectedSongId,
		selectSong,
		songList,
		playback,
		playGeneration,
		togglePlayPause,
		isAudioPlaying,
		expandedSongIds,
		toggleSongExpanded,
		selectedGenerationId,
		selectGenerationInSidebar
	} from '$lib/stores/player';
	import { deleteGeneration } from '$lib/api/client';
	import {
		sortKey,
		searchQuery,
		activeFilters,
		SORT_OPTIONS,
		METRICS,
		getSortMetric,
		addFilter,
		removeFilter,
		updateFilterMin,
		updateFilterSelect,
		applyFilters
	} from '$lib/stores/filter';
	import type { SongItem, GenerationItem } from '$lib/api/types';

	const MAX_VISIBLE_GENS = 3;

	const songs = $derived($filteredSongs);
	const activeSongId = $derived($selectedSongId);
	const activeGenId = $derived($selectedGenerationId);
	const pb = $derived($playback);
	const audioPlaying = $derived($isAudioPlaying);
	const expanded = $derived($expandedSongIds);
	const currentSortKey = $derived($sortKey);
	const search = $derived($searchQuery);
	const filters = $derived($activeFilters);
	const sortMetric = $derived(getSortMetric(currentSortKey));

	let showFilterMenu = $state(false);
	let showAllGens: Record<string, boolean> = $state({});

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

	function visibleGroups(song: SongItem): VersionGroup[] {
		const allGroups = groupByVersion(song.generations);
		if (showAllGens[song.id]) return allGroups;
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

	const availableMetrics = $derived(
		METRICS.filter((m) => !filters.some((f) => f.metric.key === m.key))
	);

	const availableKeys = $derived.by(() => {
		const seen: Record<string, boolean> = {};
		for (const s of songs) {
			if (s.key) seen[s.key] = true;
		}
		return Object.keys(seen).sort();
	});

	const displaySongs = $derived.by(() => {
		let result = [...songs];

		if (search) {
			const q = search.toLowerCase();
			result = result.filter((s) => s.title.toLowerCase().includes(q));
		}

		result = applyFilters(result, filters);

		if (currentSortKey === 'name') {
			result.sort((a, b) => a.title.localeCompare(b.title));
		} else {
			result.sort((a, b) => {
				const va = sortMetric.getValue(a);
				const vb = sortMetric.getValue(b);
				const na = typeof va === 'number' ? va : -1;
				const nb = typeof vb === 'number' ? vb : -1;
				return nb - na;
			});
		}

		return result;
	});

	function isPlaying(song: SongItem): boolean {
		return pb?.songId === song.id;
	}

	function isGenPlaying(gen: GenerationItem): boolean {
		return pb?.generation.id === gen.id;
	}

	function badgeValue(song: SongItem): string {
		const val = sortMetric.getValue(song);
		if (typeof val !== 'number') return '';
		return sortMetric.max <= 10 ? String(val) : val.toFixed(1);
	}

	function handleSongClick(song: SongItem): void {
		selectSong(song.id);
		if (!expanded.has(song.id)) {
			toggleSongExpanded(song.id);
		}
	}

	function handleExpandToggle(e: Event, songId: string): void {
		e.stopPropagation();
		toggleSongExpanded(songId);
	}

	function handleGenPlayToggle(e: Event, gen: GenerationItem, song: SongItem): void {
		e.stopPropagation();
		if (isGenPlaying(gen)) {
			togglePlayPause();
		} else {
			playGeneration(gen, song);
		}
	}

	function handleGenSelect(gen: GenerationItem, song: SongItem): void {
		selectGenerationInSidebar(gen, song);
	}

	let confirmDeleteGenId: string | null = $state(null);

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
		} catch {
			// silently fail
		}
		confirmDeleteGenId = null;
	}
</script>

<div class="controls">
	<input
		class="search"
		type="text"
		placeholder="Search..."
		value={search}
		oninput={(e: Event) => searchQuery.set((e.target as HTMLInputElement).value)}
		aria-label="Search songs"
	/>

	<select
		class="sort-select"
		value={currentSortKey}
		onchange={(e: Event) => sortKey.set((e.target as HTMLSelectElement).value)}
		aria-label="Sort by"
	>
		<option value="name">Sort: Name</option>
		{#each SORT_OPTIONS as opt (opt.key)}
			<option value={opt.key}>Sort: {opt.label}</option>
		{/each}
	</select>

	<div class="filter-chips">
		{#each filters as f (f.metric.key)}
			<div class="chip">
				<span class="chip-label">{f.metric.label}</span>
				{#if f.metric.type === 'select'}
					<select
						class="chip-select"
						value={f.selectValue}
						onchange={(e: Event) =>
							updateFilterSelect(f.metric.key, (e.target as HTMLSelectElement).value)}
					>
						<option value="">any</option>
						{#each availableKeys as k (k)}
							<option value={k}>{k}</option>
						{/each}
					</select>
				{:else}
					<span class="chip-op">≥</span>
					<input
						type="range"
						class="chip-slider"
						min="0"
						max={f.metric.max}
						step={f.metric.step}
						value={f.min}
						oninput={(e: Event) =>
							updateFilterMin(f.metric.key, parseFloat((e.target as HTMLInputElement).value))}
					/>
					<span class="chip-value">{f.min > 0 ? f.min : 'off'}</span>
				{/if}
				<button
					class="chip-remove"
					onclick={() => removeFilter(f.metric.key)}
					aria-label="Remove filter"
				>
					✕
				</button>
			</div>
		{/each}

		<div class="add-filter-wrap">
			<button
				class="add-filter-btn"
				onclick={() => (showFilterMenu = !showFilterMenu)}
				aria-label="Add filter"
			>
				+ Filter
			</button>
			{#if showFilterMenu}
				<div class="filter-menu">
					{#each availableMetrics as m (m.key)}
						<button
							class="filter-menu-item"
							onclick={() => {
								addFilter(m.key);
								showFilterMenu = false;
							}}
						>
							{m.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</div>

<div class="song-list" role="tree" aria-label="Song list">
	{#each displaySongs as song (song.id)}
		<div class="song-group" class:active={song.id === activeSongId}>
			<div
				class="song-item"
				class:active={song.id === activeSongId}
				class:playing={isPlaying(song)}
				role="treeitem"
				aria-selected={song.id === activeSongId}
				aria-expanded={expanded.has(song.id)}
			>
				<button
					class="expand-toggle"
					onclick={(e) => handleExpandToggle(e, song.id)}
					aria-label={expanded.has(song.id) ? 'Collapse' : 'Expand'}
				>
					{expanded.has(song.id) ? '▾' : '▸'}
				</button>
				<button class="song-name-btn" onclick={() => handleSongClick(song)}>
					{#if badgeValue(song)}
						<span class="song-badge">{badgeValue(song)}</span>
					{/if}
					<span class="song-name">{song.title}</span>
				</button>
				<span class="song-meta">
					{song.generation_count} gen{song.generation_count !== 1 ? 's' : ''}
				</span>
				{#if song.best_rating}
					<span class="song-rating">★{song.best_rating.toFixed(0)}</span>
				{/if}
			</div>

			{#if expanded.has(song.id)}
				<div class="gen-list-inline">
					{#each visibleGroups(song) as group (group.label)}
						<div class="version-group">
							<span class="version-label">{group.label}</span>
							{#each group.generations as gen (gen.id)}
								<div
									class="gen-row"
									class:playing={isGenPlaying(gen)}
									class:selected={gen.id === activeGenId}
									onclick={() => handleGenSelect(gen, song)}
									onkeydown={(e) => e.key === 'Enter' && handleGenSelect(gen, song)}
									role="button"
									tabindex="0"
									aria-label="Generation {gen.generation_number}"
								>
									<button
										class="gen-play-btn"
										onclick={(e) => handleGenPlayToggle(e, gen, song)}
										aria-label={isGenPlaying(gen) && audioPlaying
											? 'Pause'
											: 'Play generation ' + gen.generation_number}
									>
										{#if isGenPlaying(gen) && audioPlaying}
											⏸
										{:else if isGenPlaying(gen)}
											▶
										{:else}
											▶
										{/if}
									</button>
									<span class="gen-num">gen{gen.generation_number}</span>
									{#if gen.scores?.user_rating}
										<span class="gen-rating">★{gen.scores.user_rating.toFixed(0)}</span>
									{/if}
									{#if gen.scores?.audiobox_enjoyment}
										<span class="gen-score">E:{gen.scores.audiobox_enjoyment.toFixed(1)}</span>
									{/if}
									{#if gen.seed}
										<span class="gen-seed">seed:{gen.seed}</span>
									{/if}
									{#if confirmDeleteGenId === gen.id}
										<button
											class="gen-delete-confirm"
											onclick={(e) => handleGenDeleteConfirm(e, gen)}
										>
											Delete?
										</button>
									{:else}
										<button
											class="gen-delete-btn"
											onclick={(e) => handleGenDeleteClick(e, gen.id)}
											aria-label="Delete generation {gen.generation_number}"
										>
											✕
										</button>
									{/if}
								</div>
							{/each}
						</div>
					{/each}
					{#if song.generations.length === 0}
						<span class="gen-empty">No generations</span>
					{/if}
					{#if song.generations.length > MAX_VISIBLE_GENS && !showAllGens[song.id]}
						<button class="show-all-btn" onclick={() => (showAllGens[song.id] = true)}>
							Show all ({song.generations.length})
						</button>
					{/if}
					{#if showAllGens[song.id] && song.generations.length > MAX_VISIBLE_GENS}
						<button class="show-all-btn" onclick={() => (showAllGens[song.id] = false)}>
							Show less
						</button>
					{/if}
				</div>
			{/if}
		</div>
	{:else}
		<p class="empty">No songs match</p>
	{/each}
</div>

<style>
	.controls {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex-shrink: 0;
	}

	.search {
		width: 100%;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		outline: none;
	}

	.search:focus {
		border-color: var(--primary);
	}

	.search::placeholder {
		color: var(--text-dim);
	}

	.sort-select {
		width: 100%;
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 11px;
	}

	.filter-chips {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.chip {
		display: flex;
		align-items: center;
		gap: 4px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 6px;
		font-size: 10px;
	}

	.chip-label {
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.chip-op {
		color: var(--text-dim);
	}

	.chip-slider {
		flex: 1;
		-webkit-appearance: none;
		appearance: none;
		height: 3px;
		background: var(--border);
		border-radius: 2px;
		outline: none;
		min-width: 60px;
	}

	.chip-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--primary);
		cursor: pointer;
	}

	.chip-value {
		color: var(--text-light);
		font-family: var(--font-display);
		min-width: 24px;
		text-align: right;
	}

	.chip-select {
		flex: 1;
		background: var(--bg);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 2px 4px;
		border-radius: 3px;
		font-size: 10px;
	}

	.chip-remove {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		cursor: pointer;
		padding: 0 2px;
		flex-shrink: 0;
	}

	.chip-remove:hover {
		color: var(--primary);
	}

	.add-filter-wrap {
		position: relative;
	}

	.add-filter-btn {
		background: none;
		border: 1px dashed var(--border);
		color: var(--text-dim);
		padding: 3px 10px;
		border-radius: 4px;
		font-size: 10px;
		width: 100%;
	}

	.add-filter-btn:hover {
		border-color: var(--primary);
		color: var(--text-muted);
	}

	.filter-menu {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		z-index: 50;
		max-height: 200px;
		overflow-y: auto;
		margin-top: 2px;
	}

	.filter-menu-item {
		display: block;
		width: 100%;
		padding: 6px 10px;
		background: none;
		border: none;
		color: var(--text);
		font-size: 11px;
		text-align: left;
		cursor: pointer;
	}

	.filter-menu-item:hover {
		background: var(--surface-hover);
		color: #fff;
	}

	.song-list {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.song-group {
		border-bottom: 1px solid #1a1a1a;
	}

	.song-group.active {
		border-left: 3px solid var(--primary);
	}

	.song-item {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		border: none;
		background: transparent;
		color: var(--text);
		font-size: 12px;
		text-align: left;
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
	}

	.expand-toggle:hover {
		color: var(--text-muted);
	}

	.song-name-btn {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
		padding: 0;
		min-width: 0;
		text-align: left;
	}

	.song-badge {
		font-weight: 700;
		min-width: 28px;
		text-align: center;
		padding: 2px 4px;
		border-radius: 4px;
		font-size: 11px;
		background: var(--score-good-bg);
		color: var(--score-good);
		flex-shrink: 0;
	}

	.song-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.song-meta {
		font-size: 10px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.song-rating {
		font-size: 10px;
		font-family: var(--font-display);
		color: var(--score-ok);
		flex-shrink: 0;
	}

	/* Inline generation list */
	.gen-list-inline {
		display: flex;
		flex-direction: column;
		padding: 0 0 4px 28px;
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
		padding: 4px 12px;
		background: none;
		border: none;
		color: var(--text);
		font-size: 11px;
		text-align: left;
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
		background: #1a2a2a;
		border-left: 2px solid var(--primary);
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

	.gen-score {
		font-size: 9px;
		color: var(--text-dim);
		background: var(--surface);
		padding: 1px 4px;
		border-radius: 3px;
	}

	.gen-rating {
		font-size: 9px;
		font-family: var(--font-display);
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

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
	}
</style>
