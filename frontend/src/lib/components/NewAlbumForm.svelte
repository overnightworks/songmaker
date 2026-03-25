<script lang="ts">
	import { fetchAlbums, createAlbum } from '$lib/api/client';
	import { albumList } from '$lib/stores/player';

	interface Props {
		onclose: () => void;
	}

	let { onclose }: Props = $props();

	let title = $state('');
	let artist = $state('');
	let creating = $state(false);
	let error = $state('');

	async function handleCreate(): Promise<void> {
		if (!title.trim()) return;
		creating = true;
		error = '';
		try {
			await createAlbum(title.trim(), artist.trim());
			const refreshed = await fetchAlbums();
			albumList.set(refreshed);
			onclose();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed';
		} finally {
			creating = false;
		}
	}
</script>

<div class="new-album-form">
	<input type="text" bind:value={title} placeholder="Album title" disabled={creating} />
	<input type="text" bind:value={artist} placeholder="Artist (optional)" disabled={creating} />
	<div class="new-album-actions">
		<button class="create-btn" onclick={handleCreate} disabled={creating || !title.trim()}>
			{creating ? 'Creating...' : 'Create Album'}
		</button>
		<button class="cancel-btn" onclick={onclose}>Cancel</button>
	</div>
	{#if error}<p class="album-error">{error}</p>{/if}
</div>

<style>
	.new-album-form {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex-shrink: 0;
	}

	.new-album-form input {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		width: 100%;
	}

	.new-album-form input:focus {
		border-color: var(--primary);
		outline: none;
	}

	.new-album-actions {
		display: flex;
		gap: 6px;
	}

	.create-btn {
		background: var(--primary);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 4px 10px;
		font-size: 11px;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.create-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.cancel-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 10px;
		font-size: 11px;
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-body);
	}

	.album-error {
		color: var(--score-bad);
		font-size: 11px;
	}
</style>
