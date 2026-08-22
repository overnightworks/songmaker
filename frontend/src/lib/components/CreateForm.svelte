<script lang="ts">
	import { fetchAlbums, createAlbum, createSong } from '$lib/api/client';
	import { albumList, addSongToList } from '$lib/stores/player';
	import { openWriteTab, selectSong } from '$lib/stores/navigation';
	import { addToast } from '$lib/stores/toast';
	import type { AlbumItem } from '$lib/api/types';

	interface Props {
		albums: AlbumItem[];
	}

	let { albums }: Props = $props();

	let newTitle = $state('');
	let newAlbumId = $state('');
	let newAlbumTitle = $state('');
	let newAlbumArtist = $state('');
	let creating = $state(false);
	let creatingAlbum = $state(false);

	async function handleCreateAlbum(): Promise<void> {
		if (!newAlbumTitle.trim()) return;
		creatingAlbum = true;
		try {
			const album = await createAlbum(newAlbumTitle.trim(), newAlbumArtist.trim());
			albumList.set((await fetchAlbums()).items);
			newAlbumId = album.id;
			newAlbumTitle = '';
			newAlbumArtist = '';
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Album creation failed', 'error');
		} finally {
			creatingAlbum = false;
		}
	}

	async function handleCreateSong(): Promise<void> {
		if (!newTitle.trim() || !newAlbumId) return;
		creating = true;
		try {
			const created = await createSong({
				title: newTitle,
				album_id: newAlbumId
			});
			addSongToList(created);
			selectSong(created.id);
			openWriteTab();
			newTitle = '';
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Create failed', 'error');
		} finally {
			creating = false;
		}
	}
</script>

<div class="create-panel">
	<div class="create-header">
		<h2>Create</h2>
	</div>

	<div class="create-section">
		<h3>New Album</h3>
		<div class="create-fields">
			<input type="text" bind:value={newAlbumTitle} placeholder="Album title" />
			<input type="text" bind:value={newAlbumArtist} placeholder="Artist (optional)" />
			<button onclick={handleCreateAlbum} disabled={creatingAlbum || !newAlbumTitle.trim()}>
				{creatingAlbum ? 'Creating...' : 'Create'}
			</button>
		</div>
	</div>

	<div class="create-section">
		<h3>New Song</h3>
		<div class="create-fields">
			<input type="text" bind:value={newTitle} placeholder="Song title" />
			<select bind:value={newAlbumId}>
				<option value="">Select album</option>
				{#each albums as a (a.id)}
					<option value={a.id}>{a.title}</option>
				{/each}
			</select>
			<button onclick={handleCreateSong} disabled={creating || !newTitle.trim() || !newAlbumId}>
				{creating ? 'Creating...' : 'Create'}
			</button>
		</div>
	</div>
</div>

<style>
	.create-panel {
		padding: 20px;
		max-width: 600px;
	}

	.create-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 16px;
	}

	.create-header h2 {
		font-family: var(--font-display);
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.33rem;
		margin: 0;
		text-transform: uppercase;
	}

	.create-section {
		margin-bottom: 16px;
	}

	.create-section h3 {
		font-family: var(--font-display);
		color: var(--text-muted);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin: 0 0 8px;
	}

	.create-fields {
		display: flex;
		gap: 8px;
	}

	.create-fields input,
	.create-fields select {
		flex: 1;
		padding: var(--input-padding);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		font-size: 0.87rem;
	}

	.create-fields input:focus,
	.create-fields select:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.create-fields button {
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		cursor: pointer;
		white-space: nowrap;
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		transition: box-shadow 0.2s;
	}

	.create-fields button:hover:not(:disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
	}

	.create-fields button:disabled {
		opacity: 0.4;
	}

	@media (max-width: 768px) {
		.create-fields {
			flex-direction: column;
		}

		.create-fields button {
			align-self: flex-start;
		}
	}
</style>
