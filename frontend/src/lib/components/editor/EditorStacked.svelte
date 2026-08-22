<script lang="ts">
	import type { RecipeChip } from '$lib/stores/recipe';
	import {
		RECIPE_GROUP_REPRODUCE_LABEL,
		RECIPE_GROUP_SOUND_LABEL,
		RECIPE_GROUP_TEXT_LABEL,
		RECIPE_STACKED_EDIT_LABEL,
		RECIPE_STACKED_LABEL
	} from '$lib/constants';

	interface Props {
		chips: RecipeChip[];
		onexpand: () => void;
	}

	let { chips, onexpand }: Props = $props();

	interface StackedGroup {
		label: string;
		keys: string[];
	}

	const GROUPS: StackedGroup[] = [
		{
			label: RECIPE_GROUP_SOUND_LABEL,
			keys: ['model', 'takes', 'bpm', 'duration', 'key', 'voice']
		},
		{ label: RECIPE_GROUP_TEXT_LABEL, keys: ['lm', 'dit'] },
		{ label: RECIPE_GROUP_REPRODUCE_LABEL, keys: ['seed', 'repaint'] }
	];

	function summarize(keys: string[]): string {
		return keys
			.map((key) => chips.find((c) => c.key === key))
			.filter((c): c is RecipeChip => c !== undefined)
			.map((c) => `${c.label} ${c.value}`)
			.join(' · ');
	}
</script>

<!--
	Rendered instead of the full RecipePanel only when Co-Writer and Recipe are
	both open (the "stacked" state) — the full panel's three multi-field groups
	push the chat column below the fold at typical viewport heights. This is a
	one-row-per-group summary; "Edit" swaps in the full panel on demand.
-->
<div class="editor-stacked" role="region" aria-label={RECIPE_STACKED_LABEL}>
	{#each GROUPS as group (group.label)}
		<div class="stacked-row">
			<span class="stacked-title">{group.label}</span>
			<span class="stacked-summary">{summarize(group.keys)}</span>
		</div>
	{/each}
	<button type="button" class="stacked-edit" onclick={onexpand}>
		{RECIPE_STACKED_EDIT_LABEL}
	</button>
</div>

<style>
	.editor-stacked {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0.7rem 0.9rem;
		background: var(--surface);
		border: 1px solid var(--primary);
		border-radius: var(--card-radius);
	}

	.stacked-row {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		min-width: 0;
	}

	.stacked-title {
		flex-shrink: 0;
		width: 5.5rem;
		font-family: var(--font-display);
		font-size: 0.68rem;
		color: var(--primary);
		text-transform: uppercase;
		letter-spacing: 0.8px;
	}

	.stacked-summary {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.stacked-edit {
		align-self: flex-end;
		padding: 0.25rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
	}

	.stacked-edit:hover {
		border-color: var(--primary);
		color: var(--primary);
	}
</style>
