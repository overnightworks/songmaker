<script lang="ts">
	import { currentAlbum, currentTrackIndex, selectTrack } from '$lib/stores/player';
	import { scoreFilter, sortMode } from '$lib/stores/filter';
	import type { SortMode } from '$lib/stores/filter';
	import { getLyricalCoherence, getDynamics } from '$lib/utils/scores';
	import ScoresBadge from './ScoresBadge.svelte';
	import type { Track } from '$lib/api/types';

	const album = $derived($currentAlbum);
	const activeTrackIdx = $derived($currentTrackIndex);
	const filter = $derived($scoreFilter);
	const sort = $derived($sortMode);

	interface IndexedTrack {
		track: Track;
		index: number;
	}

	const filteredTracks = $derived.by(() => {
		if (!album) return [];
		let tracks: IndexedTrack[] = album.tracks.map((t, i) => ({ track: t, index: i }));

		if (filter > 0) {
			tracks = tracks.filter(({ track }) => getLyricalCoherence(track) >= filter);
		}

		if (sort === 'vocal') {
			tracks.sort((a, b) => getLyricalCoherence(b.track) - getLyricalCoherence(a.track));
		} else if (sort === 'dynamics') {
			tracks.sort((a, b) => getDynamics(b.track) - getDynamics(a.track));
		} else if (sort === 'name') {
			tracks.sort((a, b) => a.track.title.localeCompare(b.track.title));
		}

		return tracks;
	});

	function setFilter(min: number): void {
		scoreFilter.set(min);
	}

	function setSort(e: Event): void {
		const target = e.target as HTMLSelectElement;
		sortMode.set(target.value as SortMode);
	}

	const FILTER_OPTIONS = [
		{ label: 'All', value: 0 },
		{ label: '7+', value: 7 },
		{ label: '5+', value: 5 }
	];
</script>

<div class="filters">
	<span class="filter-label">Filter:</span>
	{#each FILTER_OPTIONS as opt (opt.value)}
		<button
			class="filter-btn"
			class:active={filter === opt.value}
			onclick={() => setFilter(opt.value)}
		>
			{opt.label}
		</button>
	{/each}
	<select class="sort-select" onchange={setSort} value={sort}>
		<option value="vocal">Sort: Lyrical Coherence</option>
		<option value="latest">Sort: Latest</option>
		<option value="dynamics">Sort: Dynamics</option>
		<option value="name">Sort: Name</option>
	</select>
</div>

<div class="song-list" role="listbox" aria-label="Song list">
	{#each filteredTracks as { track, index } (index)}
		<button
			class="song-item"
			class:active={index === activeTrackIdx}
			onclick={() => selectTrack(index)}
			role="option"
			aria-selected={index === activeTrackIdx}
		>
			<ScoresBadge value={getLyricalCoherence(track)} />
			<span class="song-name">{track.title}</span>
			{#if getDynamics(track) > 0}
				<span class="song-dynamics">{Math.round(getDynamics(track))}</span>
			{/if}
		</button>
	{:else}
		<p class="empty">No songs match filter</p>
	{/each}
</div>

<style>
	.filters {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		align-items: center;
		flex-shrink: 0;
	}

	.filter-label {
		font-size: 10px;
		color: var(--text-muted);
	}

	.filter-btn {
		background: #222;
		border: 1px solid #444;
		color: #ccc;
		padding: 4px 10px;
		border-radius: 12px;
		font-size: 11px;
	}

	.filter-btn.active {
		background: var(--primary);
		color: #fff;
		border-color: var(--primary);
	}

	.filter-btn:hover {
		border-color: var(--primary);
	}

	.sort-select {
		background: #222;
		border: 1px solid #444;
		color: #ccc;
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 11px;
	}

	.song-list {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.song-item {
		width: 100%;
		padding: 8px 12px;
		display: flex;
		align-items: center;
		gap: 8px;
		border: none;
		border-bottom: 1px solid #1a1a1a;
		background: transparent;
		color: var(--text);
		font-size: 12px;
		text-align: left;
	}

	.song-item:hover {
		background: var(--surface-hover);
	}

	.song-item.active {
		background: #1a2a1a;
		border-left: 3px solid var(--primary);
	}

	.song-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.song-dynamics {
		font-size: 10px;
		color: var(--text-muted);
	}

	.empty {
		padding: 20px;
		color: #666;
		text-align: center;
	}
</style>
