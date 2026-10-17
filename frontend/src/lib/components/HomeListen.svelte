<script lang="ts">
	import { onMount } from 'svelte';
	import type { LibraryListenItem } from '$lib/api/library';
	import {
		HOME_LISTEN_LABEL,
		HOME_LISTEN_LIMIT,
		HOME_LISTEN_EMPTY,
		HOME_LISTEN_LOADING,
		HOME_LISTEN_ERROR,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';
	import {
		ensureLastPlayedRead,
		readLastPlayed,
		libraryListenItems,
		libraryListenState
	} from '$lib/stores/libraryOrder';
	import {
		albumList,
		allAlbumsLoad,
		songList,
		ensureAllAlbumsLoaded
	} from '$lib/stores/libraryData';
	import { playlistList, playlistLoad, ensurePlaylistsLoaded } from '$lib/stores/playlists';
	import {
		collectionTransport,
		toggleOrStartCollection,
		playAlbum,
		queueContext
	} from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { openAlbum, openPlaylist } from '$lib/stores/navigation';
	import { whenBackOnline } from '$lib/stores/connectivity';
	import { activityTimeLabel } from '$lib/utils/format';
	import LibraryRow from './LibraryRow.svelte';

	const albums = $derived(new Map($albumList.map((album) => [album.id, album])));
	const playlists = $derived(new Map($playlistList.map((playlist) => [playlist.id, playlist])));
	const visibleItems = $derived(
		$libraryListenItems
			.filter((item) => {
				if (item.type === 'album')
					return (
						!albums.get(item.id)?.is_archived &&
						($allAlbumsLoad.status !== 'ready' || albums.has(item.id))
					);
				return $playlistLoad.status !== 'ready' || playlists.has(item.id);
			})
			.slice(0, HOME_LISTEN_LIMIT)
	);

	onMount(() => {
		void ensureLastPlayedRead();
		void ensureAllAlbumsLoaded();
		void ensurePlaylistsLoaded();
		return whenBackOnline(() => void readLastPlayed());
	});

	function foreground(): void {
		if (document.visibilityState === 'visible') void readLastPlayed();
	}

	function subtitle(item: LibraryListenItem): string {
		const type = item.type === 'album' ? 'Album' : 'Playlist';
		const state = $collectionTransport(item.type, item.id);
		if (state.current) {
			const queue = $queueContext;
			const number =
				queue.type === 'playlist'
					? queue.index + 1
					: $songList.find((song) => song.id === audioPlayer.current?.songId)?.track_number;
			const total =
				item.type === 'album'
					? albums.get(item.id)?.song_count
					: playlists.get(item.id)?.entry_count;
			if (number && total && state.transport === 'playing')
				return `${type} · playing · song ${number} of ${total}`;
			if (number) return `${type} · stopped at song ${number}`;
		}
		if (item.song_number) return `${type} · stopped at song ${item.song_number}`;
		return `${type} · played ${activityTimeLabel(item.played_at, new Date())}`;
	}

	function rowPlay(item: LibraryListenItem): (() => void) | undefined {
		if ($collectionTransport(item.type, item.id).current)
			return () => toggleOrStartCollection(item.type, item.id, null);
		if (item.type === 'album' && albums.get(item.id)?.has_playable_take)
			return () => toggleOrStartCollection('album', item.id, () => void playAlbum(item.id));
		return undefined;
	}
</script>

<svelte:document onvisibilitychange={foreground} />

<section class="home-listen" aria-label={HOME_LISTEN_LABEL}>
	<h2>{HOME_LISTEN_LABEL}</h2>
	{#if $libraryListenState === 'unread'}
		<p role="status">{HOME_LISTEN_LOADING}</p>
	{:else if $libraryListenState === 'failed'}
		<div class="listen-error" role="alert">
			<p>{HOME_LISTEN_ERROR}</p>
			<button type="button" onclick={() => void readLastPlayed()}>{LIBRARY_RETRY_LABEL}</button>
		</div>
	{:else if visibleItems.length === 0}
		<p>{HOME_LISTEN_EMPTY}</p>
	{:else}
		{#each visibleItems as item (item.type + item.id)}
			<LibraryRow
				title={item.title}
				subtitle={subtitle(item)}
				coverAlt={`${item.type} cover for ${item.title}`}
				coverUrl={item.cover?.card ?? null}
				playlistCovers={item.type === 'playlist' ? item.album_covers : null}
				openLabel={`Open ${item.type} ${item.title}`}
				onopen={() =>
					item.type === 'album' ? void openAlbum(item.id) : void openPlaylist(item.id)}
				transport={$collectionTransport(item.type, item.id).transport}
				onplay={rowPlay(item)}
			/>
		{/each}
	{/if}
</section>

<style>
	.home-listen {
		padding: 12px 20px;
	}
	h2 {
		margin: 0 0 8px;
		font-size: 13px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
	}
	p {
		margin: 0;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
	}
	.listen-error {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	button {
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		padding: 4px 8px;
		cursor: pointer;
	}
	@media (max-width: 768px) {
		.home-listen {
			padding: 12px;
		}
	}
</style>
