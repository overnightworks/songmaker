<script lang="ts">
	import { filteredSongs, selectedSongId, selectSong, playback } from '$lib/stores/player';
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
	import type { SongItem } from '$lib/api/types';

	const songs = $derived($filteredSongs);
	const activeSongId = $derived($selectedSongId);
	const pb = $derived($playback);
	const currentSortKey = $derived($sortKey);
	const search = $derived($searchQuery);
	const filters = $derived($activeFilters);
	const sortMetric = $derived(getSortMetric(currentSortKey));

	let showFilterMenu = $state(false);

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

	function badgeValue(song: SongItem): string {
		const val = sortMetric.getValue(song);
		if (typeof val !== 'number') return '';
		return sortMetric.max <= 10 ? String(val) : val.toFixed(1);
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

<div class="song-list" role="listbox" aria-label="Song list">
	{#each displaySongs as song (song.id)}
		<button
			class="song-item"
			class:active={song.id === activeSongId}
			class:playing={isPlaying(song)}
			onclick={() => selectSong(song.id)}
			role="option"
			aria-selected={song.id === activeSongId}
		>
			{#if badgeValue(song)}
				<span class="song-badge">{badgeValue(song)}</span>
			{/if}
			<span class="song-name">{song.title}</span>
			<span class="song-meta">
				{song.generation_count} gen{song.generation_count !== 1 ? 's' : ''}
			</span>
			{#if song.best_rating}
				<span class="song-rating">★{song.best_rating.toFixed(0)}</span>
			{/if}
		</button>
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

	.song-item {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		border: none;
		border-bottom: 1px solid #1a1a1a;
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
		border-left: 3px solid var(--primary);
	}

	.song-item.playing {
		background: #1a1a2a;
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

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
	}
</style>
