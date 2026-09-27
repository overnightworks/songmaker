<script lang="ts">
	import { RAIL_SEARCH_CLEAR_LABEL, RAIL_SEARCH_LABEL } from '$lib/constants';
	import { isAdmin } from '$lib/stores/auth';
	import { railTreeQuery } from '$lib/stores/librarySearch';
	import {
		groupRailSearchResults,
		railSearch,
		retryRailSearch,
		syncRailSearch,
		visibleRailSearchPages,
		type RailSearchTarget
	} from '$lib/stores/railSearch';
	import { openRailSearchTarget } from '$lib/stores/navigation';
	import { playlistList } from '$lib/stores/playlists';
	import { titleInitials } from '$lib/utils/format';
	import PlaylistCover from '../PlaylistCover.svelte';

	const ACTIVE_RESULT_CLASS = 'rail-search-result-active';

	const query = $derived($railTreeQuery);
	const searchState = $derived($railSearch);
	const pages = $derived(visibleRailSearchPages($isAdmin));
	const groups = $derived(groupRailSearchResults(searchState, $playlistList, pages));
	const results = $derived(groups.flatMap((group) => group.results));
	const hasQuery = $derived(searchState.query.length > 0);

	let chosenResultId = $state<string | null>(null);
	const activeIndex = $derived(
		Math.max(
			0,
			results.findIndex((result) => result.id === chosenResultId)
		)
	);
	const activeResultId = $derived(results[activeIndex]?.id ?? null);

	let input: HTMLInputElement;
	let panel: HTMLElement | undefined = $state();

	function setQuery(value: string): void {
		chosenResultId = null;
		railTreeQuery.set(value);
		syncRailSearch(value);
	}

	function onInput(event: Event): void {
		setQuery((event.currentTarget as HTMLInputElement).value);
	}

	function clearSearch(): void {
		setQuery('');
		input.focus();
	}

	$effect(() => {
		if (chosenResultId === null) return;
		panel?.querySelector(`.${ACTIVE_RESULT_CLASS}`)?.scrollIntoView({ block: 'nearest' });
	});

	function moveActiveResult(step: 1 | -1): void {
		const next = Math.min(results.length - 1, Math.max(0, activeIndex + step));
		chosenResultId = results[next].id;
	}

	function onKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape' && query) {
			event.preventDefault();
			setQuery('');
			return;
		}
		if (!hasQuery || results.length === 0) return;
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			moveActiveResult(event.key === 'ArrowDown' ? 1 : -1);
			return;
		}
		if (event.key !== 'Enter') return;
		event.preventDefault();
		selectResult(results[activeIndex].target);
	}

	function selectResult(target: RailSearchTarget): void {
		void openRailSearchTarget(target);
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
			bind:this={input}
			type="search"
			data-hitbox="text"
			value={query}
			placeholder={RAIL_SEARCH_LABEL}
			aria-label={RAIL_SEARCH_LABEL}
			oninput={onInput}
			onkeydown={onKeydown}
		/>
		{#if query}
			<button
				type="button"
				class="rail-search-clear"
				data-hitbox="frequent"
				aria-label={RAIL_SEARCH_CLEAR_LABEL}
				onclick={clearSearch}>×</button
			>
		{/if}
	</div>

	{#if hasQuery}
		<div class="rail-search-panel" aria-live="polite" bind:this={panel}>
			{#if searchState.status === 'loading'}
				<p class="rail-search-status">Searching…</p>
			{:else if searchState.status === 'error'}
				<div class="rail-search-error" role="alert">
					<p>{searchState.error ?? 'Search failed'}</p>
					<button type="button" onclick={retryRailSearch}>Retry</button>
				</div>
			{/if}

			{#if groups.length > 0}
				{#each groups as group (group.label)}
					<section class="rail-search-group" aria-label={`${group.label} results`}>
						<h2>{group.label}</h2>
						<ul>
							{#each group.results as result (result.id)}
								<li>
									<button
										type="button"
										class="rail-search-result"
										class:rail-search-result-active={result.id === activeResultId}
										onclick={() => selectResult(result.target)}
									>
										{#if result.picture.kind === 'album'}
											<span class="rail-search-art" aria-hidden="true">
												{#if result.picture.cover}
													<img src={result.picture.cover.card} alt="" />
												{:else}
													{titleInitials(result.label)}
												{/if}
											</span>
										{:else if result.picture.kind === 'playlist'}
											<PlaylistCover
												title={result.label}
												covers={result.picture.covers}
												cover={result.picture.cover}
												size="var(--rail-search-picture)"
											/>
										{:else}
											<span
												class="rail-search-glyph"
												class:rail-search-page-glyph={result.picture.kind === 'page'}
												aria-hidden="true">{result.picture.glyph}</span
											>
										{/if}
										<span class="rail-search-text">
											<span class="rail-search-title">
												{#each result.labelParts as part, index (index)}
													{#if part.matched}<mark>{part.text}</mark>{:else}{part.text}{/if}
												{/each}
											</span>
											<small
												><span class="rail-search-kind">{result.kindWord}</span
												>{#if result.detail}{` · ${result.detail}`}{/if}</small
											>
										</span>
									</button>
								</li>
							{/each}
						</ul>
					</section>
				{/each}
			{:else if searchState.status === 'ready'}
				<p class="rail-search-status">No results for “{searchState.query}”.</p>
			{/if}
		</div>
	{/if}
</div>

<style>
	.rail-search-region {
		--rail-search-picture: 28px;
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

	/* The outline is an inset shadow rather than a border so the bar is exactly
	   as tall as the field's own touch target instead of wrapping it. */
	.rail-search {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
		min-width: 0;
		min-height: 32px;
		margin: 0 12px 8px;
		padding: 0 0 0 10px;
		border: 0;
		border-radius: 4px;
		color: var(--text-subtle);
		background: var(--surface-hover);
		box-shadow: inset 0 0 0 1px var(--border);
	}

	.rail-search:focus-within {
		box-shadow:
			inset 0 0 0 1px var(--accent),
			0 0 0 2px color-mix(in srgb, var(--accent) 16%, transparent);
	}

	.rail-search svg {
		flex-shrink: 0;
	}

	input {
		flex: 1;
		align-self: stretch;
		width: 100%;
		min-width: 0;
		padding: 0;
		border: 0;
		outline: 0;
		box-shadow: none;
		background: transparent;
		color: var(--text);
		font: inherit;
		font-size: 0.8rem;
	}

	input::placeholder {
		color: var(--text-subtle);
	}

	input::-webkit-search-cancel-button {
		appearance: none;
	}

	.rail-search-clear {
		align-self: stretch;
		border: 0;
		background: none;
		color: var(--text-subtle);
		font: inherit;
		font-size: 1rem;
	}

	.rail-search-clear:hover {
		color: var(--text);
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
		gap: 10px;
		width: 100%;
		padding: 5px 16px 5px 13px;
		border: 0;
		border-left: 3px solid transparent;
		background: none;
		color: var(--text-muted);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	@media (any-pointer: coarse) {
		.rail-search-region {
			--rail-search-picture: 32px;
		}

		.rail-search-result {
			min-height: 48px;
		}
	}

	:global(html[data-pointer='coarse']) .rail-search-region {
		--rail-search-picture: 32px;
	}

	:global(html[data-pointer='coarse']) .rail-search-result {
		min-height: 48px;
	}

	.rail-search-result:hover,
	.rail-search-result:focus-visible,
	.rail-search-result-active {
		border-left-color: var(--primary);
		outline: 0;
		background: color-mix(in srgb, var(--primary) 8%, transparent);
		color: var(--text);
	}

	.rail-search-art,
	.rail-search-glyph {
		display: grid;
		place-items: center;
		width: var(--rail-search-picture);
		height: var(--rail-search-picture);
		flex: 0 0 var(--rail-search-picture);
		overflow: hidden;
		color: var(--text-muted);
	}

	.rail-search-art {
		border-radius: 3px;
		background: var(--surface-hover);
		font-family: var(--font-display);
		font-size: 0.6rem;
		letter-spacing: 0.04em;
	}

	.rail-search-art img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.rail-search-glyph {
		box-sizing: border-box;
		border: 1px solid var(--border);
		border-radius: 50%;
		font-size: 0.85rem;
	}

	.rail-search-glyph.rail-search-page-glyph {
		border-radius: 3px;
	}

	.rail-search-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.rail-search-title,
	.rail-search-result small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.rail-search-title {
		font-size: 0.8rem;
	}

	.rail-search-title mark {
		background: none;
		color: var(--primary);
		font-weight: 600;
	}

	.rail-search-result small {
		color: var(--text-subtle);
		font-size: 0.7rem;
	}

	.rail-search-kind {
		color: var(--text-muted);
	}
</style>
