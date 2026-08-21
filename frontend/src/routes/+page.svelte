<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { albumList, selectedSong, selectedAlbumId } from '$lib/stores/player';
	import { librarySurface } from '$lib/stores/libraryContext';
	import { goBack, initNavigation, openLibraryCreate } from '$lib/stores/navigation';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { loadActiveModels } from '$lib/stores/presets';
	import {
		resourceSync,
		retryResourceSync,
		startLibraryResourceSync,
		stopLibraryResourceSync,
		waitForResourceReady
	} from '$lib/stores/resourceSync';
	import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '$lib/constants';
	import SongList from '$lib/components/SongList.svelte';
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
	const currentAlbumId = $derived($selectedAlbumId);
	const albums = $derived($albumList);
	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const playlistDetail = $derived($selectedPlaylistDetail);
	const hasSelection = $derived(!!song || !!selectedAlbum || !!playlistDetail);
	const hasDetail = $derived(
		$librarySurface === 'create' || ($librarySurface === 'detail' && hasSelection)
	);
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
		<div class="workspace" class:has-detail={hasDetail}>
			<SongList
				onNewSong={() => {
					if ($librarySurface === 'create') goBack();
					else openLibraryCreate();
				}}
			/>

			<main class="detail-panel">
				{#if $librarySurface === 'create'}
					<CreateForm albums={$albumList} />
				{:else if song}
					<SongDetailView />
				{:else if selectedAlbum}
					<AlbumDetailView />
				{:else if playlistDetail}
					<PlaylistDetailView />
				{/if}
			</main>
		</div>
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

	.workspace {
		display: grid;
		flex: 1;
		width: 100%;
		min-width: 0;
		min-height: 0;
		overflow-x: hidden;
		grid-template-columns: 260px minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr);
		grid-template-areas: 'nav browse';
	}

	.workspace.has-detail {
		grid-template-areas: 'nav detail';
	}

	.workspace > :global(.library-nav) {
		grid-area: nav;
		min-width: 0;
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		border-right: 1px solid var(--border);
		background-image:
			linear-gradient(rgba(160, 32, 240, 0.02) 1px, transparent 1px),
			linear-gradient(90deg, rgba(160, 32, 240, 0.02) 1px, transparent 1px);
		background-size: 40px 40px;
	}

	.workspace > :global(.library-browse) {
		grid-area: browse;
		min-width: 0;
		min-height: 0;
	}

	.workspace.has-detail > :global(.library-browse) {
		display: none;
	}

	.detail-panel {
		grid-area: detail;
		display: none;
		min-width: 0;
		min-height: 0;
		overflow-y: auto;
		overflow-x: hidden;
		flex-direction: column;
	}

	.workspace.has-detail > .detail-panel {
		display: flex;
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

	@media (max-width: 768px) {
		.workspace {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: auto minmax(0, 1fr);
			grid-template-areas:
				'nav'
				'browse';
		}

		.workspace > :global(.library-nav) {
			border-right: none;
			border-bottom: 1px solid var(--border);
		}

		.workspace.has-detail {
			grid-template-rows: minmax(0, 1fr);
			grid-template-areas: 'detail';
		}

		.workspace.has-detail > :global(.library-nav),
		.workspace.has-detail > :global(.library-browse) {
			display: none;
		}
	}
</style>
