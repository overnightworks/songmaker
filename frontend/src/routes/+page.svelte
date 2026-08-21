<script lang="ts">
	import { onMount } from 'svelte';
	import { albumList, selectedSong, selectedGeneration, selectedAlbumId } from '$lib/stores/player';
	import { hydrateLibraryFromHistory, librarySurface } from '$lib/stores/libraryContext';
	import {
		resourceSync,
		retryResourceSync,
		waitForResourceReady
	} from '$lib/stores/librarySearch';
	import { detailTab, goBack, initNavigation, openLibraryCreate } from '$lib/stores/navigation';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { loadActiveModels } from '$lib/stores/presets';
	import { addToast } from '$lib/stores/toast';
	import { LIBRARY_RETRY_LABEL, RESOURCE_SYNC_ERROR } from '$lib/constants';
	import SongList from '$lib/components/SongList.svelte';
	import CreateForm from '$lib/components/CreateForm.svelte';
	import SongDetailView from '$lib/components/SongDetailView.svelte';
	import GenerationView from '$lib/components/GenerationView.svelte';
	import AlbumDetailView from '$lib/components/AlbumDetailView.svelte';
	import PlaylistDetailView from '$lib/components/PlaylistDetailView.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';

	let loading = $state(true);
	let loadError = $state(false);
	let navCleanup: (() => void) | undefined;

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const currentAlbumId = $derived($selectedAlbumId);
	const albums = $derived($albumList);
	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const playlistDetail = $derived($selectedPlaylistDetail);
	const tab = $derived($detailTab);
	const hasSelection = $derived(!!song || !!activeGen || !!selectedAlbum || !!playlistDetail);
	const hasDetail = $derived(
		$librarySurface === 'create' || ($librarySurface === 'detail' && hasSelection)
	);

	onMount(() => {
		void bootstrapLibrary().then((ok) => {
			if (ok) navCleanup = initNavigation();
		});
		return () => navCleanup?.();
	});

	async function bootstrapLibrary(): Promise<boolean> {
		try {
			const syncOk = await waitForResourceReady();
			if (!syncOk) {
				loadError = true;
				return false;
			}
			const browseOk = await hydrateLibraryFromHistory();
			await loadActiveModels();
			if (!browseOk) {
				addToast('Failed to load', 'error');
				loadError = true;
				return false;
			}
			return true;
		} catch (e) {
			addToast(e instanceof Error ? e.message : RESOURCE_SYNC_ERROR, 'error');
			loadError = true;
			return false;
		} finally {
			loading = false;
		}
	}

	async function retryLoad(): Promise<void> {
		loading = true;
		loadError = false;
		try {
			const syncOk = await retryResourceSync();
			if (!syncOk) {
				loadError = true;
				return;
			}
			const browseOk = await hydrateLibraryFromHistory();
			await loadActiveModels();
			if (!browseOk) {
				loadError = true;
				return;
			}
			navCleanup?.();
			navCleanup = initNavigation();
		} catch (e) {
			addToast(e instanceof Error ? e.message : RESOURCE_SYNC_ERROR, 'error');
			loadError = true;
		} finally {
			loading = false;
		}
	}
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if loadError}
	<div class="error" role="alert">
		<p>{$resourceSync.error || RESOURCE_SYNC_ERROR}</p>
		<button class="retry-btn" onclick={() => retryLoad()}>{LIBRARY_RETRY_LABEL}</button>
	</div>
{:else}
	<div class="workspace" class:has-detail={hasDetail}>
		<SongList
			onNewSong={() => {
				if ($librarySurface === 'create') goBack();
				else openLibraryCreate();
			}}
		/>

		<main class="detail-panel" class:chat-active={!!song && tab === 'chat'}>
			{#if $librarySurface === 'create'}
				<CreateForm albums={$albumList} />
			{:else if activeGen && song}
				<GenerationView />
			{:else if song}
				<SongDetailView />
			{:else if selectedAlbum}
				<AlbumDetailView />
			{:else if playlistDetail}
				<PlaylistDetailView />
			{/if}
		</main>
	</div>
{/if}

<ToastContainer />

<style>
	.workspace {
		display: grid;
		flex: 1;
		width: 100%;
		height: 100%;
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

	.detail-panel.chat-active {
		overflow-y: hidden;
	}

	.loading,
	.error {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--text-muted);
		font-style: italic;
		flex-direction: column;
		gap: 16px;
	}

	.retry-btn {
		display: block;
		margin: 12px auto 0;
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

	.error {
		color: var(--score-bad);
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
