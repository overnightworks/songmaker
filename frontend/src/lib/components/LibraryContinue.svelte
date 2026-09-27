<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchLibraryContinue, type LibraryContinueItem } from '$lib/api/library';
	import { openAlbum, openPlaylist, selectSong } from '$lib/stores/navigation';
	import {
		initLibraryContinueCollapsed,
		libraryContinueCollapsed,
		toggleLibraryContinueCollapsed
	} from '$lib/stores/ui';
	import { activityTimeLabel } from '$lib/utils/format';
	import LibraryTileContent from './LibraryTileContent.svelte';

	const MAX_CONTINUE_ITEMS = 6;

	type LoadState = 'loading' | 'ready' | 'error';

	let items = $state<LibraryContinueItem[]>([]);
	let loadState = $state<LoadState>('loading');
	let loadedAt = $state(new Date());

	const visibleItems = $derived(items.slice(0, MAX_CONTINUE_ITEMS));

	let inflightRefresh: Promise<void> | null = null;

	onMount(() => {
		initLibraryContinueCollapsed();
		void refreshItems();
	});

	// Continue ranks what the musician touched last, so it is never cached
	// beyond one visit: every show of Home and every return to the foreground
	// asks the server again, and a signal that repeats mid-request joins it.
	function refreshItems(): Promise<void> {
		inflightRefresh ??= fetchItems().finally(() => (inflightRefresh = null));
		return inflightRefresh;
	}

	// A list already on screen stays when a refresh fails (#1039): the phone may
	// wake before its network does, and the offline notice owns saying so. Only
	// a Home that never had a list names the failure and offers Retry.
	async function fetchItems(): Promise<void> {
		if (loadState === 'error') loadState = 'loading';
		try {
			items = (await fetchLibraryContinue()).items;
			loadedAt = new Date();
			loadState = 'ready';
		} catch {
			if (loadState !== 'ready') loadState = 'error';
		}
	}

	function refreshOnReturnToForeground(): void {
		if (document.visibilityState === 'visible') void refreshItems();
	}

	function songOf(item: LibraryContinueItem): { id: string; title: string } | null {
		return item.song_id ? { id: item.song_id, title: item.song_title ?? '' } : null;
	}

	function itemLabel(item: LibraryContinueItem): string {
		const song = songOf(item);
		return song
			? `Open song ${song.title} in ${item.type} ${item.title}`
			: `Open ${item.type} ${item.title}`;
	}

	function openItem(item: LibraryContinueItem): void {
		const song = songOf(item);
		if (song) void selectSong(song.id);
		else if (item.type === 'album') void openAlbum(item.id);
		else void openPlaylist(item.id);
	}
</script>

<svelte:document onvisibilitychange={refreshOnReturnToForeground} />

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
				<button type="button" class="continue-retry" onclick={() => void refreshItems()}
					>Retry</button
				>
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
						aria-label={itemLabel(item)}
					>
						<LibraryTileContent
							title={item.title}
							subtitle={songOf(item)?.title ?? ''}
							coverAlt={`${item.type} cover for ${item.title}`}
							coverUrl={item.cover?.card ?? null}
							playlistCovers={item.type === 'playlist' ? item.album_covers : null}
						/>
						<time class="continue-when" datetime={item.activity_at}
							>{activityTimeLabel(item.activity_at, loadedAt)}</time
						>
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
		display: grid;
		grid-template-columns: 56px minmax(0, 1fr);
		grid-template-rows: auto auto;
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
		grid-row: 1 / span 2;
		width: 56px;
		border-radius: 3px;
	}

	.continue-item :global(.tile-meta) {
		align-self: end;
		padding: 0 8px;
	}

	.continue-item :global(.tile-title) {
		font-size: 0.78rem;
	}

	.continue-item :global(.tile-subtitle) {
		color: var(--text-muted);
		font-size: 0.7rem;
	}

	.continue-when {
		align-self: start;
		min-width: 0;
		overflow: hidden;
		padding: 1px 8px 0;
		color: var(--text-subtle);
		font-size: 0.64rem;
		text-overflow: ellipsis;
		white-space: nowrap;
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

		.continue-item {
			grid-template-columns: 44px minmax(0, 1fr);
			min-height: 58px;
		}

		.continue-item :global(.tile-cover) {
			width: 44px;
		}
	}
</style>
