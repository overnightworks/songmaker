<script lang="ts">
	import { untrack } from 'svelte';
	import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
	import {
		playableTracks,
		trackPlaybackInfo,
		type SharedCollectionView
	} from '#lib/share/sharedCollection.ts';
	import { SharePlayback, type ShareStreamFetcher } from '#lib/share/sharePlayback.svelte.ts';
	import {
		NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
		NOW_PLAYING_SHUFFLE_DISABLE_PREFIX
	} from '#lib/constants/now-playing.ts';
	import {
		SHARE_SONGS_HEADING,
		SHARE_BACK_TO_PLAYER_LABEL,
		shareAlbumSubtitle,
		sharePlaylistSubtitle,
		shareNowPlayingLine,
		SHARE_NO_AUDIO_NOTICE,
		SHARE_NOW_PLAYING_NO_LYRICS
	} from '#lib/constants/share.ts';
	import { formatTime, titleInitials } from '#lib/utils/format.ts';
	import { subscribeCompactLayout } from '#lib/utils/compact-layout.ts';
	import PlaylistCover from '#lib/components/PlaylistCover.svelte';
	import TransportBarFrame from '#lib/components/TransportBarFrame.svelte';
	import NowPlayingFrame from '#lib/components/NowPlayingFrame.svelte';
	import NowPlayingQueue from '#lib/components/NowPlayingQueue.svelte';
	import ShareStatus from '#lib/components/ShareStatus.svelte';
	import SharedFooter from './SharedFooter.svelte';

	const MOBILE_TRANSPORT_MEDIA = '(max-width: 640px), (any-pointer: coarse)';

	interface Props {
		loading: boolean;
		errorKind: 'missing' | 'error' | null;
		resource: string;
		onretry?: () => void;
		view: SharedCollectionView | null;
		fetchStream: ShareStreamFetcher | null;
	}

	let { loading, errorKind, resource, onretry, view, fetchStream }: Props = $props();

	const playback = new SharePlayback();
	let coverFailed = $state(false);
	let mobileTransport = $state(false);
	let stackedPlayer = $state(false);
	let pageElement: HTMLElement | undefined = $state();
	let transportElement: HTMLDivElement | undefined = $state();
	let playerOutOfView = $state(false);

	const tracks = $derived(view ? playableTracks(view.tracks) : []);
	const coverUrl = $derived(view?.cover && !coverFailed ? view.cover.detail : null);
	const currentSubtitle = $derived(playback.currentTrack?.subtitle ?? view?.artist ?? '');
	const isCollection = $derived(view?.kind === 'album' || view?.kind === 'playlist');
	const subtitleByEntryId = $derived(
		view?.kind === 'playlist'
			? new Map(tracks.map((track) => [track.key, track.albumTitle ?? '']))
			: undefined
	);
	const transportCover = $derived(
		view?.kind === 'playlist' ? playback.currentTrack?.cover : view?.cover
	);
	let failedTransportCover = $state<string | null>(null);
	const transportCoverUrl = $derived(transportCover?.card ?? null);
	const stagedTrack = $derived(
		playback.currentTrack ?? tracks[0] ?? (isCollection ? null : view?.tracks[0]) ?? null
	);
	const collectionHead = $derived(
		isCollection && view && stagedTrack
			? {
					title: view.title,
					subtitle:
						view.kind === 'playlist'
							? sharePlaylistSubtitle(tracks.length)
							: shareAlbumSubtitle(view.artist),
					nowPlaying: shareNowPlayingLine(
						stagedTrack.title,
						Math.max(0, playback.queue.currentIndex) + 1,
						tracks.length
					)
				}
			: undefined
	);
	const stagedInfo = $derived(view && stagedTrack ? trackPlaybackInfo(view, stagedTrack) : null);

	$effect(() => {
		void view?.cover;
		coverFailed = false;
	});

	// Only another share restarts playback. Taking the player over makes the
	// app's callbacks read its state, and a Play changing that state must not
	// run this again and unload what it just started.
	$effect(() => {
		const collection = view;
		const streamFetcher = fetchStream;
		if (!collection) return;
		untrack(() => playback.start(collection, streamFetcher));
		return () => playback.stop();
	});

	$effect(() => {
		return subscribeCompactLayout((value) => {
			mobileTransport = value;
		}, MOBILE_TRANSPORT_MEDIA);
	});

	$effect(() => {
		if (!isCollection || !pageElement || !transportElement) {
			playerOutOfView = false;
			return;
		}
		const observer = new IntersectionObserver(
			([entry]) => (playerOutOfView = !entry.isIntersecting),
			{ root: pageElement }
		);
		observer.observe(transportElement);
		return () => observer.disconnect();
	});

	function scrollBackToPlayer(): void {
		pageElement?.querySelector('.now-playing.page')?.scrollIntoView({ behavior: 'smooth' });
	}
