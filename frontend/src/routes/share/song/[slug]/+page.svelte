<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { APP_NAME } from '$lib/constants';
	import LegalContent from '$lib/components/LegalContent.svelte';

	interface SharedSong {
		title: string;
		artist: string;
		album_title: string;
		audio_url: string | null;
	}

	let data: SharedSong | null = $state(null);
	let error: string | null = $state(null);
	let loading = $state(true);
	let audioEl: HTMLAudioElement | null = $state(null);
	let isPlaying = $state(false);
	let progress = $state(0);
	let legalSection: string | null = $state(null);

	const slug = $derived(page.params.slug ?? '');

	$effect(() => {
		if (slug) fetchData(slug);
	});

	async function fetchData(s: string) {
		loading = true;
		error = null;
		try {
			const resp = await fetch(`/shared/song/${s}`);
			if (!resp.ok) {
				error = resp.status === 404 ? 'Song not found' : 'Failed to load';
				return;
			}
			data = await resp.json();
		} catch {
			error = 'Failed to load';
		} finally {
			loading = false;
		}
	}

	function togglePlay() {
		if (!audioEl || !data?.audio_url) return;
		if (isPlaying) {
			audioEl.pause();
		} else {
			audioEl.play();
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
	<title>{data ? `${data.title} — ${data.artist}` : 'Shared Song'} | {APP_NAME}</title>
</svelte:head>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') legalSection = null;
	}}
/>

{#if data?.audio_url}
	<audio
		bind:this={audioEl}
		src={data.audio_url}
		ontimeupdate={onTimeUpdate}
		onended={onEnded}
		onpause={() => (isPlaying = false)}
		onplay={() => (isPlaying = true)}
	></audio>
{/if}

<div class="shared-page">
	<div class="bg-effects" aria-hidden="true">
		<div class="glow glow-1"></div>
		<div class="glow glow-2"></div>
	</div>
	{#if loading}
		<div class="center">Loading...</div>
	{:else if error}
		<div class="center error">{error}</div>
	{:else if data}
		<div class="song-header">
			<h1 data-text={data.title}>{data.title}</h1>
			<p class="artist">{data.artist}</p>
			{#if data.album_title}<p class="album">{data.album_title}</p>{/if}
		</div>

		{#if data.audio_url}
			<button class="play-btn" onclick={togglePlay}>
				{isPlaying ? '⏸' : '▶'}
			</button>

			{#if audioEl}
				<div class="now-playing">
					<div class="now-info">
						<span class="now-title">{data.title}</span>
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
		{:else}
			<p class="no-audio">No audio available for this song.</p>
		{/if}

		<p class="powered">
			Powered by <a href="/">{APP_NAME}</a>
			· <button class="link-btn" onclick={() => (legalSection = 'impressum')}>Impressum</button>
			· <button class="link-btn" onclick={() => (legalSection = 'datenschutz')}>Datenschutz</button>
		</p>
	{/if}
</div>

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

	.song-header {
		text-align: center;
		margin-bottom: 2rem;
	}

	.song-header h1 {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 2.4rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin: 0 0 0.3rem;
		color: var(--text);
	}

	.artist {
		font-size: 1.1rem;
		color: var(--primary, #ff3220);
		margin: 0;
	}

	.album {
		color: var(--text-muted, #888);
		margin: 0.2rem 0 0;
		font-size: 0.9rem;
	}

	.play-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 64px;
		height: 64px;
		margin: 2rem auto;
		border-radius: 50%;
		border: 2px solid transparent;
		background: linear-gradient(135deg, var(--primary, #ff3220), var(--accent, #a020f0));
		color: #fff;
		font-size: 24px;
		cursor: pointer;
		transition: box-shadow 0.2s;
	}

	.play-btn:hover {
		box-shadow: 0 0 24px rgba(160, 32, 240, 0.4);
	}

	.no-audio {
		text-align: center;
		color: var(--text-dim, #444);
		font-size: 0.9rem;
		margin-top: 2rem;
	}

	.now-playing {
		margin-top: 1rem;
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
