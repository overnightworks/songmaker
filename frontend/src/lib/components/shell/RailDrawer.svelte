<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { RAIL_DRAWER_CLOSE_LABEL, RAIL_DRAWER_LABEL } from '$lib/constants';
	import { closeSidebar, railWidth, sidebarOpen } from '$lib/stores/ui';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';

	let { children }: { children: Snippet } = $props();

	let panel: HTMLDivElement | undefined = $state();
	const open = $derived($sidebarOpen);

	afterNavigate(() => closeSidebar());

	$effect(() => {
		if (!open) return;
		void tick().then(() => {
			if (panel) focusFirstIn(panel);
		});
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!open || !panel) return;
		handleFocusTrapKeydown(panel, event, () => closeSidebar());
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#if open}
	<div class="drawer-modal">
		<button
			class="drawer-backdrop"
			tabindex="-1"
			onclick={() => closeSidebar()}
			aria-label={RAIL_DRAWER_CLOSE_LABEL}
		></button>
		<div
			bind:this={panel}
			class="drawer-panel"
			style:--rail-width={`${$railWidth}px`}
			role="dialog"
			aria-modal="true"
			aria-label={RAIL_DRAWER_LABEL}
			tabindex="-1"
		>
			{@render children()}
		</div>
	</div>
{/if}

<style>
	.drawer-modal {
		position: fixed;
		inset: 0;
		z-index: 400;
	}

	.drawer-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}

	.drawer-panel {
		position: fixed;
		top: 0;
		bottom: 0;
		left: 0;
		width: min(var(--rail-width), 84vw);
		z-index: 1;
		box-shadow: 4px 0 24px rgba(0, 0, 0, 0.3);
	}

	.drawer-panel :global(.rail) {
		width: 100%;
	}
</style>
