<script lang="ts">
	import { tick, untrack, type Snippet } from 'svelte';
	import { COMPACT_LAYOUT_MAX_PX } from '$lib/constants';
	import { historyLayerState } from '$lib/stores/layers';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';

	interface Props {
		/** The history layer Back closes, unique per menu. */
		layer: string;
		/** Names both the trigger and the open menu. */
		label: string;
		closeLabel: string;
		/** Shows the trigger pressed while the menu is closed, e.g. while a choice it made is still open. */
		pressed?: boolean;
		trigger: Snippet;
		children: Snippet;
	}

	let { layer, label, closeLabel, pressed = false, trigger, children }: Props = $props();

	const VIEWPORT_MARGIN_PX = 8;
	const TRIGGER_GAP_PX = 8;

	const open = historyLayerState(
		untrack(() => layer),
		false
	);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let panel: HTMLDivElement | undefined = $state();
	let left = $state(0);
	let top = $state(0);
	let wasOpen = false;
	let focusTriggerOnClose = true;

	$effect(() => {
		const isOpen = $open;
		if (wasOpen && !isOpen && focusTriggerOnClose) focusTrigger();
		focusTriggerOnClose = true;
		wasOpen = isOpen;
	});

	function withinViewport(start: number, size: number, viewport: number): number {
		const last = viewport - VIEWPORT_MARGIN_PX - size;
		return Math.max(VIEWPORT_MARGIN_PX, Math.min(start, last));
	}

	// A phone's popover stands at the screen edge nearest its trigger, the way
	// the frozen frames draw it; a wider window keeps it under the trigger's
	// own right edge.
	function horizontalStart(anchor: DOMRect, width: number): number {
		const viewport = window.innerWidth;
		const underTrigger = withinViewport(anchor.right - width, width, viewport);
		if (viewport > COMPACT_LAYOUT_MAX_PX) return underTrigger;
		const triggerCentre = anchor.left + anchor.width / 2;
		return triggerCentre < viewport / 2
			? VIEWPORT_MARGIN_PX
			: withinViewport(viewport - VIEWPORT_MARGIN_PX - width, width, viewport);
	}

	function placeBelowOrAboveTrigger(): void {
		if (!triggerButton || !panel) return;
		const anchor = triggerButton.getBoundingClientRect();
		const size = panel.getBoundingClientRect();
		const below = anchor.bottom + TRIGGER_GAP_PX;
		const above = anchor.top - TRIGGER_GAP_PX - size.height;
		const fitsBelow = below + size.height <= window.innerHeight - VIEWPORT_MARGIN_PX;
		const fitsAbove = above >= VIEWPORT_MARGIN_PX;
		left = horizontalStart(anchor, size.width);
		top = fitsBelow || !fitsAbove ? withinViewport(below, size.height, window.innerHeight) : above;
	}

	async function openMenu(): Promise<void> {
		$open = true;
		await tick();
		placeBelowOrAboveTrigger();
		if (panel) focusFirstIn(panel);
	}

	export function focusTrigger(): void {
		queueMicrotask(() => triggerButton?.focus());
	}

	export function close(restoreFocus = true): void {
		if (!$open) return;
		focusTriggerOnClose = restoreFocus;
		$open = false;
	}

	function toggle(): void {
		if ($open) close();
		else void openMenu();
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!$open || !panel) return;
		handleFocusTrapKeydown(panel, event);
	}

	function onWindowResize(): void {
		if ($open) placeBelowOrAboveTrigger();
	}
</script>

<svelte:window onkeydown={onWindowKeydown} onresize={onWindowResize} />

<button
	bind:this={triggerButton}
	class="menu-trigger"
	data-hitbox="frequent"
	aria-haspopup="dialog"
	aria-expanded={$open}
	class:pressed
	aria-label={label}
	onclick={toggle}
>
	{@render trigger()}
</button>
{#if $open}
	<div class="menu-backdrop-layer">
		<button class="menu-backdrop" tabindex="-1" onclick={() => close()} aria-label={closeLabel}
		></button>
	</div>
	<div
		bind:this={panel}
		class="menu-panel"
		role="dialog"
		aria-modal="true"
		aria-label={label}
		tabindex="-1"
		style:left="{left}px"
		style:top="{top}px"
	>
		{@render children()}
	</div>
{/if}

<style>
	.menu-trigger {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		padding: 0.4rem;
	}

	.menu-trigger:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.menu-trigger[aria-expanded='true'],
	.menu-trigger.pressed {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
	}

	.menu-backdrop-layer {
		position: fixed;
		inset: 0;
		z-index: 300;
	}

	.menu-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: none;
		cursor: default;
	}

	.menu-panel {
		position: fixed;
		display: flex;
		flex-direction: column;
		gap: 2px;
		width: 238px;
		max-width: calc(100vw - 16px);
		max-height: calc(100dvh - 16px);
		overflow-y: auto;
		padding: 0.5rem;
		background: var(--header-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		z-index: 301;
	}
</style>
