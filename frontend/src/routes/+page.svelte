<script lang="ts">
	import { onMount } from 'svelte';
	import { albumList, selectedSong, selectedGeneration, selectedAlbumId } from '$lib/stores/player';
	import { searchQuery } from '$lib/stores/filter';
	import { loadLibraryBrowse } from '$lib/stores/librarySearch';
	import { detailTab, initNavigation } from '$lib/stores/navigation';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { loadActiveModels } from '$lib/stores/presets';
	import { addToast } from '$lib/stores/toast';
	import SongList from '$lib/components/SongList.svelte';
	import CreateForm from '$lib/components/CreateForm.svelte';
	import SongDetailView from '$lib/components/SongDetailView.svelte';
	import GenerationView from '$lib/components/GenerationView.svelte';
	import AlbumDetailView from '$lib/components/AlbumDetailView.svelte';
	import PlaylistDetailView from '$lib/components/PlaylistDetailView.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';

	let loading = $state(true);
	let loadError = $state(false);
	let showCreate = $state(false);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const currentAlbumId = $derived($selectedAlbumId);
	const albums = $derived($albumList);
	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const playlistDetail = $derived($selectedPlaylistDetail);
	const tab = $derived($detailTab);
	const hasDetail = $derived(
		!!song || !!activeGen || showCreate || !!selectedAlbum || !!playlistDetail
	);
	const searching = $derived($searchQuery.trim().length > 0);

	$effect(() => {
		if (song) showCreate = false;
	});

	onMount(() => {
		let cleanup: (() => void) | undefined;

		(async () => {
			try {
				const [browseOk] = await Promise.all([
					loadLibraryBrowse({ reset: true }),
					loadActiveModels()
				]);
				if (!browseOk) {
					addToast('Failed to load', 'error');
					loadError = true;
				}
			} catch (e) {
				addToast(e instanceof Error ? e.message : 'Failed to load', 'error');
				loadError = true;
			} finally {
				loading = false;
			}
			if (!loadError) {
				cleanup = initNavigation();
			}
		})();

		return () => cleanup?.();
	});
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if loadError}
	<div class="error">Failed to load. Please refresh.</div>
{:else}
	<div class="workspace" class:has-detail={hasDetail} class:searching>
		<SongList
			onNewSong={() => {
				showCreate = !showCreate;
			}}
		/>

		<main class="detail-panel" class:chat-active={!!song && tab === 'chat'}>
			{#if showCreate}
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

	.workspace.has-detail.searching {
		grid-template-areas: 'nav browse';
	}

	.workspace.has-detail.searching > :global(.library-browse) {
		display: block;
	}

	.workspace.has-detail.searching > .detail-panel {
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

		.workspace.has-detail.searching {
			grid-template-areas: 'detail';
		}

		.workspace.has-detail.searching > :global(.library-browse) {
			display: none;
		}

		.workspace.has-detail.searching > .detail-panel {
			display: flex;
		}
	}
</style>
