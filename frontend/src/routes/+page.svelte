<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchAlbums, fetchSongs } from '$lib/api/client';
	import { albumList, songList, selectedSong, selectedAlbumId } from '$lib/stores/player';
	import { detailTab, initNavigation } from '$lib/stores/navigation';
	import { selectedPlaylistDetail, loadPlaylists } from '$lib/stores/playlists';
	import { loadActiveModels } from '$lib/stores/presets';
	import { addToast } from '$lib/stores/toast';
	import SongList from '$lib/components/SongList.svelte';
	import CreateForm from '$lib/components/CreateForm.svelte';
	import SongDetailView from '$lib/components/SongDetailView.svelte';
	import AlbumDetailView from '$lib/components/AlbumDetailView.svelte';
	import PlaylistDetailView from '$lib/components/PlaylistDetailView.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';

	let loading = $state(true);
	let loadError = $state(false);
	let showCreate = $state(false);

	const song = $derived($selectedSong);
	const currentAlbumId = $derived($selectedAlbumId);
	const albums = $derived($albumList);
	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const playlistDetail = $derived($selectedPlaylistDetail);
	const tab = $derived($detailTab);
	const hasDetail = $derived(!!song || showCreate || !!selectedAlbum || !!playlistDetail);

	$effect(() => {
		if (song) showCreate = false;
	});

	onMount(() => {
		let cleanup: (() => void) | undefined;

		(async () => {
			try {
				const [a, s] = await Promise.all([
					fetchAlbums(),
					fetchSongs(),
					loadPlaylists(),
					loadActiveModels()
				]);
				albumList.set(a.items);
				songList.set(s.items);
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
	<aside class="sidebar" class:has-detail={hasDetail}>
		<SongList
			onNewSong={() => {
				showCreate = !showCreate;
			}}
		/>
	</aside>

	<main
		class="main-content"
		class:has-detail={hasDetail}
		class:chat-active={!!song && tab === 'chat'}
	>
		{#if showCreate}
			<CreateForm albums={$albumList} />
		{:else if song}
			<SongDetailView />
		{:else if selectedAlbum}
			<AlbumDetailView />
		{:else if playlistDetail}
			<PlaylistDetailView />
		{:else}
			<div class="empty-state">
				<div class="empty-waveform" aria-hidden="true">
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
				</div>
				Select a song or create a new one
			</div>
		{/if}
	</main>
{/if}

<ToastContainer />

<style>
	.sidebar {
		width: 320px;
		min-width: 280px;
		height: 100%;
		display: flex;
		flex-direction: column;
		border-right: 1px solid var(--border);
		flex-shrink: 0;
		position: relative;
		background-image:
			linear-gradient(rgba(160, 32, 240, 0.02) 1px, transparent 1px),
			linear-gradient(90deg, rgba(160, 32, 240, 0.02) 1px, transparent 1px);
		background-size: 40px 40px;
	}

	.main-content {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.main-content.chat-active {
		overflow-y: hidden;
	}

	.loading,
	.error,
	.empty-state {
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

	.empty-waveform {
		display: flex;
		align-items: flex-end;
		gap: 3px;
		height: 32px;
	}

	.wave-bar {
		width: 3px;
		background: linear-gradient(to top, var(--primary), var(--accent));
		border-radius: 2px;
		opacity: 0.3;
	}

	@media (prefers-reduced-motion: no-preference) {
		.wave-bar {
			animation: wave-idle 1.5s ease-in-out infinite;
		}

		.wave-bar:nth-child(1) {
			animation-delay: 0s;
			height: 12px;
		}
		.wave-bar:nth-child(2) {
			animation-delay: 0.15s;
			height: 20px;
		}
		.wave-bar:nth-child(3) {
			animation-delay: 0.3s;
			height: 28px;
		}
		.wave-bar:nth-child(4) {
			animation-delay: 0.45s;
			height: 20px;
		}
		.wave-bar:nth-child(5) {
			animation-delay: 0.6s;
			height: 12px;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.wave-bar:nth-child(1) {
			height: 12px;
		}
		.wave-bar:nth-child(2) {
			height: 20px;
		}
		.wave-bar:nth-child(3) {
			height: 28px;
		}
		.wave-bar:nth-child(4) {
			height: 20px;
		}
		.wave-bar:nth-child(5) {
			height: 12px;
		}
	}

	@keyframes wave-idle {
		0%,
		100% {
			transform: scaleY(0.6);
		}
		50% {
			transform: scaleY(1);
		}
	}

	@media (max-width: 768px) {
		.sidebar {
			position: static;
			width: 100%;
			min-width: 0;
			height: 100%;
			border-right: none;
			transform: none;
		}

		.sidebar.has-detail {
			display: none;
		}

		.main-content {
			display: none;
		}

		.main-content.has-detail {
			display: flex;
		}
	}
</style>
