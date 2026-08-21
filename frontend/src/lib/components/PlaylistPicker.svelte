<script lang="ts">
	import { onMount } from 'svelte';
	import {
		createNewPlaylist,
		ensurePlaylistsLoaded,
		loadPlaylists,
		playlistList,
		playlistLoad
	} from '$lib/stores/playlists';
	import { addToast } from '$lib/stores/toast';
	import {
		LIBRARY_PLAYLISTS_ERROR,
		LIBRARY_PLAYLISTS_LOADING,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';

	interface Props {
		onselect: (playlistId: string) => void;
		onclose: () => void;
	}

	let { onselect, onclose }: Props = $props();
	let menuRef = $state<HTMLDivElement | null>(null);
	let newTitle = $state('');
	let creating = $state(false);

	const playlists = $derived($playlistList);
	const load = $derived($playlistLoad);

	onMount(() => {
		void ensurePlaylistsLoaded();
	});

	function handleClickOutside(event: MouseEvent): void {
		if (menuRef && !menuRef.contains(event.target as Node)) {
			onclose();
		}
	}

	$effect(() => {
		document.addEventListener('click', handleClickOutside, true);
		return () => document.removeEventListener('click', handleClickOutside, true);
	});

	async function handleCreate(): Promise<void> {
		if (!newTitle.trim()) return;
		creating = true;
		try {
			const playlist = await createNewPlaylist(newTitle.trim());
			newTitle = '';
			onselect(playlist.id);
		} catch {
			addToast('Failed to create playlist', 'error');
		} finally {
			creating = false;
		}
	}
</script>

<div class="picker" bind:this={menuRef}>
	<div class="picker-header">Add to Playlist</div>
	<div class="picker-list">
		{#if load.status === 'loading' && playlists.length === 0}
			<p class="picker-status" role="status">{LIBRARY_PLAYLISTS_LOADING}</p>
		{:else if load.status === 'error' && playlists.length === 0}
			<p class="picker-status" role="alert">{load.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="picker-retry" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{:else}
			{#each playlists as p (p.id)}
				<button class="picker-item" onclick={() => onselect(p.id)}>
					<span class="picker-title">{p.title}</span>
					<span class="picker-count">{p.entry_count}</span>
				</button>
			{/each}
		{/if}
		{#if load.status === 'error' && playlists.length > 0}
			<p class="picker-status" role="alert">{load.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="picker-retry" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{/if}
	</div>
	<div class="picker-create">
		<input
			class="picker-input"
			type="text"
			placeholder="New playlist..."
			bind:value={newTitle}
			onkeydown={(e) => {
				if (e.key === 'Enter') handleCreate();
			}}
		/>
		<button
			class="picker-add"
			data-hitbox="frequent"
			data-hitbox-face
			onclick={handleCreate}
			disabled={creating || !newTitle.trim()}
			aria-label="Add playlist"
		>
			+
		</button>
	</div>
</div>

<style>
	.picker {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 4px;
		min-width: 200px;
		max-height: 300px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
		z-index: 100;
		display: flex;
		flex-direction: column;
	}

	.picker-header {
		padding: 8px 12px;
		font-size: 10px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		color: var(--text-muted);
		border-bottom: 1px solid var(--border);
	}

	.picker-list {
		overflow-y: auto;
		max-height: 200px;
	}

	.picker-status {
		margin: 0;
		padding: 8px 12px;
		font-size: 12px;
		color: var(--text-muted);
	}

	.picker-retry {
		margin: 0 12px 8px;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--border);
		color: var(--text);
		font-size: 11px;
		cursor: pointer;
	}

	.picker-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 8px 12px;
		background: none;
		border: none;
		color: var(--text-light);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.picker-item:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.picker-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.picker-count {
		font-size: 10px;
		color: var(--text-subtle);
		flex-shrink: 0;
		margin-left: 8px;
	}

	.picker-create {
		display: flex;
		gap: 4px;
		padding: 6px 8px;
		border-top: 1px solid var(--border);
	}

	.picker-input {
		flex: 1;
		padding: 4px 8px;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text);
		font-size: 11px;
		outline: none;
		min-width: 0;
	}

	.picker-input:focus {
		border-color: var(--accent);
	}

	.picker-add {
		color: var(--text-muted);
		font-size: 14px;
		line-height: 1;
	}

	.picker-add:hover:not(:disabled) {
		color: var(--primary);
	}

	.picker-add:disabled {
		opacity: 0.3;
	}
</style>
