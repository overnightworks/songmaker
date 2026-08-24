<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { albumList } from '$lib/stores/libraryData';
	import { selectedSong } from '$lib/stores/player';
	import { librarySurface } from '$lib/stores/libraryContext';
	import { initNavigation, openLibraryCreate } from '$lib/stores/navigation';
	import { openCollection } from '$lib/stores/collection';
	import { loadActiveModels } from '$lib/stores/presets';
	import {
		resourceSync,
		retryResourceSync,
		startLibraryResourceSync,
		stopLibraryResourceSync,
		waitForResourceReady
	} from '$lib/stores/resourceSync';
	import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '$lib/constants';
	import LibraryWall from '$lib/components/LibraryWall.svelte';
	import CreateForm from '$lib/components/CreateForm.svelte';
	import SongDetailView from '$lib/components/SongDetailView.svelte';
	import AlbumDetailView from '$lib/components/AlbumDetailView.svelte';
	import PlaylistDetailView from '$lib/components/PlaylistDetailView.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';

	let loading = $state(true);
	let workspaceReady = $state(false);
	let bootstrapError = $state<string | null>(null);
	let navCleanup: (() => void) | undefined;

	const song = $derived($selectedSong);
	const surface = $derived($librarySurface);
	const collection = $derived($openCollection);
	const sync = $derived($resourceSync);

	onMount(() => {
		startLibraryResourceSync();
		void bootstrapLibrary().then((ok) => {
			if (ok && !navCleanup) navCleanup = initNavigation();
		});
		return () => {
			stopLibraryResourceSync();
			navCleanup?.();
		};
	});

	async function bootstrapLibrary(): Promise<boolean> {
		loading = true;
		bootstrapError = null;
		try {
			const [syncOk] = await Promise.all([waitForResourceReady(), loadActiveModels()]);
			if (!syncOk) {
				bootstrapError = get(resourceSync).error || RESOURCE_SYNC_ERROR;
				return false;
			}
			workspaceReady = true;
			return true;
		} catch (e) {
			bootstrapError = e instanceof Error ? e.message : RESOURCE_SYNC_ERROR;
			return false;
		} finally {
			loading = false;
		}
	}

	async function retryLoad(): Promise<void> {
		if (!workspaceReady) loading = true;
		try {
			const ok = await retryResourceSync();
			if (ok) {
				workspaceReady = true;
				bootstrapError = null;
				if (!navCleanup) navCleanup = initNavigation();
				return;
			}
			bootstrapError = get(resourceSync).error || RESOURCE_SYNC_ERROR;
		} catch (e) {
			bootstrapError = e instanceof Error ? e.message : RESOURCE_SYNC_ERROR;
		} finally {
			loading = false;
		}
	}
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if !workspaceReady}
	<div class="error" role="alert">
		<p>{bootstrapError || RESOURCE_SYNC_ERROR}</p>
		<button class="retry-btn" onclick={() => retryLoad()}>{LIBRARY_RETRY_LABEL}</button>
	</div>
{:else}
	<div class="library-root">
		{#if sync.status === 'error' && sync.error}
			<div class="sync-status" role="alert">
				<p>{sync.error}</p>
				<button class="retry-btn" onclick={() => retryLoad()}>{LIBRARY_RETRY_LABEL}</button>
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
				<LibraryWall oncreate={openLibraryCreate} />
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
