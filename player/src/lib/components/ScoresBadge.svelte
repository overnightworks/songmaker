<script lang="ts">
	import { scoreLevel } from '$lib/utils/scores';

	interface Props {
		value: number;
	}

	let { value }: Props = $props();

	const level = $derived(scoreLevel(value));
</script>

{#if value > 0}
	<span
		class="badge"
		class:good={level === 'good'}
		class:ok={level === 'ok'}
		class:bad={level === 'bad'}
	>
		{value}
	</span>
{:else}
	<span class="badge empty">-</span>
{/if}

<style>
	.badge {
		font-weight: 700;
		min-width: 28px;
		text-align: center;
		padding: 2px 4px;
		border-radius: 4px;
		font-size: 11px;
		display: inline-block;
	}

	.good {
		background: var(--score-good-bg);
		color: var(--score-good);
	}

	.ok {
		background: var(--score-ok-bg);
		color: var(--score-ok);
	}

	.bad {
		background: var(--score-bad-bg);
		color: var(--score-bad);
	}

	.empty {
		color: var(--text-dim);
	}
</style>
