<script lang="ts">
	import {
		browsingAlbum,
		browsingAlbumIndex,
		browsingTrackIndex,
		playback,
		selectTrack,
		playTrack
	} from '$lib/stores/player';
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
	import ScoresBadge from './ScoresBadge.svelte';
	import type { Track } from '$lib/api/types';

	const album = $derived($browsingAlbum);
	const activeTrackIdx = $derived($browsingTrackIndex);
	const albumIdx = $derived($browsingAlbumIndex);
	const pb = $derived($playback);
	const currentSortKey = $derived($sortKey);
	const search = $derived($searchQuery);
	const filters = $derived($activeFilters);
	const sortMetric = $derived(getSortMetric(currentSortKey));

	let showFilterMenu = $state(false);

	interface IndexedTrack {
		track: Track;
		index: number;
	}

	const availableMetrics = $derived(
		METRICS.filter((m) => !filters.some((f) => f.metric.key === m.key))
	);

	const selectOptionsForKey = $derived.by(() => {
		if (!album) return [];
		const seen: Record<string, boolean> = {};
		for (const t of album.tracks) {
			const k = t.generation?.key;
			if (k) seen[k] = true;
		}
		return Object.keys(seen).sort();
	});

	const filteredTracks = $derived.by(() => {
		if (!album) return [];
		let tracks: IndexedTrack[] = album.tracks.map((t, i) => ({ track: t, index: i }));

		if (search) {
			const q = search.toLowerCase();
			tracks = tracks.filter(({ track }) => track.title.toLowerCase().includes(q));
		}

		const rawTracks = tracks.map((t) => t.track);
		const passedTracks = applyFilters(rawTracks, filters);
		const passedFiles = new Set(passedTracks.map((t) => t.file));
		tracks = tracks.filter(({ track }) => passedFiles.has(track.file));

		if (currentSortKey === 'name') {
			tracks.sort((a, b) => a.track.title.localeCompare(b.track.title));
		} else if (currentSortKey !== 'latest') {
			tracks.sort(
				(a, b) =>
					(sortMetric.getValue(b.track) as number) - (sortMetric.getValue(a.track) as number)
			);
		}

		return tracks;
	});

	function isPlaying(index: number): boolean {
		return pb?.albumIndex === albumIdx && pb?.trackIndex === index;
	}

	function displayValue(track: Track): string {
		if (currentSortKey === 'latest' || currentSortKey === 'name') return '';
		const val = sortMetric.getValue(track);
		if (typeof val !== 'number' || val === 0) return '';
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
		<option value="latest">Sort: Latest</option>
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
						{#each selectOptionsForKey as k (k)}
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
					aria-label="Remove {f.metric.label} filter"
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
	{#each filteredTracks as { track, index } (index)}
		<div
			class="song-item"
			class:active={index === activeTrackIdx}
			class:playing={isPlaying(index)}
			role="option"
			aria-selected={index === activeTrackIdx}
		>
			<button
				class="play-icon"
				onclick={(e: MouseEvent) => {
					e.stopPropagation();
					playTrack(albumIdx, index);
				}}
				aria-label="Play {track.title}"
			>
				{#if isPlaying(index)}
					<span class="icon-playing">🔊</span>
				{:else}
					<span class="icon-play">▶</span>
				{/if}
			</button>
			<button class="song-body" onclick={() => selectTrack(index)}>
				{#if displayValue(track)}
					<ScoresBadge value={sortMetric.getValue(track) as number} />
				{/if}
				<span class="song-name">{track.title}</span>
				{#if track.scores?.user_rating}
					<span class="user-rating">★{track.scores.user_rating.toFixed(1)}</span>
				{/if}
			</button>
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
		min-width: 40px;
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
		display: flex;
		align-items: center;
		border-bottom: 1px solid #1a1a1a;
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

	.play-icon {
		width: 32px;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		cursor: pointer;
		flex-shrink: 0;
		padding: 8px 4px 8px 8px;
	}

	.song-item:hover .play-icon .icon-play {
		color: var(--primary);
	}

	.icon-playing {
		font-size: 12px;
	}

	.icon-play {
		opacity: 0;
		transition: opacity 0.15s;
	}

	.song-item:hover .icon-play {
		opacity: 1;
	}

	.song-body {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px 8px 0;
		background: none;
		border: none;
		color: var(--text);
		font-size: 12px;
		text-align: left;
		cursor: pointer;
		min-width: 0;
	}

	.song-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.user-rating {
		font-size: 10px;
		font-family: var(--font-display);
		color: var(--score-ok);
		flex-shrink: 0;
		white-space: nowrap;
	}

	.empty {
		padding: 20px;
		color: var(--text-dim);
		text-align: center;
	}
</style>
