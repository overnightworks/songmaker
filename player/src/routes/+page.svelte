<script lang="ts">
	import { onMount } from 'svelte';
	import { loadFromApi } from '$lib/api/loader';
	import {
		albums,
		browsingTrack,
		browsingAlbum,
		playBrowsingTrack,
		playback,
		browsingAlbumIndex,
		browsingTrackIndex,
		playbackTime
	} from '$lib/stores/player';
	import AlbumNav from '$lib/components/AlbumNav.svelte';
	import SongList from '$lib/components/SongList.svelte';
	import SyncedLyrics from '$lib/components/SyncedLyrics.svelte';
	import ScoresPanel from '$lib/components/ScoresPanel.svelte';
	import GenInfoPanel from '$lib/components/GenInfoPanel.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';

	let loading = $state(true);
	let error = $state('');
	let showChat = $state(false);

	const track = $derived($browsingTrack);
	const album = $derived($browsingAlbum);
	const pb = $derived($playback);
	const albumIdx = $derived($browsingAlbumIndex);
	const trackIdx = $derived($browsingTrackIndex);
	const isBrowsedTrackPlaying = $derived(
		pb?.albumIndex === albumIdx && pb?.trackIndex === trackIdx
	);
	const lyricsTime = $derived(isBrowsedTrackPlaying ? $playbackTime : 0);

	onMount(async () => {
		try {
			const loaded = await loadFromApi();
			albums.set(loaded);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data';
		} finally {
			loading = false;
		}
	});
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if error}
	<div class="error">{error}</div>
{:else}
	<aside class="sidebar">
		<header class="sidebar-header">
			<h1>{album?.title ?? 'Songmaker'}</h1>
		</header>
		<AlbumNav />
		<SongList />
	</aside>

	<main class="main-content">
		{#if track}
			<div class="player-area">
				<div class="now-playing">
					<span class="track-number">{track.number}</span>
					<h2 class="track-title">{track.title}</h2>
					{#if album}
						<span class="track-meta">{album.artist}</span>
					{/if}
					<div class="now-playing-actions">
						<button
							class="play-track-btn"
							class:is-playing={isBrowsedTrackPlaying}
							onclick={playBrowsingTrack}
							aria-label={isBrowsedTrackPlaying ? 'Now playing' : 'Play this track'}
						>
							{isBrowsedTrackPlaying ? '🔊 Playing' : '▶ Play'}
						</button>
						<button
							class="chat-toggle-btn"
							class:active={showChat}
							onclick={() => (showChat = !showChat)}
							aria-label="Toggle Claude chat"
						>
							💬 Claude
						</button>
					</div>
				</div>

				<GenInfoPanel generation={track.generation} />
				<ScoresPanel scores={track.scores} />

				<SyncedLyrics lines={track.lines} currentTime={lyricsTime} />
			</div>
		{:else}
			<div class="empty">Select a track to start</div>
		{/if}
	</main>

	{#if showChat}
		<aside class="chat-panel">
			<ClaudeChat
				songContext={track
					? `Song: ${track.title}\nLyrics:\n${track.lines.map((l) => l.text).join('\n')}`
					: ''}
			/>
		</aside>
	{/if}
{/if}

<style>
	.sidebar {
		width: 320px;
		min-width: 280px;
		height: 100%;
		display: flex;
		flex-direction: column;
		border-right: 1px solid var(--border);
		flex-shrink: 0;
	}

	.sidebar-header {
		padding: 12px;
		border-bottom: 2px solid var(--primary);
		flex-shrink: 0;
	}

	.sidebar-header h1 {
		font-family: var(--font-display);
		font-size: 24px;
		color: var(--primary);
		letter-spacing: 6px;
		text-transform: uppercase;
	}

	.main-content {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
	}

	.player-area {
		max-width: 800px;
		margin: 0 auto;
		padding: 8px 20px;
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
		width: 100%;
	}

	.now-playing {
		text-align: center;
		margin-bottom: 6px;
		flex-shrink: 0;
	}

	.track-number {
		font-family: var(--font-display);
		color: var(--primary);
		font-size: 16px;
	}

	.track-title {
		font-family: var(--font-display);
		color: var(--text);
		font-size: 24px;
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.track-meta {
		color: var(--text-muted);
		font-size: 12px;
		margin-top: 2px;
		display: block;
	}

	.now-playing-actions {
		display: flex;
		gap: 8px;
		justify-content: center;
		margin-top: 8px;
	}

	.play-track-btn {
		margin-top: 8px;
		padding: 6px 20px;
		border: 2px solid var(--primary);
		border-radius: 20px;
		background: transparent;
		color: var(--primary);
		font-family: var(--font-display);
		font-size: 13px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
		transition: all 0.2s;
	}

	.play-track-btn:hover {
		background: var(--primary);
		color: #fff;
	}

	.play-track-btn.is-playing {
		border-color: var(--success);
		color: var(--success);
	}

	.play-track-btn.is-playing:hover {
		background: var(--success);
		color: #fff;
	}

	.chat-toggle-btn {
		padding: 6px 20px;
		border: 2px solid var(--border);
		border-radius: 20px;
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 13px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
		transition: all 0.2s;
	}

	.chat-toggle-btn:hover {
		border-color: var(--primary);
		color: var(--text);
	}

	.chat-toggle-btn.active {
		border-color: var(--primary);
		color: var(--primary);
	}

	.chat-panel {
		width: 350px;
		min-width: 300px;
		height: 100%;
		flex-shrink: 0;
	}

	.loading,
	.error,
	.empty {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--text-muted);
		font-style: italic;
	}

	.error {
		color: var(--score-bad);
	}

	@media (max-width: 768px) {
		.sidebar {
			width: 100%;
			height: auto;
			max-height: 40vh;
			min-width: unset;
			border-right: none;
			border-bottom: 1px solid var(--border);
		}
	}
</style>
