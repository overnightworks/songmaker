<script lang="ts">
	import { onMount } from 'svelte';
	import type { LibraryListenItem } from '#lib/api/library.ts';
	import type { SongItem } from '#lib/api/types.ts';
	import { HOME_LISTEN_LIMIT } from '#lib/constants/home.ts';
	import {
		ensureLastPlayedRead,
		readLastPlayed,
		libraryListenItems,
		libraryListenState
	} from '#lib/stores/libraryOrder.ts';
	import {
		albumList,
		albumSongsLoad,
		allAlbumsLoad,
		songList,
		ensureAllAlbumsLoaded
	} from '#lib/stores/libraryData.ts';
	import { playlistList, playlistLoad, ensurePlaylistsLoaded } from '#lib/stores/playlists.ts';
	import {
		collectionTransport,
		toggleOrStartCollection,
		playAlbum,
		queueContext
	} from '#lib/stores/player.ts';
	import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
	import { openAlbum, openPlaylist } from '#lib/stores/navigation.ts';
	import { whenBackOnline } from '#lib/stores/connectivity.ts';
	import { activityTimeLabel } from '#lib/utils/format.ts';
	import { albumRowOffersPlay } from '#lib/utils/playable.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import type { Key } from '#lib/words/en.ts';
	import LibraryRow from './LibraryRow.svelte';
	import HomeListSection, { homeListPhase } from './HomeListSection.svelte';

	const SENTENCE_KEYS = {
		album: {
			open: 'homeListen.openAlbum',
			cover: 'homeListen.albumCover',
			playing: 'homeListen.albumPlaying',
			stopped: 'homeListen.albumStopped',
			played: 'homeListen.albumPlayed'
		},
		playlist: {
			open: 'homeListen.openPlaylist',
			cover: 'homeListen.playlistCover',
			playing: 'homeListen.playlistPlaying',
			stopped: 'homeListen.playlistStopped',
			played: 'homeListen.playlistPlayed'
		}
	} as const satisfies Record<
		LibraryListenItem['type'],
		Record<'open' | 'cover' | 'playing' | 'stopped' | 'played', Key>
	>;

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

	const phase = $derived(homeListPhase($libraryListenState, visibleItems.length));

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
		const keys = SENTENCE_KEYS[item.type];
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
				return pageText(keys.playing, { number: String(number), total: String(total) });
			if (number) return pageText(keys.stopped, { number: String(number) });
		}
		if (item.song_number) return pageText(keys.stopped, { number: String(item.song_number) });
		return pageText(keys.played, { time: activityTimeLabel(item.played_at, new Date()) });
	}

	function rowPlay(item: LibraryListenItem): (() => void) | undefined {
		if ($collectionTransport(item.type, item.id).current)
			return () => toggleOrStartCollection(item.type, item.id, null);
		const album = item.type === 'album' ? albums.get(item.id) : undefined;
		if (!album || !albumRowOffersPlay(album, albumSongs(album.id), $albumSongsLoad))
			return undefined;
		return () => toggleOrStartCollection('album', album.id, () => void playAlbum(album.id));
	}

	function albumSongs(albumId: string): SongItem[] {
		return $songList.filter((song) => song.album_id === albumId);
	}
</script>

<svelte:document onvisibilitychange={foreground} />

<HomeListSection
	label={pageText('homeListen.label')}
	loadingText={pageText('homeListen.loading')}
	errorText={pageText('homeListen.error')}
	emptyText={pageText('homeListen.empty')}
	{phase}
	onretry={() => void readLastPlayed()}
>
	{#snippet rows()}
		{#each visibleItems as item (item.type + item.id)}
			{@const transport = $collectionTransport(item.type, item.id)}
			<LibraryRow
				title={item.title}
				subtitle={subtitle(item)}
				coverAlt={pageText(SENTENCE_KEYS[item.type].cover, { title: item.title })}
				coverUrl={item.cover?.card ?? null}
				playlistCovers={item.type === 'playlist' ? item.album_covers : null}
				openLabel={pageText(SENTENCE_KEYS[item.type].open, { title: item.title })}
				onopen={() =>
					item.type === 'album' ? void openAlbum(item.id) : void openPlaylist(item.id)}
				current={transport.current}
				transport={transport.transport}
				onplay={rowPlay(item)}
			/>
		{/each}
	{/snippet}
</HomeListSection>
