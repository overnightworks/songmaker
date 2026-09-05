<script lang="ts">
	import { RAIL_SEARCH_LABEL } from '$lib/constants';
	import { railTreeQuery } from '$lib/stores/filter';

	const query = $derived($railTreeQuery);

	function onInput(event: Event): void {
		railTreeQuery.set((event.currentTarget as HTMLInputElement).value);
	}

	function onKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Escape' || !query) return;
		event.preventDefault();
		railTreeQuery.set('');
	}
</script>

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
		value={query}
		placeholder={RAIL_SEARCH_LABEL}
		aria-label={RAIL_SEARCH_LABEL}
		oninput={onInput}
		onkeydown={onKeydown}
	/>
</div>

<style>
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
</style>
