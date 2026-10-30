<script module lang="ts">
	const LIGHT_UP_MS = 1200;
</script>

<script lang="ts">
	import { onMount, type ComponentProps } from 'svelte';
	import {
		transportButtonFace,
		transportButtonLabel,
		type TransportState
	} from '#lib/services/audioPlayer.svelte.ts';
	import Icon from './Icon.svelte';
	import TransportButtonIcon from './TransportButtonIcon.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	type Props = Omit<ComponentProps<typeof LibraryTileContent>, 'presentation'> & {
		openLabel: string;
		onopen: () => void;
		onplay?: () => void;
		// The caller names the place its trailing action opens; the row stays generic.
		edit?: { label: string; onclick: () => void };
		transport?: TransportState;
		selected?: boolean;
		lightUp?: boolean;
		onlit?: () => void;
	};
	let {
		openLabel,
		onopen,
		onplay,
		edit,
		transport = 'idle',
		selected = false,
		lightUp = false,
		onlit,
		...content
	}: Props = $props();

	let lit = $state(false);
	onMount(() => {
		if (!lightUp) return;
		lit = true;
		onlit?.();
		const settle = setTimeout(() => (lit = false), LIGHT_UP_MS);
		return () => clearTimeout(settle);
	});
</script>

<div
	class="wall-tile library-row"
	class:selected
	class:lit
	style:--light-up-ms={`${LIGHT_UP_MS}ms`}
>
	<button type="button" class="wall-tile-body" aria-label={openLabel} onclick={onopen}>
		<LibraryTileContent {...content} presentation="row" />
	</button>
	{#if onplay}
		<button
			type="button"
			class="row-play"
			aria-label={`${transportButtonLabel(transport)} ${content.title}`}
			onclick={onplay}
		>
			<TransportButtonIcon face={transportButtonFace(transport)} size={20} />
		</button>
	{:else if edit}
		<button type="button" class="row-editor" aria-label={edit.label} onclick={edit.onclick}>
			<Icon name="pencil" size={20} />
		</button>
	{:else}
		<span class="row-play-spacer" aria-hidden="true"></span>
	{/if}
</div>

<style>
	.library-row {
		display: flex;
		align-items: center;
		gap: 12px;
		height: 58px;
		min-width: 0;
		border-bottom: 1px solid var(--border);
	}
	.library-row.selected {
		box-shadow: var(--selected-ring);
	}
	.library-row.lit {
		animation: light-up var(--light-up-ms) ease-out;
	}
	@keyframes light-up {
		from {
			background: color-mix(in srgb, var(--accent) 30%, transparent);
		}
		to {
			background: transparent;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.library-row.lit {
			animation: none;
			background: color-mix(in srgb, var(--accent) 18%, transparent);
		}
	}
	.wall-tile-body {
		display: flex;
		align-items: center;
		gap: 12px;
		flex: 1;
		min-width: 0;
		height: 100%;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}
	.row-editor,
	.row-play,
	.row-play-spacer {
		display: grid;
		place-items: center;
		flex: none;
		width: 44px;
		height: 44px;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--text);
	}
	.row-editor,
	.row-play {
		cursor: pointer;
	}
	button:hover {
		background: var(--surface-hover);
	}
	button:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
</style>
