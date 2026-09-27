<script lang="ts">
	import { OFFLINE_STRIP_MESSAGE } from '$lib/constants';
	import { offline } from '$lib/stores/connectivity';
	import Icon from './Icon.svelte';
</script>

<!-- The live region stays mounted so a screen reader hears the sentence
	arrive; the strip itself never pushes the page, it rests on the bar. -->
<div class="offline-edge" role="status" aria-live="polite">
	{#if $offline}
		<div class="offline-strip">
			<Icon name="cloud-off" size={14} class="offline-glyph" />
			<span>{OFFLINE_STRIP_MESSAGE}</span>
		</div>
	{/if}
</div>

<style>
	.offline-edge {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--transport-bar-height);
		z-index: 101;
	}

	.offline-strip {
		display: flex;
		align-items: center;
		gap: 9px;
		height: var(--offline-strip-height);
		padding: 0 14px;
		background: var(--bg-deep);
		border-top: 1px solid var(--border);
		color: var(--text-light);
		font-size: 0.82rem;
	}

	.offline-strip :global(.offline-glyph) {
		flex: none;
		color: var(--text-muted);
	}
</style>
