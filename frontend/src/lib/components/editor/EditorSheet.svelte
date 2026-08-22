<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';

	interface Props {
		open: boolean;
		label: string;
		onclose: () => void;
		children: Snippet;
	}

	let { open, label, onclose, children }: Props = $props();

	let panel: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (!open) return;
		void tick().then(() => {
			if (panel) focusFirstIn(panel);
		});
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!open || !panel) return;
		handleFocusTrapKeydown(panel, event, onclose);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#if open}
	<div class="sheet-modal">
		<button class="sheet-backdrop" tabindex="-1" onclick={onclose} aria-label="Close"></button>
		<div
			bind:this={panel}
			class="sheet-panel"
			role="dialog"
			aria-modal="true"
			aria-label={label}
			tabindex="-1"
		>
			{@render children()}
		</div>
	</div>
{/if}

<style>
	.sheet-modal {
		position: fixed;
		inset: 0;
		z-index: 400;
	}

	.sheet-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}

	.sheet-panel {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 1;
		max-height: 85vh;
		overflow-y: auto;
		background: var(--bg);
		border-top: 1px solid var(--border);
		border-radius: 12px 12px 0 0;
		box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.3);
		padding: 1rem;
	}
</style>
