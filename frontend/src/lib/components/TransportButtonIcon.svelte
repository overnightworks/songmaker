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

{#if face === 'spinner'}<span
		class="spinner ring-turn"
		style:width="{size}px"
		style:height="{size}px"
	></span>{:else}<Icon name={face} {size} />{/if}

<style>
	.spinner {
		display: inline-block;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		--ring-turn: 0.8s;
	}
</style>
