<script lang="ts">
	import type { ComponentProps } from 'svelte';
	import {
		transportButtonFace,
		transportButtonLabel,
		type TransportState
	} from '$lib/services/audioPlayer.svelte';
	import TransportButtonIcon from './TransportButtonIcon.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	type Props = Omit<ComponentProps<typeof LibraryTileContent>, 'presentation'> & {
		openLabel: string;
		onopen: () => void;
		onplay?: () => void;
		transport?: TransportState;
		selected?: boolean;
	};
	let {
		openLabel,
		onopen,
		onplay,
		transport = 'idle',
		selected = false,
		...content
	}: Props = $props();
</script>

<div class="wall-tile library-row" class:selected>
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
