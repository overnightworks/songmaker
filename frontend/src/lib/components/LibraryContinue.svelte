<script lang="ts">
	import { onMount } from 'svelte';
	import type { LibraryContinueItem } from '$lib/api/library';
	import { loadLibraryContinueItems } from '$lib/stores/libraryData';
	import { openAlbum, selectSong } from '$lib/stores/navigation';
	import {
		initLibraryContinueCollapsed,
		libraryContinueCollapsed,
		toggleLibraryContinueCollapsed
	} from '$lib/stores/ui';
	import LibraryTileContent from './LibraryTileContent.svelte';

	const MAX_CONTINUE_ITEMS = 6;

	type LoadState = 'loading' | 'ready' | 'error';

	let items = $state<LibraryContinueItem[]>([]);
	let loadState = $state<LoadState>('loading');

	const visibleItems = $derived(items.slice(0, MAX_CONTINUE_ITEMS));

	onMount(() => {
		initLibraryContinueCollapsed();
		void loadItems();
	});

	async function loadItems(): Promise<void> {
		loadState = 'loading';
		try {
			items = await loadLibraryContinueItems();
			loadState = 'ready';
		} catch {
			loadState = 'error';
		}
	}

	function itemSubtitle(item: LibraryContinueItem): string {
		return item.type === 'song' && item.album_title
			? item.album_title
			: item.type === 'song'
				? 'Song'
				: 'Album';
	}

	function openItem(item: LibraryContinueItem): void {
		if (item.type === 'album') {
			void openAlbum(item.id);
			return;
		}
		void selectSong(item.id);
	}
</script>

<section class="library-continue" aria-label="Continue">
	<button
		type="button"
		class="continue-toggle"
		aria-expanded={!$libraryContinueCollapsed}
		onclick={toggleLibraryContinueCollapsed}
	>
		<span>Continue</span>
		<span class="continue-caret" aria-hidden="true">{$libraryContinueCollapsed ? '⌄' : '⌃'}</span>
	</button>

	{#if !$libraryContinueCollapsed}
		{#if loadState === 'loading'}
			<p class="continue-state" role="status">Loading continue items…</p>
		{:else if loadState === 'error'}
			<div class="continue-state" role="alert">
				<p>Could not load continue items.</p>
				<button type="button" class="continue-retry" onclick={() => void loadItems()}>Retry</button>
			</div>
		{:else if visibleItems.length === 0}
			<p class="continue-state">Nothing to continue yet.</p>
		{:else}
			<div class="continue-items">
				{#each visibleItems as item (item.type + item.id)}
					<button
						type="button"
						class="continue-item"
						onclick={() => openItem(item)}
						aria-label={`Open ${item.type} ${item.title}`}
					>
						<LibraryTileContent
							title={item.title}
							subtitle={itemSubtitle(item)}
							coverAlt={`${item.type} cover for ${item.title}`}
							coverUrl={item.cover?.card ?? null}
						/>
						<span class="continue-tag">{item.type === 'song' ? 'Song' : 'Album'}</span>
					</button>
				{/each}
			</div>
		{/if}
	{/if}
</section>

<style>
	.library-continue {
		padding: 0 20px 8px;
		flex-shrink: 0;
	}

	.continue-toggle {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 8px 0;
		border: 0;
		background: transparent;
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.9rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-align: left;
		text-transform: uppercase;
		cursor: pointer;
	}

	.continue-caret {
		color: var(--text-subtle);
		font-family: var(--font-body);
		font-size: 1rem;
	}

	.continue-items {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 8px;
	}

	.continue-item {
		position: relative;
		display: grid;
		grid-template-columns: 56px minmax(0, 1fr);
		align-items: center;
		min-width: 0;
		padding: 6px;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}

	.continue-item:hover,
	.continue-item:focus-visible {
		border-color: var(--primary);
		background: var(--surface-hover);
		outline: none;
	}

	.continue-item :global(.tile-cover) {
		width: 56px;
		border-radius: 3px;
	}

	.continue-item :global(.tile-meta) {
		padding: 0 22px 0 8px;
	}

	.continue-item :global(.tile-title) {
		font-size: 0.78rem;
	}

	.continue-item :global(.tile-subtitle) {
		font-size: 0.68rem;
	}

	.continue-tag {
		position: absolute;
		top: 6px;
		right: 6px;
		color: var(--text-subtle);
		font-size: 0.62rem;
		line-height: 1;
		text-transform: uppercase;
	}

	.continue-state {
		margin: 0;
		padding: 12px 0;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
	}

	.continue-state[role='alert'] {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.continue-state p {
		margin: 0;
	}

	.continue-retry {
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font: inherit;
		padding: 3px 8px;
		cursor: pointer;
	}

	.continue-retry:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	@media (max-width: 768px) {
		.library-continue {
			padding: 0 12px 6px;
		}

		.continue-items {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
