<script module lang="ts">
	// One models fetch per page load, not per mount. The `(library)` route
	// group mounts this component exactly once for as long as the browser
	// stays on any of the three library addresses (issue #276); this guard
	// only matters for the boundary it does still cross — leaving the library
	// entirely (Settings, sign-out) and coming back unmounts and remounts it,
	// and that return must not re-fetch, nor flash the Loading gate over a
	// library that is already on screen. The live stream needs no such flag —
	// its own store is session state, and routes/+layout.svelte owns its
	// lifetime.
	let activeModelsLoaded = false;
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { albumList } from '$lib/stores/libraryData';
	import { selectedSong } from '$lib/stores/player';
	import { librarySurface } from '$lib/stores/libraryContext';
	import { openCollection } from '$lib/stores/collection';
	import { loadActiveModels } from '$lib/stores/presets';
	import { resourceSync, retryResourceSync } from '$lib/stores/resourceSync';
	import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '$lib/constants';
	import LibraryWall from './LibraryWall.svelte';
	import CreateForm from './CreateForm.svelte';
	import SongDetailView from './SongDetailView.svelte';
	import AlbumDetailView from './AlbumDetailView.svelte';
	import PlaylistDetailView from './PlaylistDetailView.svelte';
	import ToastContainer from './ToastContainer.svelte';

	let modelsReady = $state(activeModelsLoaded);

	const song = $derived($selectedSong);
	const surface = $derived($librarySurface);
	const collection = $derived($openCollection);
	const sync = $derived($resourceSync);

	// The live stream's own state is the gate, rather than a promise resolved
	// once per mount. `ready` turns true when the first snapshot has landed and
	// stays true while a later error is only a banner over a workspace that
	// already works — so a mount that finds the stream already live (returning
	// to the library after leaving it) shows the library at once, and no mount
	// depends on being ordered after the layout that starts the stream.
	const workspaceReady = $derived(sync.ready && modelsReady);
	const bootstrapFailed = $derived(!sync.ready && sync.status === 'error');

	onMount(() => {
		if (!activeModelsLoaded) void loadModels();
	});

	async function loadModels(): Promise<void> {
		await loadActiveModels();
		activeModelsLoaded = true;
		modelsReady = true;
	}

	function retryLoad(): Promise<boolean> {
		return retryResourceSync();
	}
</script>

{#if bootstrapFailed}
	<div class="error" role="alert">
		<p>{sync.error || RESOURCE_SYNC_ERROR}</p>
		<button class="retry-btn" onclick={() => void retryLoad()}>{LIBRARY_RETRY_LABEL}</button>
	</div>
{:else if !workspaceReady}
	<div class="loading">Loading...</div>
{:else}
	<div class="library-root">
		{#if sync.status === 'error' && sync.error}
			<div class="sync-status" role="alert">
				<p>{sync.error}</p>
				<button class="retry-btn" onclick={() => void retryLoad()}>{LIBRARY_RETRY_LABEL}</button>
			</div>
		{/if}
		<main class="main">
			{#if song}
				<SongDetailView />
			{:else if surface === 'create'}
				<CreateForm albums={$albumList} />
			{:else if surface === 'detail' && collection?.kind === 'album'}
				<AlbumDetailView albumId={collection.id} />
			{:else if surface === 'detail' && collection?.kind === 'playlist'}
				<PlaylistDetailView />
			{:else}
				<LibraryWall />
			{/if}
		</main>
	</div>
{/if}

<ToastContainer />

<style>
	.library-root {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
		min-height: 0;
	}

	.main {
		flex: 1;
		width: 100%;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow-y: auto;
		overflow-x: hidden;
	}

	.loading,
	.error,
	.sync-status {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--text-muted);
		font-style: italic;
		flex-direction: column;
		gap: 16px;
	}

	.error,
	.sync-status {
		color: var(--score-bad);
	}

	.sync-status {
		flex: 0;
		padding: 12px 16px;
	}

	.retry-btn {
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}
</style>