</script>

{#snippet playlistCover()}
	{#if view?.kind === 'playlist'}
		<PlaylistCover
			title={view.title}
			covers={view.playlistCovers ?? []}
			cover={view.cover}
			size="100%"
		/>
	{/if}
{/snippet}

{#snippet trackInfo(titleGlowStyle: string)}
	<span class="track-cover" aria-hidden="true">
		{#if transportCoverUrl && transportCoverUrl !== failedTransportCover}
			<img
				src={transportCoverUrl}
				alt=""
				onerror={() => (failedTransportCover = transportCoverUrl)}
			/>
		{:else}
			{titleInitials(playback.currentTrack?.title ?? '')}
		{/if}
	</span>
	<span class="track-text">
		<span class="track-title" style={titleGlowStyle}>{playback.currentTrack?.title ?? ''}</span>
		{#if currentSubtitle}
			<span class="track-detail">{currentSubtitle}</span>
		{/if}
	</span>
{/snippet}

{#snippet collectionSongs()}
	<NowPlayingQueue
		queue={playback.queue}
		contextLabel={view?.title ?? null}
		currentSongTitle={stagedTrack?.title ?? ''}
		heading={SHARE_SONGS_HEADING}
		{subtitleByEntryId}
		onJump={(index) => {
			if (index === playback.queue.currentIndex && playback.currentTrack)
				playback.toggle(playback.currentTrack);
			else playback.jump(index);
		}}
		showTakeLabel={false}
	/>
{/snippet}

<div
	class="shared-page player-page"
	class:collection-page={isCollection}
	class:bar-room={isCollection && stackedPlayer && playback.currentTrack !== null}
	bind:this={pageElement}
>
	<div class="bg-effects" aria-hidden="true">
		<div class="glow glow-1"></div>
		<div class="glow glow-2"></div>
	</div>

	{#if loading}
		<ShareStatus kind="loading" {resource} />
	{:else if errorKind}
		<ShareStatus
			kind={errorKind}
			{resource}
			onretry={errorKind === 'error' ? onretry : undefined}
		/>
	{:else if stagedInfo}
		<NowPlayingFrame
			bind:transportElement
			bind:stacked={stackedPlayer}
			surface="page"
			artwork={view?.kind === 'playlist' ? playlistCover : undefined}
			{collectionHead}
			songs={isCollection ? collectionSongs : undefined}
			canPrev={playback.canPrev}
			canNext={playback.currentTrack ? playback.canNext : tracks.length > 1}
			onprev={isCollection ? () => playback.prev() : undefined}
			onnext={isCollection
				? () => (playback.currentTrack ? playback.next() : playback.jump(1))
				: undefined}
			shuffle={playback.shuffle}
			shuffleLabel={playback.shuffle
				? NOW_PLAYING_SHUFFLE_DISABLE_PREFIX
				: NOW_PLAYING_SHUFFLE_LABEL_PREFIX}
			onToggleShuffle={isCollection ? () => playback.setShuffle(!playback.shuffle) : undefined}
			info={stagedInfo}
			onCoverError={() => (coverFailed = true)}
			{coverUrl}
			onTogglePlay={() => playback.play()}
			onSeek={(seconds) => playback.seek(seconds)}
			ended={playback.ended}
			unplayableNotice={tracks.length === 0 ? SHARE_NO_AUDIO_NOTICE : null}
			showTakeLabel={false}
			lyricsEmptyLabel={SHARE_NOW_PLAYING_NO_LYRICS}
			lyricsCues={stagedTrack?.cues ?? null}
			lyricsText={stagedTrack?.lyrics ?? null}
		/>
	{:else if view}
		<h1 class="header-title">{view.title}</h1>
		<p class="no-audio" role="status">{SHARE_NO_AUDIO_NOTICE}</p>
	{/if}

	<SharedFooter />
</div>

{#if playback.currentTrack && isCollection && playerOutOfView}
	<TransportBarFrame
		transport={audioPlayer.transport}
		errorMsg={audioPlayer.error}
		takeIsCurrent={audioPlayer.current !== null}
		currentTime={audioPlayer.currentTime}
		duration={audioPlayer.duration}
		{formatTime}
		canPrev={playback.canPrev}
		canNext={playback.canNext}
		onPrev={() => playback.prev()}
		onNext={() => playback.next()}
		onTogglePlay={() => playback.play()}
		onSeek={(seconds) => playback.seek(seconds)}
		{trackInfo}
		nowPlayingOpen={false}
		onOpenNowPlaying={scrollBackToPlayer}
		nowPlayingDisabled={false}
		{mobileTransport}
		nowPlayingTargetLabel={SHARE_BACK_TO_PLAYER_LABEL}
		onReturnToPlayer={scrollBackToPlayer}
	/>
{/if}

<style>
	.shared-page {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem 1rem;
		height: 100dvh;
		overflow-y: auto;
		font-family: var(--font-body, 'Open Sans', sans-serif);
		color: var(--text, #e0e0e0);
		position: relative;
	}

	.bg-effects {
		position: fixed;
		inset: 0;
		pointer-events: none;
		z-index: 0;
		overflow: hidden;
		background-image:
			linear-gradient(var(--glow-accent) 1px, transparent 1px),
			linear-gradient(90deg, var(--glow-accent) 1px, transparent 1px);
		background-size: 60px 60px;
	}

	.glow {
		position: absolute;
		border-radius: 50%;
		filter: blur(80px);
		opacity: 0.4;
	}

	.glow-1 {
		width: 300px;
		height: 300px;
		background: color-mix(in srgb, var(--accent) 15%, transparent);
		top: 10%;
		left: -5%;
	}

	.glow-2 {
		width: 250px;
		height: 250px;
		background: color-mix(in srgb, var(--primary) 10%, transparent);
		bottom: 20%;
		right: -5%;
	}

	@media (prefers-reduced-motion: no-preference) {
		.glow-1 {
			animation: float-glow 8s ease-in-out infinite;
		}
		.glow-2 {
			animation: float-glow 10s ease-in-out infinite reverse;
		}
	}

	@keyframes float-glow {
		0%,
		100% {
			transform: translate(0, 0);
		}
		50% {
			transform: translate(20px, -15px);
		}
	}

	.header-title {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 1.55rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1.5px;
		margin: 0;
	}

	.no-audio {
		margin-top: 1.5rem;
		text-align: center;
		color: var(--text-subtle, #888);
		font-size: 0.9rem;
	}

	.track-cover {
		display: grid;
		place-items: center;
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
	}

	.track-detail {
		font-size: 0.73rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* The player page has no bar under it, so nothing reserves its room, and
	   wide it needs the width of two columns. It is a column of the screen's
	   height, which the player fills on a phone to keep the sung line in view. */
	.shared-page.player-page {
		--player-height: 0px;
		--share-player-room: calc(100dvh - 5rem);
		display: flex;
		flex-direction: column;
		max-width: 1120px;
		padding: 4rem 2rem 1rem;
	}

	.shared-page.player-page.collection-page {
		max-width: 1320px;
	}

	@media (max-width: 768px) {
		.shared-page,
		.shared-page.player-page {
			padding: 1.2rem 0.8rem;
		}
		.header-title {
			font-size: 1.2rem;
		}
	}

	/* A phone on its side has no height to spare above the player. */
	@media (max-height: 600px) {
		.shared-page.player-page {
			padding: 0.8rem 1.2rem;
			--share-player-room: calc(100dvh - 1.6rem);
		}
	}

	/* The bar sits over the page's end once the player is out of view, so the
	   footer keeps its room above it from the first Play on. */
	.shared-page.player-page.bar-room {
		padding-bottom: calc(var(--transport-bar-height) + 1rem);
	}
</style>
