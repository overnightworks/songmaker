<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { fetchSharedAlbumStream } from '$lib/api/client';
	import type { QueueStreamManifest, QueueStreamTrackItem } from '$lib/api/types';
	import { APP_NAME, ALBUM_COVER_ALT_TYPE } from '$lib/constants';
	import LegalContent from '$lib/components/LegalContent.svelte';
	import SharedPlayer from '$lib/components/SharedPlayer.svelte';
	import ShareStatus from '$lib/components/ShareStatus.svelte';
	import { queuePlaybackMode, shouldUseQueueStream } from '$lib/stores/playbackSettings';

	interface SharedSong {
		id: string;
		title: string;
		track_number: number;
		audio_url: string | null;
	}

	interface SharedAlbumCover {
		card: string;
		detail: string;
	}

	interface SharedAlbum {
		title: string;
		artist: string;
		subtitle: string;
		year: string;
		songs: SharedSong[];
		cover?: SharedAlbumCover | null;
	}

	let album: SharedAlbum | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
	let loading = $state(true);
	let currentTrack: SharedSong | null = $state(null);
	let streamManifest: QueueStreamManifest | null = $state(null);
	let streamStartIndex = $state(0);
	let playerPlaying = $state(false);
	let playerLoading = $state(false);
	let legalSection: string | null = $state(null);
	let playerRef: ReturnType<typeof SharedPlayer> | undefined = $state();
	let coverFailed = $state(false);

	const slug = $derived(page.params.slug ?? '');
	const STREAM_REFRESH_MARGIN_MS = 60_000;

	$effect(() => {
		if (slug) fetchAlbum(slug);
	});

	async function fetchAlbum(s: string) {
		loading = true;
		errorKind = null;
		try {
			const resp = await fetch(`/shared/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			album = await resp.json();
			coverFailed = false;
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
	}

	async function play(song: SharedSong) {
		if (!song.audio_url) return;
		if (currentTrack === song) {
			playerRef?.togglePlay();
			return;
		}
		if (shouldUseQueueStream($queuePlaybackMode)) {
			try {
				const manifest = await getStreamManifest();
				const streamIndex = manifest.tracks.findIndex((track) => track.song_id === song.id);
				if (streamIndex >= 0) {
					streamManifest = manifest;
					streamStartIndex = streamIndex;
					currentTrack = song;
					playerRef?.loadAndPlay(manifest.stream_url, {
						startIndex: streamIndex,
						streamTracks: manifest.tracks,
						streamWindowed: manifest.windowed
					});
					return;
				}
			} catch {
				streamManifest = null;
			}
		}
		streamManifest = null;
		currentTrack = song;
		playerRef?.loadAndPlay(song.audio_url, { streamTracks: null, streamWindowed: false });
	}

	async function getStreamManifest(): Promise<QueueStreamManifest> {
		if (
			streamManifest &&
			Date.parse(streamManifest.expires_at) > Date.now() + STREAM_REFRESH_MARGIN_MS
		) {
			return streamManifest;
		}
		streamManifest = await fetchSharedAlbumStream(slug);
		return streamManifest;
	}

	function onEnded() {
		if (!album || !currentTrack) return;
		advanceTrack(1);
	}

	function advanceTrack(direction: number) {
		if (!album || !currentTrack) return;
		if (streamManifest) {
			playerRef?.seekToTrack(streamStartIndex + direction);
			return;
		}
		const playable = album.songs.filter((song) => song.audio_url);
		if (playable.length <= 1) return;
		const idx = Math.max(0, playable.indexOf(currentTrack));
		const nextIndex = (idx + direction + playable.length) % playable.length;
		void play(playable[nextIndex]);
	}

	function onStreamTrackChange(track: QueueStreamTrackItem, index: number) {
		if (!album) return;
		streamStartIndex = index;
		const song = album.songs.find((candidate) => candidate.id === track.song_id);
		if (song) currentTrack = song;
	}

	function onStateChange(playing: boolean, isLoading: boolean) {
		playerPlaying = playing;
		playerLoading = isLoading;
	}

	function onPlayerError() {
		if (!streamManifest || !currentTrack?.audio_url) return;
		streamManifest = null;
		streamStartIndex = 0;
		playerRef?.loadAndPlay(currentTrack.audio_url, { streamTracks: null, streamWindowed: false });
	}
</script>

<svelte:head>
	<title>{album ? `${album.title} — ${album.artist}` : 'Shared Album'} | {APP_NAME}</title>
</svelte:head>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') legalSection = null;
	}}
/>

<div class="shared-page">
	<div class="bg-effects" aria-hidden="true">
		<div class="glow glow-1"></div>
		<div class="glow glow-2"></div>
	</div>
	{#if loading}
		<ShareStatus kind="loading" resource="album" />
	{:else if errorKind}
		<ShareStatus
			kind={errorKind}
			resource="album"
			onretry={errorKind === 'error' ? () => fetchAlbum(slug) : undefined}
		/>
	{:else if album}
		<div class="album-header">
			{#if album.cover?.detail && !coverFailed}
				<img
					class="share-cover"
					src={album.cover.detail}
					alt={`${ALBUM_COVER_ALT_TYPE} ${album.title}`}
					onerror={() => (coverFailed = true)}
				/>
			{/if}
			<h1 data-text={album.title}>{album.title}</h1>
			<p class="artist">{album.artist}</p>
			{#if album.subtitle}<p class="subtitle">{album.subtitle}</p>{/if}
			{#if album.year}<p class="year">{album.year}</p>{/if}
		</div>

		<div class="tracklist">
			{#each album.songs as song (song.id)}
				<button
					class="track"
					class:active={currentTrack === song}
					class:disabled={!song.audio_url}
					onclick={() => play(song)}
					disabled={!song.audio_url}
				>
					<span
						class="play-indicator"
						class:playing={currentTrack === song && playerPlaying}
						class:buffering={currentTrack === song && playerLoading}
					>
						{#if currentTrack === song && playerLoading}
							<span class="spinner"></span>
						{:else if currentTrack === song && playerPlaying}
							⏸
						{:else if song.audio_url}
							▶
						{:else}
							--
						{/if}
					</span>
					<span class="track-title">{song.title}</span>
				</button>
			{/each}
		</div>

		<p class="powered">
			Powered by <a href="/">{APP_NAME}</a>
			· <button class="link-btn" onclick={() => (legalSection = 'impressum')}>Impressum</button>
			· <button class="link-btn" onclick={() => (legalSection = 'datenschutz')}>Datenschutz</button>
			·
			<button class="link-btn" onclick={() => (legalSection = 'nutzungsbedingungen')}
				>Nutzungsbedingungen</button
			>
		</p>
	{/if}
</div>

{#if currentTrack?.audio_url}
	<SharedPlayer
		bind:this={playerRef}
		audioUrl={streamManifest?.stream_url ?? currentTrack.audio_url}
		title={currentTrack.title}
		subtitle={album?.artist}
		autoplay
		streamTracks={streamManifest?.tracks}
		streamWindowed={streamManifest?.windowed ?? false}
		startIndex={streamStartIndex}
		onended={onEnded}
		onnext={() => advanceTrack(1)}
		onprev={() => advanceTrack(-1)}
		onerror={onPlayerError}
		ontrackchange={onStreamTrackChange}
		onstatechange={onStateChange}
	/>
{/if}

{#if legalSection}
	<div class="legal-overlay">
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="legal-backdrop" onclick={() => (legalSection = null)}></div>
		<div class="legal-modal">
			<LegalContent initialSection={legalSection} onback={() => (legalSection = null)} />
		</div>
	</div>
{/if}

<style>
	.shared-page {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem 1rem;
		min-height: 100dvh;
		font-family: var(--font-body, 'Open Sans', sans-serif);
		color: var(--text, #e0e0e0);
		position: relative;
		z-index: 1;
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

	.album-header {
		text-align: center;
		margin-bottom: 2rem;
		position: relative;
	}

	.share-cover {
		width: 8rem;
		height: 8rem;
		object-fit: cover;
		margin: 0 auto 1rem;
		display: block;
	}

	.album-header h1 {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 2.4rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin: 0 0 0.3rem;
		color: var(--text);
		position: relative;
	}

	@media (prefers-reduced-motion: no-preference) {
		.album-header h1:hover::after {
			content: attr(data-text);
			position: absolute;
			top: 0;
			left: 0;
			right: 0;
			color: var(--accent);
			clip-path: inset(0 0 50% 0);
			animation: title-glitch 0.3s steps(2) infinite;
		}
	}

	@keyframes title-glitch {
		0% {
			transform: translate(0);
		}
		50% {
			transform: translate(3px, -1px);
		}
		100% {
			transform: translate(-2px, 1px);
		}
	}

	.artist {
		font-size: 1.1rem;
		color: var(--primary, #ff3220);
		margin: 0;
	}

	.subtitle,
	.year {
		color: var(--text-muted, #888);
		margin: 0.2rem 0 0;
		font-size: 0.9rem;
	}

	.tracklist {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.track {
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
			border-color 0.15s,
			box-shadow 0.15s;
	}

	.track:hover:not(.disabled) {
		background: color-mix(in srgb, var(--surface-hover) 90%, transparent);
		border-color: color-mix(in srgb, var(--accent) 15%, transparent);
		box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 8%, transparent);
	}

	.track.active {
		background: color-mix(in srgb, var(--surface-hover) 90%, transparent);
		border-left: 3px solid transparent;
		border-image: linear-gradient(to bottom, var(--primary), var(--accent)) 1;
	}

	.track.disabled {
		opacity: 0.4;
		cursor: default;
	}

	.play-indicator {
		width: 2.4rem;
		height: 2.4rem;
		border-radius: 50%;
		border: 2px solid var(--border, #333);
		background: transparent;
		color: var(--text-muted, #888);
		font-size: 0.933rem;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		transition:
			border-color 0.15s,
			color 0.15s;
	}

	.track:hover:not(.disabled) .play-indicator {
		border-color: var(--primary, #ff3220);
		color: var(--primary, #ff3220);
	}

	.play-indicator.playing {
		border-color: var(--accent, #a020f0);
		color: var(--accent, #a020f0);
	}

	.play-indicator.buffering {
		border-color: var(--accent, #a020f0);
	}

	.spinner {
		display: inline-block;
		width: 0.933rem;
		height: 0.933rem;
		border: 2px solid var(--accent, #a020f0);
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.track-title {
		flex: 1;
	}

	.powered {
		text-align: center;
		margin-top: 3rem;
		padding-bottom: calc(var(--player-height, 88px) + 1rem);
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
	}

	.powered a {
		color: var(--text-muted, #888);
		text-decoration: none;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		background-clip: text;
	}

	.powered a:hover,
	.powered .link-btn:hover {
		-webkit-text-fill-color: transparent;
	}

	.link-btn {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		cursor: pointer;
		color: var(--text-muted, #888);
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		background-clip: text;
	}

	.legal-overlay {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.legal-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.8);
		backdrop-filter: blur(4px);
	}

	.legal-modal {
		position: relative;
		max-height: 85dvh;
		max-width: 700px;
		width: 95%;
		overflow-y: auto;
		background: var(--bg, #0a0a0a);
		border: 1px solid var(--border, #333);
		border-radius: 8px;
		box-shadow: 0 0 40px color-mix(in srgb, var(--accent) 10%, transparent);
	}
</style>
