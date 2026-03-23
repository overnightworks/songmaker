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
		background: #1a3a1a;
		color: #4f4;
	}

	.ok {
		background: #3a3a1a;
		color: #ff4;
	}

	.bad {
		background: #3a1a1a;
		color: #f44;
	}

	.empty {
		color: #555;
	}
</style>
