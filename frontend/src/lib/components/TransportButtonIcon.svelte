<script lang="ts">
	import Icon from './Icon.svelte';
	import type { TransportButtonFace } from '#lib/services/audioPlayer.svelte.ts';

	interface Props {
		/** The face `transportButtonFace` chose for the transport this button acts on. */
		face: TransportButtonFace;
		size: number;
	}

	let { face, size }: Props = $props();
</script>

{#if face === 'spinner'}<span class="spinner" style:width="{size}px" style:height="{size}px"
	></span>{:else}<Icon name={face} {size} />{/if}

<style>
	.spinner {
		display: inline-block;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
