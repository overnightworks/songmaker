<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		MODELS_ADVANCED_LABEL,
		MODELS_COLUMN_MODEL_LABEL,
		MODELS_COLUMN_PROVIDER_LABEL,
		MODELS_COLUMN_ROUTE_LABEL
	} from '$lib/constants';

	interface Props {
		task: string;
		provider: string;
		route: string;
		model: string;
		advanced?: Snippet;
	}

	let { task, provider, route, model, advanced }: Props = $props();
</script>

<div class="tt-row">
	<div class="cell cell-task">{task}</div>
	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_PROVIDER_LABEL}</span>
		<span class="ro">{provider}</span>
	</div>
	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_ROUTE_LABEL}</span>
		<span class="ro">{route}</span>
	</div>
	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_MODEL_LABEL}</span>
		<span class="ro">{model}</span>
	</div>
</div>

{#if advanced}
	<div class="tt-sub">
		<details class="adv">
			<summary>{MODELS_ADVANCED_LABEL}</summary>
			<div class="adv-body">{@render advanced()}</div>
		</details>
	</div>
{/if}

<style>
	.tt-row {
		display: grid;
		grid-template-columns: var(--models-columns);
		gap: var(--models-gap);
		align-items: start;
		padding: 0.65rem 0.85rem;
		border-top: 1px solid var(--border);
		border-left: 3px solid transparent;
	}

	.cell {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 0.2rem;
		min-width: 0;
	}
	.cell-task {
		font-weight: 600;
		letter-spacing: 0.04em;
		padding-top: 0.3rem;
	}
	.k {
		display: none;
		font-size: 0.68rem;
		letter-spacing: 0.07em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.ro {
		display: block;
		padding: 0.34rem 0;
		font-size: 0.8rem;
		color: var(--text);
	}

	.tt-sub {
		padding: 0 0.85rem 0.6rem var(--models-sub-indent);
		border-left: 3px solid transparent;
	}

	details.adv summary {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		cursor: pointer;
		list-style: none;
		text-transform: uppercase;
		letter-spacing: 0.09em;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--accent);
	}
	details.adv summary::-webkit-details-marker {
		display: none;
	}
	details.adv summary::before {
		content: '›';
		font-size: 0.85rem;
	}
	details.adv[open] summary::before {
		content: '⌄';
	}
	.adv-body {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		margin-top: 0.45rem;
		flex-wrap: wrap;
	}

	@media (max-width: 768px) {
		.tt-row {
			grid-template-columns: minmax(0, 1fr);
			gap: 0.3rem;
			border: 1px solid var(--border);
			border-left-width: 3px;
			border-radius: 4px;
			margin-bottom: 0.6rem;
		}
		.cell {
			grid-template-columns: 4.4rem minmax(0, 1fr);
			align-items: start;
			gap: 0.55rem;
		}
		.cell .k {
			display: block;
			grid-row: 1;
			grid-column: 1;
			padding-top: 0.35rem;
		}
		.cell > :global(*:not(.k)) {
			grid-column: 2;
		}
		.cell-task {
			grid-template-columns: minmax(0, 1fr);
			font-size: 0.95rem;
			text-transform: uppercase;
		}
		.tt-sub {
			padding-left: 0.85rem;
		}
	}
</style>
