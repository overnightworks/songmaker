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
	import MenuPickerHead from './MenuPickerHead.svelte';
	import PlaylistCover from './PlaylistCover.svelte';

	interface Props {
		/** Adds to the playlist the person chose or just created; the host closes its popover. */
		onselect: (playlistId: string) => void;
		/** Returns to the menu's own rows. */
		onback: () => void;
		/** A playlist's own Add to… leaves that playlist out of the choices. */
		excludePlaylistId?: string;
	}

	let { onselect, onback, excludePlaylistId }: Props = $props();

	let newTitle = $state('');
	let creating = $state(false);

	const playlists = $derived($playlistList.filter((playlist) => playlist.id !== excludePlaylistId));
	const load = $derived($playlistLoad);

	onMount(() => {
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

<MenuPickerHead
	label={pageText('addToPicker.back')}
	heading={pageText('addToPicker.heading')}
	{onback}
/>

{#if load.status === 'loading' && playlists.length === 0}
	<p class="ap-status" role="status">{pageText('addToPicker.loading')}</p>
{:else if load.status === 'error' && playlists.length === 0}
	<p class="ap-status" role="alert">{load.error || pageText('addToPicker.error')}</p>
	<button type="button" class="ap-retry" onclick={() => loadPlaylists()}>
		{pageText('addToPicker.retry')}
	</button>
{:else}
	<ul class="menu-picker-list">
		{#each playlists as playlist (playlist.id)}
			<li>
				<button type="button" class="menu-picker-row" onclick={() => onselect(playlist.id)}>
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
