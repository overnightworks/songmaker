<script lang="ts">
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		collectionSubtitle,
		playableTracks,
		type SharedCollectionView,
		type SharedTrack
	} from '$lib/share/sharedCollection';
	import { SharePlayback, type ShareStreamFetcher } from '$lib/share/sharePlayback.svelte';
	import { ALBUM_COVER_ALT_TYPE } from '$lib/constants';
	import { SHARE_NOW_PLAYING_NO_LYRICS, SHARE_NOW_PLAYING_SHEET_LABEL } from '$lib/constants/share';
	import { formatTime, titleInitials } from '$lib/utils/format';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import CollectionHeaderFrame from '$lib/components/CollectionHeaderFrame.svelte';
	import PlaylistCover from '$lib/components/PlaylistCover.svelte';
	import TransportBarFrame from '$lib/components/TransportBarFrame.svelte';
	import NowPlayingFrame from '$lib/components/NowPlayingFrame.svelte';
	import NowPlayingQueue from '$lib/components/NowPlayingQueue.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import ShareStatus from '$lib/components/ShareStatus.svelte';
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
	let nowPlayingOpen = $state(false);

	const tracks = $derived(view ? playableTracks(view.tracks) : []);
	const coverUrl = $derived(view?.cover && !coverFailed ? view.cover.detail : null);
	const coverAlt = $derived(`${ALBUM_COVER_ALT_TYPE} ${view?.albumTitle ?? view?.title ?? ''}`);
	const isPlaying = $derived(audioPlayer.status === 'playing');
	const currentSubtitle = $derived(playback.currentTrack?.subtitle ?? view?.artist ?? '');

	$effect(() => {
		void view?.cover;
		coverFailed = false;
	});

	$effect(() => {
		const collection = view;
		const streamFetcher = fetchStream;
		if (!collection) return;
		playback.start(collection, streamFetcher);
		return () => playback.stop();
	});

	$effect(() => {
		if (!playback.currentTrack) nowPlayingOpen = false;
	});

	$effect(() => {
		return subscribeCompactLayout((value) => {
			mobileTransport = value;
		}, MOBILE_TRANSPORT_MEDIA);
	});

	function onHeaderPlay(): void {
		if (playback.currentTrack) {
			audioPlayer.toggle();
			return;
		}
		const first = tracks[0];
		if (first) playback.toggle(first);
	}

	function onRowClick(track: SharedTrack): void {
		playback.toggle(track);
	}
</script>

