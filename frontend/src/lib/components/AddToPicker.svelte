<script lang="ts">
	import { onMount } from 'svelte';
	import {
		createNewPlaylist,
		ensurePlaylistsLoaded,
		loadPlaylists,
		playlistList,
		playlistLoad
	} from '#lib/stores/playlists.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';
	import PlaylistCover from './PlaylistCover.svelte';

	interface Props {
		/** Adds to the playlist the person chose or just created; the host closes its popover. */
		onselect: (playlistId: string) => void;
		/** Returns to the menu's own rows. */
		onback: () => void;
	}

	let { onselect, onback }: Props = $props();

	let backButton: HTMLButtonElement | undefined = $state();
	let newTitle = $state('');
	let creating = $state(false);

	const playlists = $derived($playlistList);
	const load = $derived($playlistLoad);

	onMount(() => {
		backButton?.focus();
		void ensurePlaylistsLoaded();
	});

	async function createAndSelect(): Promise<void> {
		const title = newTitle.trim();
		if (!title || creating) return;
		creating = true;
		try {
			const playlist = await createNewPlaylist(title);
			newTitle = '';
			onselect(playlist.id);
		} catch {
			addToast(pageText('addToPicker.createFailed'), 'error');
		} finally {
			creating = false;
		}
	}
</script>

<div class="ap-head">
	<button
		bind:this={backButton}
		type="button"
		class="ap-back"
		aria-label={pageText('addToPicker.back')}
		onclick={onback}
	>
		<Icon name="chevron-right" size={16} class="ap-back-icon" />
	</button>
	{pageText('addToPicker.heading')}
</div>

{#if load.status === 'loading' && playlists.length === 0}
	<p class="ap-status" role="status">{pageText('addToPicker.loading')}</p>
{:else if load.status === 'error' && playlists.length === 0}
	<p class="ap-status" role="alert">{load.error || pageText('addToPicker.error')}</p>
	<button type="button" class="ap-retry" onclick={() => loadPlaylists()}>
		{pageText('addToPicker.retry')}
	</button>
{:else}
	<ul class="ap-list">
		{#each playlists as playlist (playlist.id)}
			<li>
				<button type="button" class="ap-row" onclick={() => onselect(playlist.id)}>
					<PlaylistCover
						title={playlist.title}
						covers={playlist.album_covers}
						cover={playlist.cover}
						size="28px"
					/>
					<span class="ap-title">{playlist.title}</span>
					<span class="ap-count">{playlist.entry_count}</span>
				</button>
			</li>
		{/each}
	</ul>
	{#if load.status === 'error'}
		<p class="ap-status" role="alert">{load.error || pageText('addToPicker.error')}</p>
		<button type="button" class="ap-retry" onclick={() => loadPlaylists()}>
			{pageText('addToPicker.retry')}
		</button>
	{/if}
{/if}
<div class="ap-create">
	<input
		class="ap-input"
		type="text"
		aria-label={pageText('addToPicker.newPlaceholder')}
		placeholder={pageText('addToPicker.newPlaceholder')}
		bind:value={newTitle}
		onkeydown={(event) => {
			if (event.key === 'Enter') void createAndSelect();
		}}
	/>
	<button
		type="button"
		class="ap-add"
		data-hitbox="frequent"
		data-hitbox-face
		onclick={() => void createAndSelect()}
		disabled={creating || !newTitle.trim()}
		aria-label={pageText('addToPicker.add')}
	>
		+
	</button>
</div>

<style>
	.ap-head {
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

	.ap-back {
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

	.ap-back:hover {
		background: var(--surface-hover);
	}

	.ap-back :global(.ap-back-icon) {
		transform: rotate(180deg);
	}

	.ap-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
		max-height: 268px;
		overflow-y: auto;
	}

	.ap-row {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: var(--hitbox-frequent);
		padding: 0 0.6rem;
		border: none;
		border-radius: var(--btn-radius-sm);
		background: none;
		font: inherit;
		font-size: var(--label-font-size);
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}

	.ap-row:hover {
		background: var(--surface-hover);
	}

	.ap-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ap-count {
		flex: none;
		min-width: 16px;
		font-size: 0.75rem;
		color: var(--text-subtle);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.ap-status {
		margin: 0;
		padding: 0.6rem;
		font-size: var(--label-font-size);
		color: var(--text-subtle);
	}

	.ap-retry {
		align-self: flex-start;
		margin: 0 0.6rem 0.4rem;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--accent);
		color: var(--accent);
		font: inherit;
		font-size: 0.75rem;
		cursor: pointer;
	}

	.ap-create {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-top: 4px;
		padding-top: 6px;
		border-top: 1px solid var(--border);
	}

	.ap-input {
		flex: 1;
		min-width: 0;
		min-height: var(--hitbox-frequent);
		padding: 0 0.6rem;
		font: inherit;
		font-size: var(--label-font-size);
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
	}

	.ap-input:focus {
		border-color: var(--accent);
		outline: none;
	}

	.ap-add {
		color: var(--text-muted);
		font-size: var(--label-font-size);
		line-height: 1;
	}

	.ap-add:hover:not(:disabled) {
		color: var(--accent);
	}

	.ap-add:disabled {
		opacity: 0.3;
	}
</style>
