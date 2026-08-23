<script lang="ts">
	import type { SongItem, VersionItem } from '$lib/api/types';

	type MentionItem =
		{ type: 'album' } | { type: 'version'; item: VersionItem } | { type: 'song'; item: SongItem };

	interface Props {
		items: MentionItem[];
		selectedIndex: number;
		albumTitle: string;
		loading?: boolean;
		onselect: (item: MentionItem) => void;
	}

	let { items, selectedIndex, albumTitle, loading = false, onselect }: Props = $props();
</script>

<div class="mention-dropdown">
	{#if loading}
		<div class="mention-empty">Loading catalog...</div>
	{:else if items.length === 0}
		<div class="mention-empty">No matches</div>
	{/if}
	{#each items as result, idx (idx)}
		<button
			class="mention-option"
			class:selected={idx === selectedIndex}
			onclick={() => onselect(result)}
		>
			{#if result.type === 'album'}
				<span class="mention-title">@album</span>
				<span class="mention-album">{albumTitle}</span>
			{:else if result.type === 'version'}
				<span class="mention-title">@v{result.item.version_number}</span>
				<span class="mention-album">
					{result.item.created_at ? new Date(result.item.created_at).toLocaleDateString() : ''}
					{result.item.prompt ? `· ${result.item.prompt.slice(0, 40)}` : ''}
				</span>
			{:else}
				<span class="mention-title">{result.item.title}</span>
				<span class="mention-album">{result.item.album_title}</span>
			{/if}
		</button>
	{/each}
</div>

<style>
	.mention-dropdown {
		position: absolute;
		bottom: 100%;
		left: 8px;
		right: 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		max-height: 200px;
		overflow-y: auto;
		box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.3);
		z-index: 10;
	}

	.mention-option {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 6px 12px;
		background: none;
		border: none;
		color: var(--text);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.mention-option:hover,
	.mention-option.selected {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.mention-title {
		font-weight: 500;
	}

	.mention-album {
		font-size: 10px;
		opacity: 0.6;
	}

	.mention-empty {
		padding: 8px 12px;
		font-size: 12px;
		color: var(--text-subtle);
	}
</style>
