<script lang="ts">
	import type { RecipeChip } from '$lib/stores/recipe';
	import { RECIPE_PANEL_LABEL } from '$lib/constants';

	interface Props {
		chips: RecipeChip[];
		open: boolean;
		onclick: () => void;
	}

	let { chips, open, onclick }: Props = $props();
</script>

<button
	type="button"
	class="recipe-chips"
	aria-expanded={open}
	aria-label={RECIPE_PANEL_LABEL}
	{onclick}
>
	{#each chips as chip (chip.key)}
		<span class="chip" title={chip.label}>
			<span class="chip-label">{chip.label}</span>
			<span class="chip-value">{chip.value}</span>
		</span>
	{/each}
</button>

<style>
	.recipe-chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		padding: 0;
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.25rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		font-size: 0.72rem;
		white-space: nowrap;
	}

	.recipe-chips:hover .chip,
	.recipe-chips[aria-expanded='true'] .chip {
		border-color: var(--primary);
	}

	.chip-label {
		color: var(--text-subtle);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		font-size: 0.62rem;
	}

	.chip-value {
		color: var(--text);
		font-family: var(--font-display);
	}
</style>
