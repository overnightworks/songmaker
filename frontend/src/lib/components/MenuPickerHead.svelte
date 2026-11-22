<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from './Icon.svelte';

	interface Props {
		/** Accessible name of the Back button. */
		label: string;
		heading: string;
		/** Returns to the menu's own rows. */
		onback: () => void;
		disabled?: boolean;
	}

	let { label, heading, onback, disabled = false }: Props = $props();

	let backButton: HTMLButtonElement | undefined = $state();

	onMount(() => backButton?.focus());
</script>

<div class="menu-picker-head">
	<button
		bind:this={backButton}
		type="button"
		class="menu-picker-back"
		aria-label={label}
		{disabled}
		onclick={onback}
	>
		<Icon name="chevron-right" size={16} class="menu-picker-back-icon" />
	</button>
	{heading}
</div>

<style>
	.menu-picker-head {
		display: flex;
		align-items: center;
		gap: 2px;
		margin-bottom: 0.25rem;
		padding: 0 0.6rem 0.3rem 0;
		border-bottom: 1px solid var(--border);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
	}

	.menu-picker-back {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		background: none;
		border: none;
		border-radius: var(--btn-radius-sm);
		color: var(--text);
		cursor: pointer;
	}

	.menu-picker-back:hover {
		background: var(--surface-hover);
	}

	.menu-picker-back :global(.menu-picker-back-icon) {
		transform: rotate(180deg);
	}
</style>
