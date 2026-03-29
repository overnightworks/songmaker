<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { APP_NAME } from '$lib/constants';
	import LegalContent from '$lib/components/LegalContent.svelte';

	interface SharedSong {
		title: string;
		track_number: number;
		audio_url: string | null;
	}

	interface SharedAlbum {
		title: string;
		artist: string;
		subtitle: string;
		year: string;
		songs: SharedSong[];
	}

	let album: SharedAlbum | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);
	let currentTrack: SharedSong | null = $state(null);
	let audioEl: HTMLAudioElement | null = $state(null);
	let isPlaying = $state(false);
	let progress = $state(0);
	let showLegal = $state(false);

	const slug = $derived(page.params.slug ?? '');

	$effect(() => {
		if (slug) fetchAlbum(slug);
	});

	async function fetchAlbum(s: string) {
		loading = true;
		error = null;
		try {
			const resp = await fetch(`/shared/${s}`);
			if (!resp.ok) {
				error = resp.status === 404 ? 'Album not found' : 'Failed to load album';
				return;
			}
			album = await resp.json();
		} catch {
			error = 'Failed to load album';
		} finally {
			loading = false;
		}
	}

	function play(song: SharedSong) {
		if (!song.audio_url) return;
		if (currentTrack === song && isPlaying) {
			audioEl?.pause();
			isPlaying = false;
			return;
		}
		currentTrack = song;
		if (audioEl) {
			audioEl.src = song.audio_url;
			audioEl.play();
			isPlaying = true;
		}
	}

	function onTimeUpdate() {
		if (audioEl && audioEl.duration) {
			progress = (audioEl.currentTime / audioEl.duration) * 100;
		}
	}

	function onEnded() {
		isPlaying = false;
		progress = 0;
		if (!album || !currentTrack) return;
		const idx = album.songs.indexOf(currentTrack);
		const next = album.songs.slice(idx + 1).find((s) => s.audio_url);
		if (next) play(next);
	}

	function seek(e: MouseEvent) {
		if (!audioEl || !audioEl.duration) return;
		const bar = e.currentTarget as HTMLElement;
		const rect = bar.getBoundingClientRect();
		const pct = (e.clientX - rect.left) / rect.width;
		audioEl.currentTime = pct * audioEl.duration;
	}

	function formatTime(seconds: number): string {
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}
</script>

<svelte:head>
	<title>{album ? `${album.title} — ${album.artist}` : 'Shared Album'} | {APP_NAME}</title>
</svelte:head>

<audio
	bind:this={audioEl}
	ontimeupdate={onTimeUpdate}
	onended={onEnded}
	onpause={() => (isPlaying = false)}
	onplay={() => (isPlaying = true)}
></audio>

<div class="shared-page">
	<div class="bg-effects" aria-hidden="true">
		<div class="glow glow-1"></div>
		<div class="glow glow-2"></div>
	</div>
	{#if loading}
		<div class="center">Loading...</div>
	{:else if error}
		<div class="center error">{error}</div>
	{:else if album}
		<div class="album-header">
			<h1 data-text={album.title}>{album.title}</h1>
			<p class="artist">{album.artist}</p>
			{#if album.subtitle}<p class="subtitle">{album.subtitle}</p>{/if}
			{#if album.year}<p class="year">{album.year}</p>{/if}
		</div>

		<div class="tracklist">
			{#each album.songs as song (song.track_number)}
				<button
					class="track"
					class:active={currentTrack === song}
					class:disabled={!song.audio_url}
					onclick={() => play(song)}
					disabled={!song.audio_url}
				>
					<span class="track-num">{song.track_number}</span>
					<span class="track-title">{song.title}</span>
					{#if currentTrack === song && isPlaying}
						<span class="track-status">&#9654;</span>
					{:else if !song.audio_url}
						<span class="track-status dim">--</span>
					{/if}
				</button>
			{/each}
		</div>

		{#if currentTrack && audioEl}
			<div class="now-playing">
				<div class="now-info">
					<span class="now-title">{currentTrack.title}</span>
					<span class="now-time">
						{formatTime(audioEl.currentTime || 0)} / {formatTime(audioEl.duration || 0)}
					</span>
				</div>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="progress-bar" onclick={seek}>
					<div class="progress-fill" style="width: {progress}%"></div>
				</div>
			</div>
		{/if}

		<p class="powered">
			Powered by <a href="/">{APP_NAME}</a>
			· <button class="link-btn" onclick={() => (showLegal = true)}>Impressum</button>
			· <button class="link-btn" onclick={() => (showLegal = true)}>Datenschutz</button>
		</p>
	{/if}
</div>

{#if showLegal}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="legal-overlay" onkeydown={(e) => e.key === 'Escape' && (showLegal = false)}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div class="legal-backdrop" onclick={() => (showLegal = false)}></div>
		<div class="legal-modal">
			<LegalContent onback={() => (showLegal = false)} />
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

	.center {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 60dvh;
		color: var(--text-muted, #888);
		font-size: 1.1rem;
	}

	.error {
		color: var(--primary, #ff3220);
	}

	.album-header {
		text-align: center;
		margin-bottom: 2rem;
		position: relative;
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

	.track-num {
		color: var(--text-muted, #888);
		min-width: 1.5rem;
		text-align: right;
		font-size: 0.85rem;
	}

	.track-title {
		flex: 1;
	}

	.track-status {
		color: var(--primary, #ff3220);
		font-size: 0.8rem;
	}

	.dim {
		color: var(--text-dim, #444);
	}

	.now-playing {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		background: var(--header-bg);
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		padding: 0.6rem 1rem 0.8rem;
		z-index: 10;
	}

	.now-info {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.4rem;
	}

	.now-title {
		font-size: 0.9rem;
		color: var(--text);
		font-family: var(--font-display, 'Oswald', sans-serif);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.now-time {
		font-size: 0.75rem;
		color: var(--text-muted, #888);
		font-variant-numeric: tabular-nums;
	}

	.progress-bar {
		height: 4px;
		background: var(--border, #333);
		border-radius: 2px;
		cursor: pointer;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		border-radius: 2px;
		transition: width 0.1s linear;
	}

	.powered {
		text-align: center;
		margin-top: 3rem;
		padding-bottom: 4rem;
		font-size: 0.75rem;
		color: var(--text-dim, #444);
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
