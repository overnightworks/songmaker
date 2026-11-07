<script lang="ts">
	import Icon from './Icon.svelte';

	interface Props {
		/** Names the button, e.g. what the tip explains. */
		label: string;
		/** The explanation, also the button's description. */
		text: string;
	}

	let { label, text }: Props = $props();

	const tipId = $props.id();
	let open = $state(false);
	let wrapper: HTMLSpanElement | undefined = $state();
	let button: HTMLButtonElement | undefined = $state();
	let tip: HTMLSpanElement | undefined = $state();

	const VIEWPORT_MARGIN_PX = 8;

	// The tip stays anchored to its button and shifts only as far as it must to
	// stay readable, whichever edge the button sits near.
	function shiftIntoViewport(): void {
		if (!tip) return;
		tip.style.transform = '';
		const box = tip.getBoundingClientRect();
		const overRight = box.right - (window.innerWidth - VIEWPORT_MARGIN_PX);
		const shiftX = Math.max(VIEWPORT_MARGIN_PX - box.left, -Math.max(overRight, 0));
		const shiftY = Math.max(VIEWPORT_MARGIN_PX - box.top, 0);
		tip.style.transform = `translate(${shiftX}px, ${shiftY}px)`;
	}

	$effect(() => {
		if (open) shiftIntoViewport();
	});

	function closeOnOutsidePress(event: PointerEvent): void {
		if (open && wrapper && !wrapper.contains(event.target as Node)) open = false;
	}

	function closeOnEscape(event: KeyboardEvent): void {
		if (event.key !== 'Escape' || !open) return;
		open = false;
		event.stopPropagation();
	}

	function closeWhenHoverEnds(): void {
		if (document.activeElement !== button) open = false;
	}
</script>

<svelte:window onpointerdown={closeOnOutsidePress} />

<span class="info-tip" bind:this={wrapper} onkeydown={closeOnEscape} role="presentation">
	<button
		type="button"
		class="info-tip-button"
		bind:this={button}
		aria-label={label}
		aria-describedby={tipId}
		aria-expanded={open}
		onmouseenter={() => (open = true)}
		onmouseleave={closeWhenHoverEnds}
		onfocus={() => (open = true)}
		onblur={() => (open = false)}
		onclick={() => (open = true)}
	>
		<Icon name="info" size={14} />
	</button>
	<span id={tipId} class="info-tip-text" role="tooltip" bind:this={tip} hidden={!open}>{text}</span>
</span>

<style>
	.info-tip {
		position: relative;
		display: inline-flex;
	}

	.info-tip-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0.5rem;
		border: 0;
		border-radius: var(--btn-radius-pill);
		background: none;
		color: var(--text-subtle);
		cursor: pointer;
	}

	.info-tip-button:hover,
	.info-tip-button[aria-expanded='true'] {
		color: var(--text-light);
	}

	.info-tip-button:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 0;
	}

	.info-tip-text {
		position: absolute;
		top: 100%;
		right: 0;
		z-index: 301;
		width: max-content;
		max-width: min(16rem, calc(100vw - 1rem));
		padding: var(--row-padding);
		background: var(--header-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		color: var(--text-light);
		font-size: var(--label-font-size);
	}

	.info-tip-text[hidden] {
		display: none;
	}
</style>
