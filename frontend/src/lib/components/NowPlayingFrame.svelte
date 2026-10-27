<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import type { WhisperCue } from '$lib/api/types';
	import type { PlaybackInfo } from '$lib/services/playbackTypes';
	import {
		audioPlayer,
		transportButtonFace,
		transportButtonLabel,
		transportIsBusy,
		transportWaitingNotice
	} from '$lib/services/audioPlayer.svelte';
	import {
		HITBOX_FREQUENT_PX,
		NOW_PLAYING_CLOSE,
		NOW_PLAYING_GO_TO_SONG,
		NOW_PLAYING_LABEL,
		NOW_PLAYING_NO_LYRICS,
		SONG_NEXT_LABEL,
		SONG_PREVIOUS_LABEL
	} from '$lib/constants';
	import {
		NOW_PLAYING_COLLAPSE_LABEL,
		NOW_PLAYING_DOCKED_WIDTH_PX,
		NOW_PLAYING_EXPAND_LABEL,
		NOW_PLAYING_PLAY_AGAIN_LABEL,
		NOW_PLAYING_RIGHT_PANEL_LABEL,
		NOW_PLAYING_STACKED_MEDIA,
		NOW_PLAYING_UP_NEXT_PREFIX,
		NOW_PLAYING_Z_INDEX,
		nowPlayingFromLabel,
		nowPlayingOpenSourceLabel,
		nowPlayingSheetCloseLabel,
		nowPlayingTakeLabel,
		type NowPlayingSource,
		type NowPlayingSurfaceKind
	} from '$lib/constants/now-playing';
	import { formatTime } from '$lib/utils/format';
	import { historyLayerState } from '$lib/stores/layers';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import AiNotice from './AiNotice.svelte';
	import Icon from './Icon.svelte';
	import TransportButtonIcon from './TransportButtonIcon.svelte';
	import NowPlayingLyrics from './NowPlayingLyrics.svelte';
	import SeekSlider from './SeekSlider.svelte';

	let {
		info,
		coverUrl,
		artwork,
		onCoverError,
		source = null,
		surface = 'full',
		transportElement = $bindable(),
		stacked = $bindable(false),
		onclose,
		onExpand,
		onCollapse,
		canPrev = false,
		canNext = false,
		onprev,
		onnext,
		shuffle = false,
		shuffleLabel,
		onToggleShuffle,
		onTogglePlay = () => audioPlayer.toggle(),
		onSeek = (seconds) => audioPlayer.seek(seconds),
		ended = false,
		unplayableNotice = null,
		onGoToSong,
		upNextTitle = null,
		rightPanelLabel,
		sheetLabel = NOW_PLAYING_RIGHT_PANEL_LABEL,
		rightPanelOpenOnMount = false,
		showTakeLabel = true,
		lyricsEmptyLabel = NOW_PLAYING_NO_LYRICS,
		// #45: the fully-resolved take's cues/transcript, distinct from `info`
		// (whose `generation` can still be a thin library-pool stub with no
		// whisper data). Absent/null means "no cues yet" — static lyrics.
		lyricsCues = null,
		whisperText = null,
		// #138: the resolved take's lyrics, for callers whose `info` cannot
		// carry them. A share page in stream mode builds `info` from the
		// public queue-stream manifest, which redacts `lyrics` — the text
		// comes from the share payload instead.
		lyricsText = null,
		rightPanel,
		curationBar,
		collectionHead,
		songs
	}: {
		transportElement?: HTMLDivElement;
		stacked?: boolean;
		collectionHead?: { title: string; subtitle: string; nowPlaying: string };
		songs?: Snippet;
		info: PlaybackInfo;
		coverUrl: string | null;
		artwork?: Snippet;
		onCoverError?: () => void;
		// Where the playing queue comes from. The stacked layout names it under
		// the title as a way back there; everywhere else the album line stands.
		source?: NowPlayingSource | null;
		// 'full' covers the viewport as a modal dialog; 'docked' is a column in
		// the page's own layout — no dialog role, no focus trap, no transport
		// of its own, since the transport bar beside it keeps carrying that.
		// 'page' is the whole page a share link opens (#1391): no header, no
		// close, no bar beside it, flowing in the page's own scroll.
		surface?: NowPlayingSurfaceKind | 'page';
		// The overlay surfaces' ×; the page has nothing to close.
		onclose?: () => void;
		// The docked panel grows to the full surface; the full surface shrinks
		// back to the panel wherever the viewport has room for one. A caller
		// with only one surface omits both.
		onExpand?: () => void;
		onCollapse?: () => void;
		canPrev?: boolean;
		canNext?: boolean;
		onprev?: () => void;
		onnext?: () => void;
		// Shuffle shows only where there is an order to shuffle: a single
		// shared song leaves all three out.
		shuffle?: boolean;
		shuffleLabel?: string;
		onToggleShuffle?: () => void;
		// Play and the slider act on the audioPlayer unless the caller owns
		// what they mean: a share page starts its first track before anything
		// is loaded, and starts again once it played to its end.
		onTogglePlay?: () => void;
		onSeek?: (seconds: number) => void;
		// The caller's playback ran out with nothing after it: Play becomes
		// '↻ Play again' and the slider stays at the end, where the player
		// itself goes back to 0:00.
		ended?: boolean;
		// Why there is nothing to play; Play is dimmed and this line says so.
		unplayableNotice?: string | null;
		onGoToSong?: () => void;
		// The phone's trigger for the right panel: what plays next and the
		// panel's name. Read only where a rightPanel is given.
		upNextTitle?: string | null;
		rightPanelLabel?: string;
		// The mobile sheet's accessible name. Independent of rightPanelLabel
		// (the visible trigger button text, which can change with tab state)
		// so the dialog's aria-label stays a stable description.
		sheetLabel?: string;
		rightPanelOpenOnMount?: boolean;
		// Take/version numbering is an internal editing concept — the app's
		// NowPlaying shows it, a public share listener never sees "Take N"
		// (share's classic-mode playback has no real take number to show
		// anyway; see trackPlaybackInfo()).
		showTakeLabel?: boolean;
		lyricsEmptyLabel?: string;
		lyricsCues?: WhisperCue[] | null;
		whisperText?: string | null;
		lyricsText?: string | null;
		// The queue or take panel; a single shared song has none, so it shows
		// neither the column nor the phone's sheet trigger.
		rightPanel?: Snippet;
		// Curation mode's Pick/Keep/Skip strip (issue #228). Rendered in the
		// cover column, which stays visible in every layout (docked, full,
		// and mobile stacked) — unlike the queue/take tabs, which mobile
		// hides behind an extra sheet-opening tap.
		curationBar?: Snippet;
	} = $props();

	const isDocked = $derived(surface === 'docked');
	const isPage = $derived(surface === 'page');
	const isLayer = $derived(surface === 'full');
	const sheetOpen = historyLayerState('now-playing-sheet', false);

	let root: HTMLDivElement | undefined = $state();
	let mobilePanelSeeded = false;
	let mobileSheet: HTMLDivElement | undefined = $state();

	const albumLine = $derived(
		[info.albumTitle, info.artist].filter((part) => part.length > 0).join(' · ')
	);
	const takeLabel = $derived(
		nowPlayingTakeLabel(info.generation.version_number, info.generation.generation_number)
	);

	// Before the player holds a take, the slider shows where it would start
	// and how long it runs.
	const duration = $derived(
		audioPlayer.current === null ? (info.generation.audio_duration_sec ?? 0) : audioPlayer.duration
	);
	const currentTime = $derived(ended ? duration : audioPlayer.currentTime);
	// The words follow the take the player holds, and no line is sung before
	// it holds one or once the caller's playback ended — where the player
	// itself already stands back at 0:00 and would light the opening line.
	const sungAt = $derived(ended || audioPlayer.current === null ? null : audioPlayer.currentTime);
	const transport = $derived(audioPlayer.transport);
	const buttonFace = $derived(transportButtonFace(transport));
	const notice = $derived(unplayableNotice ?? transportWaitingNotice(transport));
	const hasSideControls = $derived(Boolean(onToggleShuffle || onprev || onnext));

	$effect(() => {
		return subscribeCompactLayout((value) => {
			stacked = value;
			if (!value) {
				$sheetOpen = false;
				return;
			}
			// Seed the sheet open state from the requested panel exactly once per
			// mount — a caller that wants to land the listener straight in the
			// sheet (rightPanelOpenOnMount) should do so the same way it opens on
			// desktop. Later stacked/unstacked toggles (resize, pointer-type
			// change) must not reopen it.
			if (!mobilePanelSeeded) {
				mobilePanelSeeded = true;
				if (rightPanelOpenOnMount) $sheetOpen = true;
			}
		}, NOW_PLAYING_STACKED_MEDIA);
	});

	// Opening focuses the surface, and so does every change between docked and
	// full: switching rebuilds the controls the listener was on, which would
	// otherwise drop focus back to the document. The page is not opened.
	$effect(() => {
		if (surface === 'page') return;
		void tick().then(() => root?.focus());
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		// Only the full surface is a layer: the docked panel and the page
		// neither trap focus nor answer Escape — the page's own level-up owns
		// that key, exactly as it would with no panel at all.
		if (!isLayer || !root) return;
		const trap = $sheetOpen ? mobileSheet : root;
		if (trap) handleFocusTrapKeydown(trap, event);
	}

	async function openMobilePanel(): Promise<void> {
		$sheetOpen = true;
		await tick();
		if (mobileSheet) focusFirstIn(mobileSheet);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#snippet coverArt()}
	<div class="cover-art" aria-hidden="true">
		{#if isPage && artwork}
			{@render artwork()}
		{:else if coverUrl}
			<img src={coverUrl} alt="" onerror={onCoverError} />
		{/if}
	</div>
{/snippet}

{#snippet coverMeta()}
	<div class="cover-meta">
		<svelte:element this={isPage ? 'h1' : 'span'} class="cover-title"
			>{info.songTitle}</svelte:element
		>
		{#if stacked && source}
			<button
				type="button"
				class="from-link"
				data-hitbox="text"
				onclick={source.open}
				aria-label={nowPlayingOpenSourceLabel(source.kind, source.title)}
				>{nowPlayingFromLabel(source.title)} <span aria-hidden="true">›</span></button
			>
		{:else if albumLine}<span class="cover-line">{albumLine}</span>{/if}
		<div class="notice-row">
			{#if showTakeLabel}<span class="cover-line">{takeLabel}</span>{/if}
			<AiNotice look="badge" />
		</div>
	</div>
{/snippet}

{#snippet progress()}
	<div class="progress">
		<SeekSlider size="full" {currentTime} {duration} {formatTime} {onSeek} />
		<div class="progress-times">
			<span class="time">{formatTime(currentTime)}</span>
			<span class="time">{formatTime(duration)}</span>
		</div>
	</div>
{/snippet}

{#snippet playButton()}
	{#if ended}
		<button type="button" class="play-again" onclick={onTogglePlay}
			><span aria-hidden="true">↻</span> {NOW_PLAYING_PLAY_AGAIN_LABEL}</button
		>
	{:else}
		<button
			type="button"
			class="play-btn"
			onclick={onTogglePlay}
			disabled={unplayableNotice !== null}
			aria-label={transportButtonLabel(transport)}
			aria-busy={transportIsBusy(transport)}
		>
			<TransportButtonIcon face={buttonFace} size={26} />
		</button>
	{/if}
{/snippet}

{#snippet iconButton(
	icon: string,
	label: string,
	onclick: (() => void) | undefined,
	disabled = false
)}
	<button
		type="button"
		class="icon-btn"
		style:min-width="{HITBOX_FREQUENT_PX}px"
		style:min-height="{HITBOX_FREQUENT_PX}px"
		{onclick}
		{disabled}
		aria-label={label}
	>
		<Icon name={icon} size={20} />
	</button>
{/snippet}

<!-- Play sits on the column's centre line: two equal sides around it, the
	right one closed by an empty square where no repeat control is. With no
	control beside it, Play stands alone. -->
{#snippet transportControls()}
	{#if hasSideControls}
		<div class="transport" bind:this={transportElement}>
			<div class="transport-side before">
				{#if onToggleShuffle}
					<button
						type="button"
						class="icon-btn"
						class:active={shuffle}
						style:min-width="{HITBOX_FREQUENT_PX}px"
						style:min-height="{HITBOX_FREQUENT_PX}px"
						onclick={onToggleShuffle}
						aria-pressed={shuffle}
						aria-label={shuffleLabel}
						title={shuffleLabel}
					>
						<Icon name="shuffle" size={18} />
					</button>
				{/if}
				{#if onprev}
					{@render iconButton('skip-back', SONG_PREVIOUS_LABEL, onprev, !canPrev)}
				{/if}
			</div>
			{@render playButton()}
			<div class="transport-side after">
				{#if onnext}
					{@render iconButton('skip-forward', SONG_NEXT_LABEL, onnext, !canNext)}
				{/if}
				<span
					class="transport-slot"
					style:width="{HITBOX_FREQUENT_PX}px"
					style:height="{HITBOX_FREQUENT_PX}px"
					aria-hidden="true"
				></span>
			</div>
		</div>
	{:else}
		<div class="transport solo" bind:this={transportElement}>{@render playButton()}</div>
	{/if}
	{#if notice}<p class="waiting-notice" role="status">{notice}</p>{/if}
{/snippet}

{#snippet lyrics()}
	<NowPlayingLyrics
		lyrics={lyricsText ?? info.lyrics}
		cues={lyricsCues}
		{whisperText}
		emptyLabel={lyricsEmptyLabel}
		position={sungAt}
		songTitle={isPage && collectionHead ? info.songTitle : undefined}
	/>
{/snippet}

{#snippet pagePlayer()}
	{#if collectionHead}
		<div class="cover-meta">
			<h1 class="cover-title">{collectionHead.title}</h1>
			<div class="notice-row">
				<span class="cover-line">{collectionHead.subtitle}</span>
				<AiNotice look="badge" />
			</div>
			<span class="cover-line now-playing-line">{collectionHead.nowPlaying}</span>
		</div>
	{:else}
		{@render coverMeta()}
	{/if}
	{@render transportControls()}
	{@render progress()}
{/snippet}

<div
	bind:this={root}
	class="now-playing"
	class:docked={isDocked}
	class:page={isPage}
	class:collection={isPage && Boolean(collectionHead)}
	class:stacked
	role={isLayer ? 'dialog' : isDocked ? 'complementary' : undefined}
	aria-modal={isLayer ? 'true' : undefined}
	aria-labelledby={isPage ? undefined : 'now-playing-title'}
	tabindex="-1"
	style:z-index={isLayer ? NOW_PLAYING_Z_INDEX : null}
	style:width={isDocked ? `${NOW_PLAYING_DOCKED_WIDTH_PX}px` : null}
>
	{#key `${info.songId}:${info.generation.id}`}
		{#if isPage}
			<!-- The page reads like the picture a share link promises: the cover,
				then the song, Play, the slider and the words under it. -->
			<div class="np-body">
				{#if stacked}
					{@render coverArt()}
					<section class="np-player-col">
						{@render pagePlayer()}
						{#if unplayableNotice === null}
							<div class="np-page-lyrics">{@render lyrics()}</div>
						{/if}
						{#if songs}<div class="np-page-songs">{@render songs()}</div>{/if}
					</section>
				{:else}
					{#if !collectionHead}{@render coverArt()}{/if}
					<section class="np-player-col">
						{#if collectionHead}<div class="np-page-cover">{@render coverArt()}</div>{/if}
						{@render pagePlayer()}
						{#if !collectionHead && unplayableNotice === null}
							<div class="np-page-lyrics">{@render lyrics()}</div>
						{/if}
					</section>
					{#if collectionHead && unplayableNotice === null}
						<div class="np-page-lyrics">{@render lyrics()}</div>
					{/if}
					{#if songs}<div class="np-page-songs">{@render songs()}</div>{/if}
				{/if}
			</div>
		{:else}
			<header class="np-header">
				<div class="np-heading">
					<p class="np-kicker">{NOW_PLAYING_LABEL}</p>
					<h2 id="now-playing-title" class="np-title">{info.songTitle}</h2>
				</div>
				<div class="np-header-actions">
					{#if isDocked && onExpand}
						<button type="button" class="surface-btn" onclick={onExpand}
							>{NOW_PLAYING_EXPAND_LABEL}</button
						>
					{:else if !isDocked && onCollapse}
						<button type="button" class="surface-btn" onclick={onCollapse}
							>{NOW_PLAYING_COLLAPSE_LABEL}</button
						>
					{/if}
					{@render iconButton('x', NOW_PLAYING_CLOSE, onclose)}
				</div>
			</header>

			<div class="np-body">
				<section class="np-cover-col">
					{@render coverArt()}
					{@render coverMeta()}
					{#if curationBar}{@render curationBar()}{/if}
					<!-- The docked panel has no transport of its own: the bar beside it
						stays visible and keeps carrying seek, shuffle, prev/next and play. -->
					{#if !isDocked}
						{@render progress()}
						{@render transportControls()}
					{/if}
				</section>

				<section class="np-lyrics-col">
					{@render lyrics()}
					{#if onGoToSong}
						<button
							type="button"
							class="go-song"
							style:min-width="{HITBOX_FREQUENT_PX}px"
							style:min-height="{HITBOX_FREQUENT_PX}px"
							onclick={onGoToSong}>{NOW_PLAYING_GO_TO_SONG}</button
						>
					{/if}
				</section>

				{#if rightPanel && !stacked}
					<section class="np-right-col">
						{@render rightPanel()}
					</section>
				{/if}
			</div>

			{#if rightPanel && stacked}
				<button
					type="button"
					class="mobile-panel-trigger"
					onclick={openMobilePanel}
					aria-haspopup="dialog"
					aria-expanded={$sheetOpen}
				>
					{#if upNextTitle}
						<span class="trigger-up-next">{NOW_PLAYING_UP_NEXT_PREFIX} {upNextTitle}</span>
					{/if}
					<span class="trigger-label"
						>{rightPanelLabel}
						<Icon name="chevron-up" size={14} /></span
					>
				</button>
				{#if $sheetOpen}
					<button
						type="button"
						class="mobile-sheet-backdrop"
						tabindex="-1"
						aria-label={nowPlayingSheetCloseLabel(sheetLabel)}
						onclick={() => ($sheetOpen = false)}
					></button>
					<div
						bind:this={mobileSheet}
						class="mobile-sheet"
						role="dialog"
						aria-modal="true"
						aria-label={sheetLabel}
						tabindex="-1"
					>
						{@render rightPanel()}
					</div>
				{/if}
			{/if}
		{/if}
	{/key}
</div>

<style>
	.now-playing {
		position: fixed;
		/* Whatever room the transport bar takes right now — the app collapses
		   that to zero while this surface is up, a share page keeps its bar. */
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
	.np-header-actions {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.surface-btn {
		padding: 0.4rem 0.8rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}
	.surface-btn:hover {
		border-color: var(--primary);
		color: var(--text);
		background: color-mix(in srgb, var(--primary) 12%, var(--surface));
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
	.notice-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: 0.2rem 0.5rem;
		max-width: 100%;
	}
	.cover-title {
		margin: 0;
		font-weight: normal;
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
	.from-link {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		padding: 0 0.5rem;
		border: none;
		background: none;
		color: var(--primary);
		font: inherit;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.progress {
		width: min(320px, 80%);
	}
	.now-playing.stacked .progress {
		width: 100%;
	}
	.progress-times {
		display: flex;
		justify-content: space-between;
	}
	.time {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		color: var(--text-muted);
	}
	.waiting-notice {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-muted);
		text-align: center;
	}
	.transport {
		align-self: stretch;
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: center;
		gap: 1rem;
	}
	.transport-side {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	.transport-side.before {
		justify-content: flex-end;
	}
	.transport-side.after {
		justify-content: flex-start;
	}
	.transport-slot {
		flex-shrink: 0;
	}
	.play-btn {
		width: 64px;
		height: 64px;
		border-radius: 50%;
		border: none;
		background: var(--accent);
		color: var(--on-accent);
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
	}
	.play-btn:hover:not(:disabled),
	.play-again:hover {
		background: color-mix(in srgb, var(--accent) 82%, var(--text));
	}
	.play-btn:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.transport.solo {
		display: flex;
		justify-content: center;
	}
	.play-again {
		display: inline-flex;
		align-items: center;
		gap: 0.6rem;
		min-height: 56px;
		padding: 0 1.5rem 0 1.1rem;
		border: none;
		border-radius: 999px;
		background: var(--accent);
		color: var(--on-accent);
		font: inherit;
		font-size: 1.05rem;
		font-weight: 600;
		cursor: pointer;
	}
	.play-again span {
		font-size: 1.4rem;
		line-height: 1;
	}
	.np-lyrics-col {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
		min-height: 0;
		justify-content: center;
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
		z-index: 1;
		inset: 0 0 var(--player-height);
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}
	.mobile-sheet {
		position: fixed;
		z-index: 3;
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

	.now-playing.docked {
		position: relative;
		inset: auto;
		flex: none;
		height: 100%;
		border-left: 1px solid var(--border);
		background: var(--header-bg);
	}
	.now-playing.docked .np-header {
		padding: 0.9rem 1rem 0;
	}
	.now-playing.docked .np-body {
		grid-template-columns: 1fr;
		gap: 1.1rem;
		padding: 0.9rem 1rem 1.2rem;
		overflow-y: auto;
	}
	.now-playing.docked .np-cover-col,
	.now-playing.docked .np-lyrics-col,
	.now-playing.docked .np-right-col {
		justify-content: flex-start;
	}
	.now-playing.docked .np-right-col {
		overflow-y: visible;
	}
	.now-playing.docked .cover-art {
		width: min(220px, 70%);
		box-shadow: 0 12px 30px color-mix(in srgb, #000 35%, transparent);
	}
	.now-playing.docked .cover-title {
		font-size: 1.1rem;
	}

	.now-playing.stacked .np-body {
		grid-template-columns: 1fr;
		overflow-y: auto;
	}
	.now-playing.stacked .np-right-col {
		display: none;
	}
	/* On a short phone the column's own zero floor let its row collapse, and the
	   centred lyrics spilled up over the transport; sized to content, the row
	   stays whole and the body scrolls to the lyrics instead. */
	.now-playing.stacked .np-lyrics-col {
		min-height: min-content;
	}
	/* The take sheet's backdrop dims the surface, yet × and "Go to song" stay
	   above it: a tap meant for them must not only close the sheet. */
	.now-playing.stacked .np-header,
	.now-playing.stacked .go-song {
		position: relative;
		z-index: 2;
	}
	/* Four 44 px controls and play need a narrower gap to fit a 320 px phone's
	   column; the equal sides keep play on its centre line all the same. */
	.now-playing.stacked .transport,
	.now-playing.stacked .transport-side {
		gap: 0.5rem;
	}

	/* The page a share link opens (#1391): the frame flows in the page's own
	   scroll instead of covering the viewport. Wide, the cover stands beside
	   the song, Play, the slider and the words; on a phone, the frame fills
	   the screen (below). The page around it is a column of the screen's
	   height. */
	.now-playing.page {
		--page-play-size: 76px;
		position: static;
		flex: none;
		background: none;
		overflow: visible;
	}
	.now-playing.page .np-body {
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 4rem;
		align-items: start;
		padding: 0;
		overflow: visible;
	}
	.now-playing.page .cover-art {
		width: 100%;
	}
	.np-player-col {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 1.4rem;
		min-width: 0;
	}
	.now-playing.page .cover-meta {
		align-items: flex-start;
		gap: 0.4rem;
		text-align: left;
	}
	.now-playing.page .notice-row {
		justify-content: flex-start;
	}
	.now-playing.page .cover-title {
		font-size: 2.6rem;
		font-weight: 500;
		line-height: 1.1;
		overflow-wrap: anywhere;
	}
	.now-playing.page .cover-line {
		font-size: 1rem;
	}
	.now-playing.page .transport.solo {
		justify-content: flex-start;
	}
	/* Play again stands in a row as tall as Play, so the page holds still
	   under the listener when the song ends. */
	.now-playing.page .transport {
		min-height: var(--page-play-size);
		align-items: center;
	}
	.now-playing.page .play-btn {
		width: var(--page-play-size);
		height: var(--page-play-size);
		box-shadow: 0 8px 24px color-mix(in srgb, var(--accent) 35%, transparent);
	}
	.now-playing.page .progress,
	.np-page-lyrics {
		align-self: stretch;
		width: auto;
	}
	/* A phone shows the player and the sung line in one screen, at whatever
	   height its browser leaves: the frame is exactly the height the page
	   shows, and the words take what the player leaves, so the line they
	   follow and their Follow stay on screen. Upright, the cover gives way
	   first -- down to nothing -- before the words go under their floor; on
	   its side, the cover stands beside the player as tall as the screen
	   allows. Only a title too long for the screen scrolls the frame. */
	.now-playing.page.stacked {
		--page-lyrics-floor: 10rem;
		height: 100%;
		container-type: size;
	}
	.now-playing.page.stacked .np-body {
		height: 100%;
		overflow-y: auto;
	}
	.now-playing.page.stacked .np-player-col {
		align-self: stretch;
		min-height: 0;
	}
	.now-playing.page.stacked .np-page-lyrics {
		flex: 1 1 0;
		min-height: var(--page-lyrics-floor);
		display: grid;
		grid-template-rows: minmax(0, 1fr);
		text-align: left;
	}
	.now-playing.page.stacked .cover-title {
		font-size: 1.75rem;
	}
	@media (orientation: portrait) {
		.now-playing.page.stacked .np-body {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: minmax(0, min(320px, 80cqi)) minmax(min-content, 1fr);
			gap: 1.6rem;
		}
		.now-playing.page.stacked .cover-art {
			justify-self: center;
			width: auto;
			height: 100%;
		}
		.now-playing.page.stacked .np-player-col,
		.now-playing.page.stacked .cover-meta {
			align-items: center;
			text-align: center;
		}
		.now-playing.page.stacked .notice-row {
			justify-content: center;
		}
		.now-playing.page.stacked .transport.solo {
			justify-content: center;
		}
	}
	@media (orientation: landscape) {
		.now-playing.page.stacked {
			--page-play-size: 56px;
			--page-lyrics-floor: 6rem;
		}
		.now-playing.page.stacked .np-body {
			grid-template-columns: min(320px, 100cqh, 45cqi) minmax(0, 1fr);
			grid-template-rows: minmax(0, 1fr);
			gap: 2rem;
		}
		.now-playing.page.stacked .cover-art {
			align-self: center;
		}
		.now-playing.page.stacked .np-player-col {
			gap: 0.8rem;
		}
		.now-playing.page.stacked .cover-title {
			font-size: 1.4rem;
		}
	}
	.now-playing.page.collection {
		height: auto;
		container-type: normal;
	}
	.now-playing.page.collection .np-body {
		height: auto;
		grid-template-rows: auto;
		overflow: visible;
	}
	.now-playing.page.collection .np-page-lyrics {
		flex: none;
		height: 18rem;
		display: grid;
		grid-template-rows: minmax(0, 1fr);
		text-align: left;
	}
	.now-playing.page:not(.stacked):not(.collection) .np-player-col:has(.np-page-lyrics) {
		height: var(--share-player-room);
	}
	.now-playing.page:not(.stacked):not(.collection) .np-page-lyrics {
		flex: 1 1 0;
		min-height: 6rem;
		display: grid;
		grid-template-rows: minmax(0, 1fr);
	}
	.now-playing.page.collection:not(.stacked) .np-body {
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
		gap: 2.75rem;
	}
	.now-playing.page.collection:not(.stacked) .np-player-col {
		position: sticky;
		top: 0;
		height: auto;
		max-height: var(--share-player-room);
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr) auto auto auto;
	}
	.now-playing.page.collection:not(.stacked) .np-page-cover {
		display: block;
		align-self: stretch;
		min-height: 0;
		container-type: size;
		aspect-ratio: 1;
		width: 100%;
		min-width: 0;
	}
	.now-playing.page.collection:not(.stacked) .cover-art {
		width: min(100cqw, 100cqh);
		height: auto;
	}
	.now-playing.page.collection:not(.stacked) .np-page-lyrics {
		align-self: start;
		position: sticky;
		top: 0;
		height: auto;
		max-height: var(--share-player-room);
	}
	.np-page-songs {
		align-self: stretch;
	}
	@media (max-width: 768px) {
		.now-playing.page.collection .np-body {
			grid-template-columns: minmax(0, 1fr);
			gap: 1.6rem;
		}
		.now-playing.page.collection .cover-art {
			width: min(220px, 100%);
			height: auto;
			justify-self: center;
		}
	}
</style>
