<script lang="ts">
	import {
		albumList,
		closeNowPlaying,
		idlePlayTarget,
		nowPlayingOpen,
		nowPlayingSurface,
		openNowPlaying,
		playIdleStart,
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
		songList,
		toggleShuffle
	} from '$lib/stores/player';
	import { openCollection } from '$lib/stores/collection';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		LIBRARY_QUEUE_EMPTY_TITLE,
		LIBRARY_QUEUE_LOADING_TITLE,
		LIBRARY_QUEUE_PLAY_DETAIL,
		LIBRARY_QUEUE_RETRY_DETAIL
	} from '$lib/constants';
	import NowPlaying from './NowPlaying.svelte';
	import TransportBarFrame from './TransportBarFrame.svelte';
	import {
		updateMediaSessionPlaybackState,
		updateMediaSessionPositionState
	} from '$lib/services/mediaSession';
	import { formatTime } from '$lib/utils/format';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	const MOBILE_TRANSPORT_MEDIA = '(max-width: 640px), (any-pointer: coarse)';

	let mobileTransport = $state(false);
	let nowPlayingTrigger: HTMLButtonElement | undefined = $state();

	const current = $derived(audioPlayer.current);
	const status = $derived(audioPlayer.status);
	const errorMsg = $derived(audioPlayer.error);
	const currentTime = $derived(audioPlayer.currentTime);
	const duration = $derived(audioPlayer.duration);
	const startNotice = $derived($playStartNotice);

	const isPlaying = $derived(status === 'playing');
	const isLoading = $derived(status === 'loading' || status === 'buffering');
	const isError = $derived(status === 'error');

	const songs = $derived($songList);
	const ctx = $derived($queueContext);
	const idleTarget = $derived(
		idlePlayTarget({
			collection: $openCollection,
			playlist: $selectedPlaylistDetail,
			albums: $albumList
		})
	);
	const prevSong = $derived(canPlayPrevSong(current, songs, ctx));
	const nextSong = $derived(canPlayNextSong(current, songs, ctx));

	const coverUrl = $derived.by(() => {
		if (!current) return null;
		const song = songs.find((item) => item.id === current.songId);
		const album = song ? $albumList.find((item) => item.id === song.album_id) : undefined;
		return album?.cover?.card ?? null;
	});

	function togglePlay(): void {
		if (!current) {
			void playIdleStart();
			return;
		}
		void retryLastPlayIntent().then((retried) => {
			if (!retried) audioPlayer.toggle();
		});
	}

	function onOpenNowPlayingClick(): void {
		if (!current) return;
		openNowPlaying('queue');
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
</script>

{#snippet trackInfo(titleGlowStyle: string)}
	<span class="track-cover" aria-hidden="true">
		{#if coverUrl}
			<img src={coverUrl} alt="" />
		{/if}
	</span>
	<span class="track-text">
		{#if current}
			<span class="track-title" class:glowing={isPlaying} style={titleGlowStyle}
				>{current.songTitle}</span
			>
			<span class="track-detail"
				>{current.artist} · take {current.generation.generation_number}{#if isLoading}<span
						class="loading-text">Loading...</span
					>{:else if isError}<span class="error-text">{errorMsg ?? 'Error'}</span>{/if}</span
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

<!-- One player, never two: the full surface carries the only transport, so the
	bar steps aside for it on every viewport. -->
{#if $nowPlayingSurface !== 'full'}
	<TransportBarFrame
		{isPlaying}
		{isLoading}
		{isError}
		{errorMsg}
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
		onOpenNowPlaying={onOpenNowPlayingClick}
		nowPlayingDisabled={!current}
		onNowPlayingTriggerBind={(el) => (nowPlayingTrigger = el)}
		{mobileTransport}
	/>
{/if}
{#if $nowPlayingOpen && current}
	<NowPlaying info={current} />
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
