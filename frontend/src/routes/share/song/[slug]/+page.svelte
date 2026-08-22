<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { APP_NAME, SONG_COVER_ALT_TYPE } from '$lib/constants';
	import LegalContent from '$lib/components/LegalContent.svelte';
	import SharedPlayer from '$lib/components/SharedPlayer.svelte';
	import ShareStatus from '$lib/components/ShareStatus.svelte';

	interface SharedSongCover {
		card: string;
		detail: string;
	}

	interface SharedSong {
		title: string;
		artist: string;
		album_title: string;
		audio_url: string | null;
		cover?: SharedSongCover | null;
	}

	let data: SharedSong | null = $state(null);
	let errorKind: 'missing' | 'error' | null = $state(null);
	let loading = $state(true);
	let legalSection: string | null = $state(null);
	let coverFailed = $state(false);

	const slug = $derived(page.params.slug ?? '');

	$effect(() => {
		if (slug) fetchData(slug);
	});

	async function fetchData(s: string) {
		loading = true;
		errorKind = null;
		coverFailed = false;
		try {
			const resp = await fetch(`/shared/song/${s}`);
			if (!resp.ok) {
				errorKind = resp.status === 404 ? 'missing' : 'error';
				return;
			}
			data = await resp.json();
		} catch {
			errorKind = 'error';
		} finally {
			loading = false;
		}
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

<div class="shared-page">
	<div class="bg-effects" aria-hidden="true">
		<div class="glow glow-1"></div>
		<div class="glow glow-2"></div>
	</div>
	{#if loading}
		<ShareStatus kind="loading" resource="song" />
	{:else if errorKind}
		<ShareStatus
			kind={errorKind}
			resource="song"
			onretry={errorKind === 'error' ? () => fetchData(slug) : undefined}
		/>
	{:else if data}
		<div class="song-header">
			{#if data.cover?.detail && !coverFailed}
				<img
					class="share-cover"
					src={data.cover.detail}
					alt={`${SONG_COVER_ALT_TYPE} ${data.title}`}
					onerror={() => (coverFailed = true)}
				/>
			{/if}
			<h1>{data.title}</h1>
			<p class="artist">{data.artist}</p>
			{#if data.album_title}<p class="album">{data.album_title}</p>{/if}
		</div>

		{#if !data.audio_url}
			<p class="no-audio">No audio available for this song.</p>
		{/if}

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

{#if data?.audio_url}
	<SharedPlayer audioUrl={data.audio_url} title={data.title} subtitle={data.artist} />
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
	.share-cover {
		width: 8rem;
		height: 8rem;
		object-fit: cover;
		margin: 0 auto 1rem;
		display: block;
	}

	.shared-page {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem 1rem calc(var(--player-height, 88px) + 1rem);
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

	.no-audio {
		text-align: center;
		color: var(--text-subtle, #888);
		font-size: 0.9rem;
		margin-top: 2rem;
	}

	.powered {
		text-align: center;
		margin-top: 3rem;
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
