<script lang="ts">
	import { SEED_CHIP_CLEAR_LABEL, seedChipLabel } from '$lib/constants/take-task';
	import { clearSeed, seedFromTake } from '$lib/stores/recipe';
	import Icon from '../Icon.svelte';
</script>

{#if $seedFromTake}
	<span class="seed-chip">
		{seedChipLabel($seedFromTake.takeNumber)}
		<button
			type="button"
			class="clear"
			data-hitbox="frequent"
			title={SEED_CHIP_CLEAR_LABEL}
			aria-label={SEED_CHIP_CLEAR_LABEL}
			onclick={clearSeed}
		>
			<Icon name="x" size={14} />
		</button>
	</span>
{/if}

<style>
	.seed-chip {
		display: inline-flex;
		align-items: center;
		flex: none;
		gap: 2px;
		padding-left: 10px;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		background: var(--surface);
		font-size: 0.78rem;
		white-space: nowrap;
	}

	.clear {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: var(--hitbox-frequent);
		min-height: var(--hitbox-frequent);
		padding: 0;
		border: none;
		background: none;
		color: var(--primary);
		cursor: pointer;
	}
</style>