{#snippet titleArea()}
	<h2 class="header-title">{view?.title ?? ''}</h2>
	{#if view}<p class="header-subtitle">{collectionSubtitle(view)}</p>{/if}
{/snippet}

{#snippet playlistCover()}
	{#if view?.kind === 'playlist'}
		<PlaylistCover
			title={view.title}
			covers={view.playlistCovers ?? []}
			cover={view.cover}
			size="56px"
		/>
	{/if}
{/snippet}

{#snippet trackInfo(titleGlowStyle: string)}
	<span class="track-cover" aria-hidden="true">
		{#if coverUrl}
			<img src={coverUrl} alt="" />
		{/if}
	</span>
	<span class="track-text">
		<span class="track-title" style={titleGlowStyle}>{playback.currentTrack?.title ?? ''}</span>
		{#if currentSubtitle}
			<span class="track-detail">{currentSubtitle}</span>
		{/if}
	</span>
{/snippet}

{#snippet rightPanel()}
	<NowPlayingQueue
		queue={playback.queue}
		contextLabel={view?.title ?? null}
		currentSongTitle={playback.currentTrack?.title ?? view?.title ?? ''}
		onJump={(index) => playback.jump(index)}
		windowEnded={playback.windowEnded}
		showTakeLabel={false}
	/>
{/snippet}

<div class="shared-page">
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
	{:else if view}
		<CollectionHeaderFrame
			{coverUrl}
			showCover={view.kind !== 'playlist' && Boolean(coverUrl)}
			onCoverError={() => (coverFailed = true)}
			{coverAlt}
			initials={titleInitials(view.title)}
			artFill={null}
			onplay={onHeaderPlay}
			{titleArea}
			coverFallback={view.kind === 'playlist' ? playlistCover : undefined}
		/>

		{#if tracks.length === 0}
			<p class="no-audio">No audio available yet.</p>
		{:else}
			<div class="track-list">
				{#each tracks as track (track.key)}
					{@const row = playback.queueRows.find((r) => r.key === track.key)}
					{@const current = playback.currentTrack?.key === track.key}
					<button type="button" class="track-row" class:current onclick={() => onRowClick(track)}>
						<span class="track-row-play" aria-hidden="true">
							<Icon name={current && isPlaying ? 'pause' : 'play'} size={14} />
						</span>
						<span class="track-row-body">
							<span class="track-row-title">{track.title}</span>
							{#if track.subtitle}<span class="track-row-meta">{track.subtitle}</span>{/if}
						</span>
						{#if row?.durationSec != null}
							<span class="track-row-duration">{formatTime(row.durationSec)}</span>
						{/if}
					</button>
				{/each}
			</div>
		{/if}
	{/if}

	<SharedFooter />
</div>

{#if playback.currentTrack}
	<TransportBarFrame
		{isPlaying}
		isLoading={audioPlayer.status === 'loading' || audioPlayer.status === 'buffering'}
		isError={audioPlayer.status === 'error'}
		errorMsg={audioPlayer.error}
		currentTime={audioPlayer.currentTime}
		duration={audioPlayer.duration}
		{formatTime}
		canPrev={playback.canPrev}
		canNext={playback.canNext}
		onPrev={() => playback.prev()}
		onNext={() => playback.next()}
		onTogglePlay={() => audioPlayer.toggle()}
		onSeek={(seconds) => audioPlayer.seek(seconds)}
		{trackInfo}
		{nowPlayingOpen}
		onOpenNowPlaying={() => (nowPlayingOpen = true)}
		nowPlayingDisabled={false}
		{mobileTransport}
	/>
{/if}

{#if nowPlayingOpen && audioPlayer.current}
	<NowPlayingFrame
		info={audioPlayer.current}
		{coverUrl}
		onclose={() => (nowPlayingOpen = false)}
		canPrev={playback.canPrev}
		canNext={playback.canNext}
		onprev={() => playback.prev()}
		onnext={() => playback.next()}
		shuffle={playback.shuffle}
		shuffleLabel={playback.shuffle ? 'Disable shuffle' : 'Shuffle'}
		onToggleShuffle={() => playback.setShuffle(!playback.shuffle)}
		upNextTitle={playback.queue.upNext?.songTitle ?? null}
		rightPanelLabel="Queue"
		sheetLabel={SHARE_NOW_PLAYING_SHEET_LABEL}
		showTakeLabel={false}
		lyricsEmptyLabel={SHARE_NOW_PLAYING_NO_LYRICS}
		lyricsCues={playback.currentCues}
		lyricsText={playback.currentTrack?.lyrics ?? null}
		{rightPanel}
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

	.header-subtitle {
		margin: 0.2rem 0 0;
		font-size: 0.85rem;
		color: var(--text-muted, #888);
	}

	.no-audio {
		margin-top: 1.5rem;
		text-align: center;
		color: var(--text-subtle, #888);
		font-size: 0.9rem;
	}

	.track-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: 1.2rem;
	}

	.track-row {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		padding: 0.7rem 1rem;
		background: color-mix(in srgb, var(--surface) 80%, transparent);
		border: 1px solid transparent;
		border-radius: 4px;
		color: var(--text, #e0e0e0);
		font-size: 0.95rem;
		cursor: pointer;
		text-align: left;
		transition:
			background 0.15s,
			border-color 0.15s;
	}

	.track-row:hover {
		background: color-mix(in srgb, var(--surface-hover) 90%, transparent);
		border-color: color-mix(in srgb, var(--accent) 15%, transparent);
	}

	.track-row.current {
		background: color-mix(in srgb, var(--surface-hover) 90%, transparent);
		border-left: 3px solid transparent;
		border-image: linear-gradient(to bottom, var(--primary), var(--accent)) 1;
	}

	.track-row-play {
		width: 2.4rem;
		height: 2.4rem;
		border-radius: 50%;
		border: 2px solid var(--border, #333);
		color: var(--text-muted, #888);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.track-row:hover .track-row-play {
		border-color: var(--primary, #ff3220);
		color: var(--primary, #ff3220);
	}

	.track-row.current .track-row-play {
		border-color: var(--accent, #a020f0);
		color: var(--accent, #a020f0);
	}

	.track-row-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.track-row-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.track-row-meta {
		font-size: 0.75rem;
		color: var(--text-muted, #888);
	}

	.track-row-duration {
		flex-shrink: 0;
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
	}

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
	}

	.track-detail {
		font-size: 0.73rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	@media (max-width: 768px) {
		.shared-page {
			padding: 1.2rem 0.8rem;
		}
		.header-title {
			font-size: 1.2rem;
		}
	}
</style>
