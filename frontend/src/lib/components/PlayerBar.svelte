<script lang="ts">
	import type { Attachment } from 'svelte/attachments';
	import { albumList, songList } from '$lib/stores/libraryData';
	import {
		closeNowPlaying,
		idlePlayTarget,
		nowPlayingOpen,
		nowPlayingSurface,
		openNowPlaying,
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
		toggleShuffle
	} from '$lib/stores/player';
	import { openCollection } from '$lib/stores/collection';
	import {
		playlistDetailLoad,
		selectedPlaylist,
		selectedPlaylistDetail
	} from '$lib/stores/playlists';
	import { transportBarHidden } from '$lib/stores/transportBar';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
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
	} from '$lib/constants';
	import TransportBarFrame from './TransportBarFrame.svelte';
	import OfflineStrip from './OfflineStrip.svelte';
	import {
		updateMediaSessionPlaybackState,
		updateMediaSessionPositionState
	} from '$lib/services/mediaSession';
	import { formatTime } from '$lib/utils/format';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import { nowPlayingFromLabel, nowPlayingTakeLabel } from '$lib/constants/now-playing';

	const MOBILE_TRANSPORT_MEDIA = '(max-width: 640px), (any-pointer: coarse)';

	let mobileTransport = $state(false);
	let roomForCover = $state(true);
	let nowPlayingTrigger: HTMLButtonElement | undefined = $state();

	const current = $derived(audioPlayer.current);
	const transport = $derived(audioPlayer.transport);
	const errorMsg = $derived(audioPlayer.error);
	const currentTime = $derived(audioPlayer.currentTime);
	const duration = $derived(audioPlayer.duration);
	const startNotice = $derived($playStartNotice);

	const isPlaying = $derived(transport === 'playing');
	const isLoading = $derived(transport === 'loading' || transport === 'recovering');

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
		if (!current) return '';
		if (mobileTransport && $playbackSource) return nowPlayingFromLabel($playbackSource.title);
		return nowPlayingTakeLabel(
			current.generation.version_number,
			current.generation.generation_number
		);
	});
	const prevSong = $derived(canPlayPrevSong(current, songs, ctx));
	const nextSong = $derived(canPlayNextSong(current, songs, ctx));

	const coverUrl = $derived.by(() => {
		if (!current) return null;
		const song = songs.find((item) => item.id === current.songId);
		const album = song ? $albumList.find((item) => item.id === song.album_id) : undefined;
		return album?.cover?.card ?? null;
	});

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
		if (!current) {
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
		if (!current) return;
		if (docked) closeNowPlaying();
		else openNowPlaying('queue');
	}

	$effect(() => {
		if (!current) closeNowPlaying();
	});

	$effect(() => {
		updateMediaSessionPlaybackState(isPlaying ? 'playing' : current ? 'paused' : 'none');
		updateMediaSessionPositionState(currentTime, duration);
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
		{#if current}
			{#key current.songTitle}
				<span
					class="track-title"
					class:glowing={isPlaying}
					style={titleGlowStyle}
					{@attach mobileTransport && scrollTitleOnceWhenCut}>{current.songTitle}</span
				>
			{/key}
			<span class="track-detail" id={detailId}
				>{detailLine}{#if isLoading}<span class="loading-text">Loading...</span
					>{:else if inlineFailure}<span class="error-text">{inlineFailure}</span>{/if}</span
			>
		{:else if startNotice === 'building'}
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
		{transport}
		{errorMsg}
		onRetry={() => audioPlayer.play()}
		{currentTime}
		{duration}
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
		nowPlayingDisabled={!current}
		nowPlayingTargetLabel={current ? openNowPlayingLabel(current.songTitle) : undefined}
		nowPlayingTargetDescriptionId={current ? detailId : undefined}
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
	.track-detail {
		font-size: 0.73rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
