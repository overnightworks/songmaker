<script lang="ts">
	import type { Attachment } from 'svelte/attachments';
	import {
		albumList,
		songList,
		albumSongsErrorMessage,
		albumSongsLoad
	} from '#lib/stores/libraryData.ts';
	import {
		buildQueueViewModel,
		closeNowPlaying,
		ensureGenerationsLoaded,
		idlePlayTarget,
		nowPlayingOpen,
		nowPlayingSurface,
		openNowPlaying,
		pendingStart,
		playIdleStart,
		playbackSource,
		playNextSong,
		playPrevSong,
		canPlayPrevSong,
		canPlayNextSong,
		playStartNotice,
		queueContext,
		registerNowPlayingTrigger,
		retryLastPlayIntent,
		shuffleEnabled,
		shuffleLabel,
		transportOfTheStart,
		toggleShuffle,
		waitingStartOf
	} from '#lib/stores/player.ts';
	import { openAlbum } from '#lib/stores/navigation.ts';
	import { queueHoldsOneTake } from '#lib/utils/playable.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import { openCollection } from '#lib/stores/collection.ts';
	import {
		playlistDetailLoad,
		selectedPlaylist,
		selectedPlaylistDetail
	} from '#lib/stores/playlists.ts';
	import { transportBarHidden } from '#lib/stores/transportBar.ts';
	import {
		audioPlayer,
		transportIsBusy,
		transportOffersPause,
		transportWaitingNotice
	} from '#lib/services/audioPlayer.svelte.ts';
	import {
		LIBRARY_QUEUE_EMPTY_TITLE,
		LIBRARY_QUEUE_LOADING_TITLE,
		LIBRARY_QUEUE_PLAY_DETAIL,
		LIBRARY_QUEUE_RETRY_DETAIL,
		MINI_PLAYER_TITLE_SCROLL_PX_PER_SECOND,
		MINI_PLAYER_TITLE_SCROLL_REST_MS,
		MINI_PLAYER_TITLE_SCROLL_RETURN_MS,
		MINI_PLAYER_WITHOUT_COVER_MEDIA,
		REDUCED_MOTION_MEDIA,
		openNowPlayingLabel
	} from '#lib/constants.ts';
	import TransportBarFrame from './TransportBarFrame.svelte';
	import OfflineStrip from './OfflineStrip.svelte';
	import {
		clearMediaSessionPositionState,
		updateMediaSessionPlaybackState,
		updateMediaSessionPositionState
	} from '#lib/services/mediaSession.ts';
	import { formatTime } from '#lib/utils/format.ts';
	import { subscribeCompactLayout } from '#lib/utils/compact-layout.ts';
	import { nowPlayingFromLabel, nowPlayingTakeLabel } from '#lib/constants/now-playing.ts';

	const MOBILE_TRANSPORT_MEDIA = '(max-width: 640px), (any-pointer: coarse)';

	let mobileTransport = $state(false);
	let roomForCover = $state(true);
	let nowPlayingTrigger: HTMLButtonElement | undefined = $state();

	const current = $derived(audioPlayer.current);
	const transport = $derived(audioPlayer.transport);
	const currentTime = $derived(audioPlayer.currentTime);
	const duration = $derived(audioPlayer.duration);
	const startNotice = $derived($playStartNotice);
	// A start that waits for the network shows as the transport's own wait, here
	// and on the lock screen, which is the only surface with the screen off.
	const barTransport = $derived(transportOfTheStart(current, startNotice, transport));
	const waitingSong = $derived(waitingStartOf(startNotice, $pendingStart)?.song ?? null);
	// While a start waits, the bar names it in place of any take still loaded,
	// so the take it shows, and a press acts on, is none (#1330).
	const shownTake = $derived(waitingSong ? null : current);
	// A waiting start has no position yet, so the timeline shows none rather
	// than where the take it replaced was paused.
	const shownTime = $derived(shownTake ? currentTime : 0);
	const shownDuration = $derived(shownTake ? duration : 0);
	const errorMsg = $derived(transportWaitingNotice(barTransport) ?? audioPlayer.error);

	const isPlaying = $derived(transport === 'playing');
	const isLoading = $derived(transportIsBusy(transport));

	const songs = $derived($songList);
	const docked = $derived($nowPlayingSurface === 'docked');
	const ctx = $derived($queueContext);
	const idleTarget = $derived(
		idlePlayTarget({
			collection: $openCollection,
			playlist: $selectedPlaylistDetail,
			listedPlaylist: $selectedPlaylist,
			playlistLoading: $playlistDetailLoad.status === 'loading',
			albums: $albumList
		})
	);
	const detailId = $props.id();
	// The phone names where the music comes from under the title; the
	// desktop row, and a queue with no source, name the take.
	const detailLine = $derived.by(() => {
		if (!shownTake) return '';
		if (mobileTransport && $playbackSource) return nowPlayingFromLabel($playbackSource.title);
		return nowPlayingTakeLabel(
			shownTake.generation.version_number,
			shownTake.generation.generation_number
		);
	});
	const prevSong = $derived(canPlayPrevSong(current, songs, ctx));
	const nextSong = $derived(canPlayNextSong(current, songs, ctx));

	const playingSong = $derived(songs.find((item) => item.id === shownTake?.songId));
	const playingAlbumId = $derived(playingSong?.album_id);
	const coverUrl = $derived(
		$albumList.find((item) => item.id === playingAlbumId)?.cover?.card ?? null
	);

	// A cut title shows the rest of itself once, then rests at its start with
	// its ellipsis again; a title that fits, or a listener who asked for less
	// motion, never moves.
	const scrollTitleOnceWhenCut: Attachment<HTMLElement> = (title) => {
		if (window.matchMedia(REDUCED_MOTION_MEDIA).matches) return;
		const overflow = title.scrollWidth - title.clientWidth;
		if (overflow <= 0) return;
		const rest = MINI_PLAYER_TITLE_SCROLL_REST_MS;
		const travel = (overflow / MINI_PLAYER_TITLE_SCROLL_PX_PER_SECOND) * 1000;
		const duration = rest + travel + rest + MINI_PLAYER_TITLE_SCROLL_RETURN_MS;
		const atStart = { textIndent: '0px' };
		const atEnd = { textIndent: `-${overflow}px` };
		const scroll = title.animate(
			[
				{ ...atStart, offset: 0 },
				{ ...atStart, offset: rest / duration },
				{ ...atEnd, offset: (rest + travel) / duration },
				{ ...atEnd, offset: (rest + travel + rest) / duration },
				{ ...atStart, offset: 1 }
			],
			{ duration }
		);
		return () => scroll.cancel();
	};

	function togglePlay(): void {
		if (!shownTake) {
			void playIdleStart();
			return;
		}
		void retryLastPlayIntent().then((retried) => {
			if (!retried) audioPlayer.toggle();
		});
	}

	// The docked panel is a disclosure the bar owns: the same press that opened
	// it puts it away again. A dialog surface only ever opens from here.
	function onNowPlayingClick(): void {
		if (!shownTake) return;
		if (docked) closeNowPlaying();
		// This take for a queue of one, Queue for several; the surface keeps the
		// tab it opened on, so a queue that grows while open does not move it.
		else openNowPlaying(queueOpensOnThisTake() ? 'take' : 'queue');
	}

	function queueOpensOnThisTake(): boolean {
		const queued = buildQueueViewModel(ctx, current).items.length;
		if (ctx.type !== 'album') return queueHoldsOneTake(queued, null);
		const albumId = ctx.albumId;
		return queueHoldsOneTake(queued, {
			songs: songs.filter((s) => s.album_id === albumId),
			load: $albumSongsLoad[albumId]
		});
	}

	$effect(() => {
		if (!current) closeNowPlaying();
	});

	// A start paused from the lock screen stays there, paused, as a take would.
	$effect(() => {
		updateMediaSessionPlaybackState(
			transportOffersPause(barTransport) ? 'playing' : current || $pendingStart ? 'paused' : 'none'
		);
	});

	$effect(() => {
		if (shownTake) updateMediaSessionPositionState(currentTime, duration);
		else clearMediaSessionPositionState();
	});

	$effect(() => {
		registerNowPlayingTrigger(nowPlayingTrigger ?? null);
		return () => registerNowPlayingTrigger(null);
	});

	$effect(() => {
		return subscribeCompactLayout((value) => {
			mobileTransport = value;
		}, MOBILE_TRANSPORT_MEDIA);
	});

	$effect(() => {
		if (mobileTransport || !shownTake || playingSong) return;
		let active = true;
		void ensureGenerationsLoaded(shownTake.songId).catch((err: unknown) => {
			if (active) addToast(albumSongsErrorMessage(err), 'error');
		});
		return () => {
			active = false;
		};
	});

	$effect(() => {
		const withoutCover = window.matchMedia(MINI_PLAYER_WITHOUT_COVER_MEDIA);
		const sync = () => {
			roomForCover = !withoutCover.matches;
		};
		sync();
		withoutCover.addEventListener('change', sync);
		return () => withoutCover.removeEventListener('change', sync);
	});
