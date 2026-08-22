<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { get } from 'svelte/store';
	import type { PlaybackInfo } from '$lib/services/playbackTypes';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		HITBOX_FREQUENT_PX,
		NOW_PLAYING_CLOSE,
		NOW_PLAYING_GO_TO_SONG,
		NOW_PLAYING_LABEL,
		NOW_PLAYING_NO_LYRICS,
		NOW_PLAYING_TAKE_PREFIX,
		SHUFFLE_SCOPE_ALBUM,
		SHUFFLE_SCOPE_LIBRARY,
		SHUFFLE_SCOPE_PLAYLIST,
		SONG_NEXT_LABEL,
		SONG_PREVIOUS_LABEL
	} from '$lib/constants';
	import {
		NOW_PLAYING_LYRICS_ROW_LABEL,
		NOW_PLAYING_QUEUE_TAB,
		NOW_PLAYING_RIGHT_PANEL_LABEL,
		NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
		NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
		NOW_PLAYING_STACKED_MEDIA,
		NOW_PLAYING_TAKE_TAB,
		NOW_PLAYING_UP_NEXT_PREFIX,
		NOW_PLAYING_Z_INDEX
	} from '$lib/constants/now-playing';
	import {
		albumList,
		buildQueueViewModel,
		chooseLibraryTakePool,
		ensureGenerationsLoaded,
		jumpToQueueIndex,
		libraryQueueSkipped,
		libraryQueueSkippedComplete,
		nowPlayingPanel,
		queueContext,
		shuffleEnabled,
		songList,
		toggleShuffle,
		windowEnded
	} from '$lib/stores/player';
	import { libraryTakePool, type LibraryTakePool } from '$lib/stores/playbackSettings';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { addToast } from '$lib/stores/toast';
	import { ApiError } from '$lib/api/fetch';
	import { formatTime } from '$lib/utils/format';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import Icon from './Icon.svelte';
	import NowPlayingQueue from './NowPlayingQueue.svelte';
	import NowPlayingTake from './NowPlayingTake.svelte';

	let {
		info,
		onclose,
		onGoToSong,
		canPrev = false,
		canNext = false,
		onprev,
		onnext
	}: {
		info: PlaybackInfo;
		onclose: () => void;
		onGoToSong: () => void;
		canPrev?: boolean;
		canNext?: boolean;
		onprev?: () => void;
		onnext?: () => void;
	} = $props();

	let root: HTMLDivElement | undefined = $state();
	let stacked = $state(false);
	// Seeded once from the shared request store, not bound to it: a take-row
	// click (playTakeAndShowNowPlaying) leaves it on 'take' before opening
	// this surface, while PlayerBar's own Now Playing button opens on 'queue'
	// (see openNowPlaying). Each open is a fresh mount, so this stays correct
	// without the tab flipping under the listener while the panel is open.
	let rightPanelTab: 'queue' | 'take' = $state(get(nowPlayingPanel));
	let mobilePanelOpen = $state(false);
	let mobilePanelSeeded = false;
	let mobileSheet: HTMLDivElement | undefined = $state();
	let queueTabBtn: HTMLButtonElement | undefined = $state();
	let takeTabBtn: HTMLButtonElement | undefined = $state();

	const lyrics = $derived(info.lyrics);
	const hasLyrics = $derived(lyrics != null && lyrics.length > 0);
	const albumLine = $derived(
		[info.albumTitle, info.artist].filter((part) => part.length > 0).join(' · ')
	);
	const takeLabel = $derived(`${NOW_PLAYING_TAKE_PREFIX} ${info.generation.generation_number}`);
	const mobileTriggerLabel = $derived(
		rightPanelTab === 'take' ? NOW_PLAYING_TAKE_TAB : NOW_PLAYING_QUEUE_TAB
	);

	const ctx = $derived($queueContext);
	const songs = $derived($songList);
	const shuffle = $derived($shuffleEnabled);
	const pool = $derived($libraryTakePool);
	const shuffleScope = $derived(
		ctx.type === 'playlist'
			? SHUFFLE_SCOPE_PLAYLIST
			: ctx.type === 'album'
				? SHUFFLE_SCOPE_ALBUM
				: SHUFFLE_SCOPE_LIBRARY
	);
	const shuffleLabel = $derived(
		shuffle
			? `${NOW_PLAYING_SHUFFLE_DISABLE_PREFIX} (${shuffleScope})`
			: `${NOW_PLAYING_SHUFFLE_LABEL_PREFIX} ${shuffleScope}`
	);
	const skipped = $derived(ctx.type === 'library' ? $libraryQueueSkipped : []);
	const skippedComplete = $derived(ctx.type === 'library' ? $libraryQueueSkippedComplete : true);
	const queueVm = $derived(buildQueueViewModel(ctx, audioPlayer.current, songs));
	const contextLabel = $derived.by(() => {
		if (ctx.type === 'album') return $albumList.find((a) => a.id === ctx.albumId)?.title ?? null;
		if (ctx.type === 'playlist') return $selectedPlaylistDetail?.title ?? null;
		return null;
	});

	const coverUrl = $derived.by(() => {
		const song = songs.find((item) => item.id === info.songId);
		const album = song ? $albumList.find((item) => item.id === song.album_id) : undefined;
		return album?.cover?.detail ?? album?.cover?.card ?? null;
	});

	const currentTime = $derived(audioPlayer.currentTime);
	const duration = $derived(audioPlayer.duration);
	const isPlaying = $derived(audioPlayer.status === 'playing');
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);

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

	$effect(() => {
		return subscribeCompactLayout((value) => {
			stacked = value;
			if (!value) {
				mobilePanelOpen = false;
				return;
			}
			// Seed the sheet open state from the requested panel exactly once per
			// mount — a take-row click (rightPanelTab === 'take') should land the
			// user straight in the judging sheet on a stacked layout, the same
			// way it opens the "This take" tab on desktop. Later stacked/unstacked
			// toggles (resize, pointer-type change) must not reopen it.
			if (!mobilePanelSeeded) {
				mobilePanelSeeded = true;
				if (rightPanelTab === 'take') mobilePanelOpen = true;
			}
		}, NOW_PLAYING_STACKED_MEDIA);
	});

	onMount(() => {
		void tick().then(() => root?.focus());
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!root) return;
		if (mobilePanelOpen) {
			if (!mobileSheet) return;
			handleFocusTrapKeydown(mobileSheet, event, () => {
				mobilePanelOpen = false;
			});
			return;
		}
		handleFocusTrapKeydown(root, event, onclose);
	}

	async function openMobilePanel(): Promise<void> {
		mobilePanelOpen = true;
		await tick();
		if (mobileSheet) focusFirstIn(mobileSheet);
	}

	function onTabsKeydown(event: KeyboardEvent): void {
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		event.preventDefault();
		rightPanelTab = rightPanelTab === 'queue' ? 'take' : 'queue';
		(rightPanelTab === 'queue' ? queueTabBtn : takeTabBtn)?.focus();
	}

	function seekFromRange(e: Event): void {
		const target = e.currentTarget as HTMLInputElement;
		audioPlayer.seek(Number(target.value));
	}

	function onChoosePool(next: LibraryTakePool): void {
		void chooseLibraryTakePool(next);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

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
				{ctx}
				queue={queueVm}
				{contextLabel}
				currentSongTitle={info.songTitle}
				{pool}
				{onChoosePool}
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

<div
	bind:this={root}
	class="now-playing"
	class:stacked
	role="dialog"
	aria-modal="true"
	aria-labelledby="now-playing-title"
	tabindex="-1"
	style:z-index={NOW_PLAYING_Z_INDEX}
>
	{#key `${info.songId}:${info.generation.id}`}
		<header class="np-header">
			<div class="np-heading">
				<p class="np-kicker">{NOW_PLAYING_LABEL}</p>
				<h2 id="now-playing-title" class="np-title">{info.songTitle}</h2>
			</div>
			<button
				type="button"
				class="icon-btn"
				style:min-width="{HITBOX_FREQUENT_PX}px"
				style:min-height="{HITBOX_FREQUENT_PX}px"
				onclick={onclose}
				aria-label={NOW_PLAYING_CLOSE}
			>
				<Icon name="x" size={20} />
			</button>
		</header>

		<div class="np-body">
			<section class="np-cover-col">
				<div class="cover-art" aria-hidden="true">
					{#if coverUrl}
						<img src={coverUrl} alt="" />
					{/if}
				</div>
				<div class="cover-meta">
					<span class="cover-title">{info.songTitle}</span>
					{#if albumLine}<span class="cover-line">{albumLine}</span>{/if}
					<span class="cover-line">{takeLabel}</span>
				</div>
				<div class="progress">
					<span class="time">{formatTime(currentTime)}</span>
					<input
						class="progress-range"
						style:--progress="{progressPercent}%"
						type="range"
						min="0"
						max={duration || 0}
						step="0.1"
						value={duration > 0 ? currentTime : 0}
						oninput={seekFromRange}
						disabled={duration <= 0}
						aria-label="Seek playback"
					/>
					<span class="time">{formatTime(duration)}</span>
				</div>
				<div class="transport">
					<button
						type="button"
						class="icon-btn"
						class:active={shuffle}
						style:min-width="{HITBOX_FREQUENT_PX}px"
						style:min-height="{HITBOX_FREQUENT_PX}px"
						onclick={() => toggleShuffle()}
						aria-pressed={shuffle}
						aria-label={shuffleLabel}
						title={shuffleLabel}
					>
						<Icon name="shuffle" size={18} />
					</button>
					{#if onprev}
						<button
							type="button"
							class="icon-btn"
							style:min-width="{HITBOX_FREQUENT_PX}px"
							style:min-height="{HITBOX_FREQUENT_PX}px"
							onclick={onprev}
							disabled={!canPrev}
							aria-label={SONG_PREVIOUS_LABEL}
						>
							<Icon name="skip-back" size={20} />
						</button>
					{/if}
					<button
						type="button"
						class="play-btn"
						onclick={() => audioPlayer.toggle()}
						aria-label={isPlaying ? 'Pause' : 'Play'}
					>
						<Icon name={isPlaying ? 'pause' : 'play'} size={26} />
					</button>
					{#if onnext}
						<button
							type="button"
							class="icon-btn"
							style:min-width="{HITBOX_FREQUENT_PX}px"
							style:min-height="{HITBOX_FREQUENT_PX}px"
							onclick={onnext}
							disabled={!canNext}
							aria-label={SONG_NEXT_LABEL}
						>
							<Icon name="skip-forward" size={20} />
						</button>
					{/if}
				</div>
			</section>

			<section class="np-lyrics-col">
				<p class="lyrics-heading">{NOW_PLAYING_LYRICS_ROW_LABEL}</p>
				{#if hasLyrics}
					<div class="lyrics">{lyrics}</div>
				{:else}
					<p class="lyrics-empty">{NOW_PLAYING_NO_LYRICS}</p>
				{/if}
				<button
					type="button"
					class="go-song"
					style:min-width="{HITBOX_FREQUENT_PX}px"
					style:min-height="{HITBOX_FREQUENT_PX}px"
					onclick={onGoToSong}>{NOW_PLAYING_GO_TO_SONG}</button
				>
			</section>

			{#if !stacked}
				<section class="np-right-col">
					{@render rightPanel()}
				</section>
			{/if}
		</div>

		{#if stacked}
			<button
				type="button"
				class="mobile-panel-trigger"
				onclick={openMobilePanel}
				aria-haspopup="dialog"
				aria-expanded={mobilePanelOpen}
			>
				{#if queueVm.upNext}
					<span class="trigger-up-next"
						>{NOW_PLAYING_UP_NEXT_PREFIX} {queueVm.upNext.songTitle}</span
					>
				{/if}
				<span class="trigger-label"
					>{mobileTriggerLabel}
					<Icon name="chevron-up" size={14} /></span
				>
			</button>
			{#if mobilePanelOpen}
				<button
					type="button"
					class="mobile-sheet-backdrop"
					tabindex="-1"
					aria-label={NOW_PLAYING_CLOSE}
					onclick={() => (mobilePanelOpen = false)}
				></button>
				<div
					bind:this={mobileSheet}
					class="mobile-sheet"
					role="dialog"
					aria-modal="true"
					aria-label={NOW_PLAYING_RIGHT_PANEL_LABEL}
					tabindex="-1"
				>
					{@render rightPanel()}
				</div>
			{/if}
		{/if}
	{/key}
</div>

<style>
	.now-playing {
		position: fixed;
		inset: 0 0 var(--player-height);
		display: flex;
		flex-direction: column;
		background: var(--bg);
		overflow: hidden;
	}
	.np-header {
		flex-shrink: 0;
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.6rem;
		padding: 1rem 1.4rem 0;
	}
	.np-heading {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.np-kicker {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.68rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.np-title {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.05rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		overflow-wrap: anywhere;
	}
	.icon-btn {
		flex-shrink: 0;
		width: 44px;
		height: 44px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid transparent;
		border-radius: 50%;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	.icon-btn:hover:not(:disabled) {
		color: var(--text);
		border-color: var(--border);
		background: var(--surface-hover);
	}
	.icon-btn:disabled {
		color: var(--text-disabled);
		cursor: default;
	}
	.icon-btn.active {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 70%, var(--border));
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	.np-body {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 2rem;
		padding: 1.2rem 1.4rem 1.4rem;
		overflow: hidden;
	}
	.np-cover-col {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1.2rem;
		min-width: 0;
	}
	.cover-art {
		width: min(320px, 80%);
		aspect-ratio: 1;
		border-radius: var(--card-radius);
		overflow: hidden;
		background: var(--surface-hover);
		box-shadow: 0 20px 60px color-mix(in srgb, #000 45%, transparent);
	}
	.cover-art img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.cover-meta {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.2rem;
		text-align: center;
	}
	.cover-title {
		font-family: var(--font-display);
		font-size: 1.4rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.cover-line {
		font-size: 0.8rem;
		color: var(--text-muted);
	}
	.progress {
		width: min(320px, 80%);
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: center;
		gap: 0.6rem;
	}
	.time {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		color: var(--text-muted);
	}
	.progress-range {
		--track-bg: color-mix(in srgb, var(--border) 45%, transparent);
		appearance: none;
		-webkit-appearance: none;
		width: 100%;
		height: 24px;
		background: transparent;
		cursor: pointer;
		accent-color: var(--accent);
	}
	.progress-range:disabled {
		cursor: default;
		opacity: 0.45;
	}
	.progress-range::-webkit-slider-runnable-track {
		height: 4px;
		border-radius: 999px;
		background: linear-gradient(
			90deg,
			var(--primary) 0%,
			var(--accent) var(--progress),
			var(--track-bg) var(--progress),
			var(--track-bg) 100%
		);
	}
	.progress-range::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		border: 2px solid var(--bg);
		background: var(--text);
		margin-top: -5px;
	}
	.transport {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.play-btn {
		width: 62px;
		height: 62px;
		border-radius: 50%;
		border: 2px solid var(--primary);
		background: color-mix(in srgb, var(--surface) 72%, transparent);
		color: var(--primary);
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
	}
	.play-btn:hover {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		border-color: transparent;
		color: #fff;
	}
	.np-lyrics-col {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
		min-height: 0;
		justify-content: center;
	}
	.lyrics-heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.68rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-subtle);
	}
	.lyrics,
	.lyrics-empty {
		margin: 0;
		min-height: 4.5rem;
		max-height: 60vh;
		overflow: auto;
		overflow-wrap: anywhere;
	}
	.lyrics {
		white-space: pre-wrap;
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text);
	}
	.lyrics-empty {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.go-song {
		align-self: flex-start;
		padding: 0.5rem 0.9rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface) 80%, transparent);
		color: var(--text);
		font-size: var(--label-font-size);
		cursor: pointer;
	}
	.go-song:hover {
		border-color: var(--primary);
		background: color-mix(in srgb, var(--primary) 12%, var(--surface));
	}
	.np-right-col {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
		min-height: 0;
		overflow-y: auto;
		justify-content: center;
	}
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
	.mobile-panel-trigger {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.15rem;
		width: 100%;
		padding: 0.6rem 1.4rem calc(0.6rem + env(safe-area-inset-bottom, 0px));
		border: 0;
		border-top: 1px solid var(--border);
		background: var(--header-bg);
		color: var(--text-muted);
		cursor: pointer;
	}
	.trigger-up-next {
		font-size: 0.72rem;
		color: var(--text-subtle);
	}
	.trigger-label {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		font-family: var(--font-display);
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text);
	}
	.mobile-sheet-backdrop {
		position: fixed;
		inset: 0 0 var(--player-height);
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}
	.mobile-sheet {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--player-height);
		max-height: min(70vh, 32rem);
		padding: 0.9rem 1rem calc(0.9rem + env(safe-area-inset-bottom, 0px));
		background: var(--header-bg);
		border-top: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		min-height: 0;
	}
	.mobile-sheet .panel-content {
		overflow-y: auto;
	}

	.now-playing.stacked .np-body {
		grid-template-columns: 1fr;
		overflow-y: auto;
	}
	.now-playing.stacked .np-right-col {
		display: none;
	}
</style>
