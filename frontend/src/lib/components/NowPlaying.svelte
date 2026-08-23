<script lang="ts">
	import { get } from 'svelte/store';
	import type { PlaybackInfo } from '$lib/services/playbackTypes';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		NOW_PLAYING_QUEUE_TAB,
		NOW_PLAYING_RIGHT_PANEL_LABEL,
		NOW_PLAYING_TAKE_TAB
	} from '$lib/constants/now-playing';
	import {
		albumList,
		buildQueueViewModel,
		canPlayNextSong,
		canPlayPrevSong,
		chooseLibraryTakePool,
		closeNowPlaying,
		ensureGenerationsLoaded,
		escapeNowPlaying,
		jumpToQueueIndex,
		libraryQueueSkipped,
		libraryQueueSkippedComplete,
		navigateToPlaying,
		nowPlayingPanel,
		playNextSong,
		playPrevSong,
		queueContext,
		shuffleEnabled,
		shuffleLabel,
		songList,
		toggleShuffle,
		windowEnded
	} from '$lib/stores/player';
	import { libraryTakePool, type LibraryTakePool } from '$lib/stores/playbackSettings';
	import { addToast } from '$lib/stores/toast';
	import { ApiError } from '$lib/api/fetch';
	import NowPlayingFrame from './NowPlayingFrame.svelte';
	import NowPlayingQueue from './NowPlayingQueue.svelte';
	import NowPlayingTake from './NowPlayingTake.svelte';

	// The app's Now Playing surface owns its own transport and navigation
	// wiring — every one of its actions is a player-store action, so the mount
	// site only has to say which take is playing.
	let { info }: { info: PlaybackInfo } = $props();

	// Seeded once from the shared request store, not bound to it: a take-row
	// click (playTakeAndShowNowPlaying) leaves it on 'take' before opening
	// this surface, while PlayerBar's own Now Playing button opens on 'queue'
	// (see openNowPlaying). Each open is a fresh mount, so this stays correct
	// without the tab flipping under the listener while the panel is open.
	let rightPanelTab: 'queue' | 'take' = $state(get(nowPlayingPanel));
	let queueTabBtn: HTMLButtonElement | undefined = $state();
	let takeTabBtn: HTMLButtonElement | undefined = $state();

	const mobileTriggerLabel = $derived(
		rightPanelTab === 'take' ? NOW_PLAYING_TAKE_TAB : NOW_PLAYING_QUEUE_TAB
	);

	const ctx = $derived($queueContext);
	const songs = $derived($songList);
	const canPrev = $derived(Boolean(canPlayPrevSong(audioPlayer.current, songs, ctx)));
	const canNext = $derived(Boolean(canPlayNextSong(audioPlayer.current, songs, ctx)));
	const shuffle = $derived($shuffleEnabled);
	const isLibraryQueue = $derived(ctx.type === 'library');
	// Only the library queue is built from a take pool, so only it hands the
	// panel a picker.
	const takePool = $derived(
		isLibraryQueue ? { selected: $libraryTakePool, onChoose: onChoosePool } : undefined
	);
	const skipped = $derived(isLibraryQueue ? $libraryQueueSkipped : []);
	const skippedComplete = $derived(isLibraryQueue ? $libraryQueueSkippedComplete : true);
	const queueVm = $derived(buildQueueViewModel(ctx, audioPlayer.current, songs));
	// What is playing, named by the queue itself — never by the collection the
	// listener happens to have open, which they are free to leave mid-track.
	const contextLabel = $derived.by(() => {
		if (ctx.type === 'album') return $albumList.find((a) => a.id === ctx.albumId)?.title ?? null;
		if (ctx.type === 'playlist') return ctx.playlist.title;
		return null;
	});

	const coverUrl = $derived.by(() => {
		const song = songs.find((item) => item.id === info.songId);
		const album = song ? $albumList.find((item) => item.id === song.album_id) : undefined;
		return album?.cover?.detail ?? album?.cover?.card ?? null;
	});

	// Own-take resolution for the judging panel: resolved against songList, not
	// fetched directly, so a thin library-pool item (no scores/whisper data)
	// upgrades once its song loads. Lives in the component rather than a
	// store-level derived so the async load stays a visible effect, and a
	// rejected fetch reports through the same toast pattern other song loads
	// use — the panel itself just stays absent until the take resolves.
	const song = $derived(songs.find((s) => s.id === info.songId) ?? null);
	const playingGeneration = $derived(
		song?.generations.find((g) => g.id === info.generation.id) ?? null
	);

	$effect(() => {
		const songId = info.songId;
		// Read so Svelte tracks this effect on a take switch too, not just a
		// song switch — ensureGenerationsLoaded only takes songId, but a new
		// generation within the same song still needs playingGeneration
		// re-resolved once its song's data is (re)loaded.
		const trackedGenerationId = info.generation.id;
		void trackedGenerationId;
		void ensureGenerationsLoaded(songId).catch((err: unknown) => {
			addToast(
				err instanceof ApiError ? err.detail || err.message : 'Failed to load take details',
				'error'
			);
		});
	});

	function onTabsKeydown(event: KeyboardEvent): void {
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		event.preventDefault();
		rightPanelTab = rightPanelTab === 'queue' ? 'take' : 'queue';
		(rightPanelTab === 'queue' ? queueTabBtn : takeTabBtn)?.focus();
	}

	function onChoosePool(next: LibraryTakePool): void {
		void chooseLibraryTakePool(next);
	}

	function goToSong(): void {
		closeNowPlaying();
		void navigateToPlaying();
	}