</script>

{#snippet trackInfo(titleGlowStyle: string, inlineFailure: string | null)}
	{#if roomForCover}
		<span class="track-cover" aria-hidden="true">
			{#if coverUrl}
				<img src={coverUrl} alt="" />
			{/if}
		</span>
	{/if}
	<span class="track-text">
		{#if shownTake}
			{#key shownTake.songTitle}
				<span
					class="track-title"
					class:glowing={isPlaying}
					style={titleGlowStyle}
					{@attach mobileTransport && scrollTitleOnceWhenCut}>{shownTake.songTitle}</span
				>
			{/key}
			{#if !mobileTransport}
				{#if playingAlbumId}
					<button class="track-album" onclick={() => playingAlbumId && openAlbum(playingAlbumId)}
						>{shownTake.albumTitle}</button
					>
				{:else}
					<span class="track-album">{shownTake.albumTitle}</span>
				{/if}
			{/if}
			<span class="track-detail" id={detailId}
				>{detailLine}{#if isLoading}<span class="loading-text">Loading...</span
					>{:else if inlineFailure}<span class="error-text">{inlineFailure}</span>{/if}</span
			>
		{:else if waitingSong}
			<span class="track-title">{waitingSong.songTitle}</span>
			<span class="track-detail">{waitingSong.albumTitle}</span>
		{:else if startNotice === 'building' || startNotice === 'restoring'}
			<span class="track-title">{LIBRARY_QUEUE_LOADING_TITLE}</span>
			<span class="track-detail">{idleTarget.label}</span>
		{:else if startNotice === 'empty'}
			<span class="track-title">{LIBRARY_QUEUE_EMPTY_TITLE}</span>
			<span class="track-detail">{idleTarget.label}</span>
		{:else if startNotice === 'error'}
			<span class="track-title">{idleTarget.label} failed</span>
			<span class="track-detail">{LIBRARY_QUEUE_RETRY_DETAIL}</span>
		{:else}
			<span class="track-title">{idleTarget.label}</span>
			<span class="track-detail">{LIBRARY_QUEUE_PLAY_DETAIL}</span>
		{/if}
	</span>
{/snippet}

<!-- The bar steps aside for the full surface and for the phone's keyboard;
	playback runs on untouched, and the offline strip on its top edge goes with it. -->
{#if !$transportBarHidden}
	<OfflineStrip />
	<TransportBarFrame
		transport={barTransport}
		{errorMsg}
		takeIsCurrent={shownTake !== null}
		currentTime={shownTime}
		duration={shownDuration}
		{formatTime}
		canPrev={Boolean(prevSong)}
		canNext={Boolean(nextSong)}
		onPrev={playPrevSong}
		onNext={playNextSong}
		shuffle={$shuffleEnabled}
		shuffleLabel={$shuffleLabel}
		onToggleShuffle={() => void toggleShuffle()}
		onTogglePlay={togglePlay}
		onSeek={(seconds) => audioPlayer.seek(seconds)}
		{trackInfo}
		nowPlayingOpen={$nowPlayingOpen}
		onOpenNowPlaying={onNowPlayingClick}
		nowPlayingDocked={docked}
		nowPlayingDisabled={!shownTake}
		nowPlayingTargetLabel={shownTake ? openNowPlayingLabel(shownTake.songTitle) : undefined}
		nowPlayingTargetDescriptionId={shownTake ? detailId : undefined}
		onNowPlayingTriggerBind={(el) => (nowPlayingTrigger = el)}
		{mobileTransport}
	/>
{/if}

<style>
	.track-cover {
		display: block;
		width: 44px;
		height: 44px;
		flex-shrink: 0;
		border-radius: var(--card-radius);
		overflow: hidden;
		background: var(--surface-hover);
	}
	.track-cover img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.track-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
	}
	.track-title {
		font-family: var(--font-display);
		font-size: 0.95rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		transition: text-shadow 0.3s;
	}
	@media (prefers-reduced-motion: no-preference) {
		.track-title.glowing {
			text-shadow:
				0 0 8px color-mix(in srgb, var(--accent) 50%, transparent),
				0 0 16px color-mix(in srgb, var(--accent) 20%, transparent);
		}
	}
	.track-album,
	.track-detail {
		font-size: 0.73rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	button.track-album {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		font-size: 0.73rem;
		text-align: left;
		cursor: pointer;
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	button.track-album:hover,
	button.track-album:focus-visible {
		color: var(--primary);
	}
	.loading-text {
		color: var(--primary);
		margin-left: 4px;
	}
	.error-text {
		color: #d34;
		margin-left: 4px;
	}

	@media (max-width: 900px) {
		.track-cover {
			width: 40px;
			height: 40px;
		}
	}

	:global(.mobile-transport) .track-cover {
		width: 40px;
		height: 40px;
	}
</style>
