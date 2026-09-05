<script lang="ts">
	import { RAIL_SEARCH_LABEL } from '$lib/constants';
	import { railTreeQuery } from '$lib/stores/filter';
	import {
		firstRailSearchTarget,
		groupRailSearchResults,
		railSearch,
		retryRailSearch,
		syncRailSearch
	} from '$lib/stores/railSearch';
	import { openRailSearchTarget } from '$lib/stores/navigation';
	import { playlistList } from '$lib/stores/playlists';

	const query = $derived($railTreeQuery);
	const state = $derived($railSearch);
	const groups = $derived(groupRailSearchResults(state, $playlistList));
	const hasQuery = $derived(state.query.length > 0);

	function onInput(event: Event): void {
		const value = (event.currentTarget as HTMLInputElement).value;
		railTreeQuery.set(value);
		syncRailSearch(value);
	}

	function onKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape' && query) {
			event.preventDefault();
			railTreeQuery.set('');
			syncRailSearch('');
			return;
		}
		if (event.key !== 'Enter' || !hasQuery || state.status !== 'ready') return;
		const target = firstRailSearchTarget(state, $playlistList);
		if (!target) return;
		event.preventDefault();
		void openRailSearchTarget(target);
	}

	function selectResult(target: ReturnType<typeof firstRailSearchTarget>): void {
		if (target) void openRailSearchTarget(target);
	}
</script>

<div class="rail-search-region" class:rail-search-results={hasQuery}>
	<div class="rail-search">
		<svg
			width="15"
			height="15"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			aria-hidden="true"
		>
			<circle cx="11" cy="11" r="7" />
			<path d="m20 20-4-4" />
		</svg>
		<input
			type="search"
			data-hitbox="text"
			value={query}
			placeholder={RAIL_SEARCH_LABEL}
			aria-label={RAIL_SEARCH_LABEL}
			oninput={onInput}
			onkeydown={onKeydown}
		/>
	</div>

	{#if hasQuery}
		<div class="rail-search-panel" aria-live="polite">
			{#if state.status === 'loading'}
				<p class="rail-search-status">Searching…</p>
			{:else if state.status === 'error'}
				<div class="rail-search-error" role="alert">
					<p>{state.error ?? 'Search failed'}</p>
					<button type="button" onclick={retryRailSearch}>Retry</button>
				</div>
			{:else if groups.length === 0}
				<p class="rail-search-status">No results for “{state.query}”.</p>
			{:else}
				{#each groups as group (group.label)}
					<section class="rail-search-group" aria-label={`${group.label} results`}>
						<h2>{group.label}</h2>
						<ul>
							{#each group.results as result (result.id)}
								<li>
									<button type="button" class="rail-search-result" onclick={() => selectResult(result.target)}>
										<span>{result.label}</span>
										{#if result.meta}<small>{result.meta}</small>{/if}
									</button>
								</li>
							{/each}
						</ul>
					</section>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	.rail-search-region {
		flex-shrink: 0;
		min-height: 0;
	}

	.rail-search-region.rail-search-results {
		display: flex;
		flex: 1;
		flex-direction: column;
	}

	:global(.rail:has(.rail-search-results) .rail-scroll),
	:global(.rail:has(.rail-search-results) .rail-settings-pin) {
		display: none;
	}

	.rail-search {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		margin: 0 12px 8px;
		padding: 7px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-subtle);
		background: var(--surface-hover);
	}

	.rail-search:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 16%, transparent);
	}

	input {
		width: 100%;
		min-width: 0;
		padding: 0;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--text);
		font: inherit;
		font-size: 0.82rem;
	}

	input::placeholder {
		color: var(--text-subtle);
	}

	.rail-search-panel {
		min-height: 0;
		overflow-y: auto;
		padding: 0 0 8px;
	}

	.rail-search-status,
	.rail-search-error {
		margin: 4px 12px;
		padding: 8px;
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.rail-search-error {
		border-left: 3px solid var(--score-bad);
		background: var(--score-bad-bg);
		color: var(--score-bad);
	}

	.rail-search-error p {
		margin: 0 0 8px;
	}

	.rail-search-error button {
		border: 1px solid currentColor;
		background: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.rail-search-group h2 {
		margin: 8px 16px 3px;
		color: var(--text-subtle);
		font-family: var(--font-display);
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.rail-search-group ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.rail-search-result {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 16px 8px 24px;
		border: 0;
		border-left: 3px solid transparent;
		background: none;
		color: var(--text-muted);
		font: inherit;
		font-size: 0.82rem;
		text-align: left;
		cursor: pointer;
	}

	.rail-search-result:hover,
	.rail-search-result:focus-visible {
		border-left-color: var(--primary);
		outline: 0;
		background: color-mix(in srgb, var(--primary) 8%, transparent);
		color: var(--text);
	}

	.rail-search-result span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.rail-search-result small {
		margin-left: auto;
		flex-shrink: 0;
		color: var(--text-subtle);
	}
</style>