</script>

{#snippet rightPanel()}
	<div
		class="panel-toggle"
		role="tablist"
		aria-label={NOW_PLAYING_RIGHT_PANEL_LABEL}
		tabindex="-1"
		onkeydown={onTabsKeydown}
	>
		<button
			bind:this={queueTabBtn}
			type="button"
			id="np-tab-queue"
			role="tab"
			class:on={rightPanelTab === 'queue'}
			aria-selected={rightPanelTab === 'queue'}
			aria-controls="np-tabpanel"
			tabindex={rightPanelTab === 'queue' ? 0 : -1}
			onclick={() => (rightPanelTab = 'queue')}
		>
			{NOW_PLAYING_QUEUE_TAB}
		</button>
		<button
			bind:this={takeTabBtn}
			type="button"
			id="np-tab-take"
			role="tab"
			class:on={rightPanelTab === 'take'}
			aria-selected={rightPanelTab === 'take'}
			aria-controls="np-tabpanel"
			tabindex={rightPanelTab === 'take' ? 0 : -1}
			onclick={() => (rightPanelTab = 'take')}
		>
			{NOW_PLAYING_TAKE_TAB}
		</button>
	</div>
	<div
		id="np-tabpanel"
		class="panel-content"
		role="tabpanel"
		aria-labelledby={rightPanelTab === 'queue' ? 'np-tab-queue' : 'np-tab-take'}
	>
		{#if rightPanelTab === 'queue'}
			<NowPlayingQueue
				queue={queueVm}
				{contextLabel}
				currentSongTitle={info.songTitle}
				{takePool}
				onJump={jumpToQueueIndex}
				{skipped}
				{skippedComplete}
				windowEnded={$windowEnded}
			/>
		{:else if playingGeneration && song}
			<NowPlayingTake generation={playingGeneration} {song} lyrics={info.lyrics} />
		{/if}
	</div>
{/snippet}

<NowPlayingFrame
	{info}
	{coverUrl}
	onclose={closeNowPlaying}
	onEscape={escapeNowPlaying}
	{canPrev}
	{canNext}
	onprev={playPrevSong}
	onnext={playNextSong}
	{shuffle}
	shuffleLabel={$shuffleLabel}
	onToggleShuffle={() => toggleShuffle()}
	onGoToSong={goToSong}
	upNextTitle={queueVm.upNext?.songTitle ?? null}
	rightPanelLabel={mobileTriggerLabel}
	sheetLabel={NOW_PLAYING_RIGHT_PANEL_LABEL}
	rightPanelOpenOnMount={rightPanelTab === 'take'}
	lyricsCues={playingGeneration?.whisper_cues ?? null}
	whisperText={playingGeneration?.whisper_text ?? null}
	{rightPanel}
/>

<style>
	.panel-toggle {
		display: flex;
		gap: 0.3rem;
		flex-shrink: 0;
	}
	.panel-toggle button {
		flex: 1;
		padding: 0.4rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}
	.panel-toggle button.on {
		border-color: var(--primary);
		color: var(--primary);
		background: color-mix(in srgb, var(--primary) 10%, var(--surface));
	}
	.panel-content {
		min-height: 0;
		overflow-y: auto;
	}
</style>
