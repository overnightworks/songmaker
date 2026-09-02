<script lang="ts">
	// Owns only the text field's own affordances (typing, clearing via button
	// or Escape) -- narrowing the row's tiles from that value is the row's own
	// job, since it is the row that knows what a tile is and which one is
	// open. Purely local, controlled state: no store, no URL param, so the
	// text is gone the moment this row unmounts.
	import {
		LIBRARY_ROW_FILTER_CLEAR_LABEL,
		libraryRowFilterAriaLabel,
		libraryRowFilterPlaceholder
	} from '$lib/constants';

	interface Props {
		value: string;
		collectionLabel: string;
	}

	let { value = $bindable(''), collectionLabel }: Props = $props();

	let inputEl = $state<HTMLInputElement | null>(null);

	function clear(): void {
		value = '';
		inputEl?.focus();
	}

	function onKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Escape' || value === '') return;
		event.preventDefault();
		clear();
	}
</script>

<div class="library-row-filter">
	<input
		type="text"
		class="library-row-filter-input"
		bind:value
		bind:this={inputEl}
		placeholder={libraryRowFilterPlaceholder(collectionLabel)}
		aria-label={libraryRowFilterAriaLabel(collectionLabel)}
		autocomplete="off"
		onkeydown={onKeydown}
	/>
	{#if value}
		<button
			type="button"
			class="library-row-filter-clear"
			onclick={clear}
			aria-label={LIBRARY_ROW_FILTER_CLEAR_LABEL}
		>
			×
		</button>
	{/if}
</div>

<style>
	.library-row-filter {
		display: flex;
		align-items: center;
		gap: 0.2rem;
		padding: 0.4rem 0.9rem 0;
	}

	.library-row-filter-input {
		width: 160px;
		max-width: 100%;
		font: inherit;
		font-size: 0.78rem;
		padding: 0.25rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
	}

	.library-row-filter-input::placeholder {
		color: var(--text-subtle);
	}

	.library-row-filter-input:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}

	.library-row-filter-clear {
		border: 0;
		background: none;
		color: var(--text-subtle);
		font-size: 1rem;
		line-height: 1;
		padding: 0.1rem 0.4rem;
		border-radius: 3px;
	}

	.library-row-filter-clear:hover {
		color: var(--text);
		background: var(--surface-hover);
	}

	.library-row-filter-clear:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}
</style>
