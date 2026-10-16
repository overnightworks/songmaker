<script lang="ts">
	import type { ComponentProps } from 'svelte';
	import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '$lib/constants';
	import Icon from './Icon.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	type Props = Omit<ComponentProps<typeof LibraryTileContent>, 'presentation'> & {
		openLabel: string;
		onopen: () => void;
		onplay?: () => void;
		playing?: boolean;
	};
	let { openLabel, onopen, onplay, playing = false, ...content }: Props = $props();
</script>

<div class="library-row">
	<button type="button" class="wall-tile-body" aria-label={openLabel} onclick={onopen}>
		<LibraryTileContent {...content} presentation="row" />
	</button>
	{#if onplay}
		<button
			type="button"
			class="row-play"
			aria-label={`${playing ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL} ${content.title}`}
			onclick={onplay}
		>
			<Icon name={playing ? 'pause' : 'play'} size={20} />
		</button>
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
	.row-play {
		display: grid;
		place-items: center;
		flex: none;
		width: 44px;
		height: 44px;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--text);
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
