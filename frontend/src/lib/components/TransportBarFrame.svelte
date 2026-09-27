<script lang="ts">
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		NOW_PLAYING_LABEL,
		NOW_PLAYING_SWIPE_RISE_PX,
		TRANSPORT_PAUSE_LABEL,
		TRANSPORT_PLAY_LABEL,
		TRANSPORT_RETRY_LABEL
	} from '$lib/constants';
	import {
		AudioVisualizer,
		FFT_SIZE,
		readVizColors,
		boxShadowStyle,
		titleGlowStyle,
		playbackVisualizerAllowed,
		type VizColors
	} from '$lib/utils/visualizer';

	interface Props {
		isPlaying: boolean;
		isLoading: boolean;
		isError: boolean;
		errorMsg?: string | null;
		currentTime: number;
		duration: number;
		formatTime: (seconds: number) => string;
		canPrev: boolean;
		canNext: boolean;
		onPrev: () => void;
		onNext: () => void;
		shuffle?: boolean;
		shuffleLabel?: string;
		onToggleShuffle?: () => void;
		onTogglePlay: () => void;
		onSeek: (seconds: number) => void;
		// The frame owns the layout, so it alone says whether the track info
		// carries why playback stopped or the phone's right side does.
		trackInfo: Snippet<[titleGlowStyle: string, inlineFailure: string | null]>;
		nowPlayingOpen: boolean;
		onOpenNowPlaying: () => void;
		// A docked Now Playing is a panel in the page, not a popup: the trigger
		// is then a plain disclosure and must not promise a dialog.
		nowPlayingDocked?: boolean;
		nowPlayingDisabled: boolean;
		// The phone's cover-and-title target is named after the playing song.
		nowPlayingTargetLabel?: string;
		// That label replaces the target's own words for a screen reader, so
		// the line under the title is read as its description.
		nowPlayingTargetDescriptionId?: string;
		onNowPlayingTriggerBind?: (el: HTMLButtonElement | undefined) => void;
		mobileTransport: boolean;
	}

	let {
		isPlaying,
		isLoading,
		isError,
		errorMsg = null,
		currentTime,
		duration,
		formatTime,
		canPrev,
		canNext,
		onPrev,
		onNext,
		shuffle = false,
		shuffleLabel = '',
		onToggleShuffle,
		onTogglePlay,
		onSeek,
		trackInfo,
		nowPlayingOpen,
		onOpenNowPlaying,
		nowPlayingDocked = false,
		nowPlayingDisabled,
		nowPlayingTargetLabel = NOW_PLAYING_LABEL,
		nowPlayingTargetDescriptionId,
		onNowPlayingTriggerBind,
		mobileTransport
	}: Props = $props();

	let nowPlayingTrigger: HTMLButtonElement | undefined = $state();
	let phoneTransportControls: HTMLDivElement | undefined = $state();
	let swipeStart: { pointerId: number; x: number; y: number } | null = null;
	let swipeOpenedNowPlaying = false;
	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let analyser: AnalyserNode | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let bassLevel = $state(0);
	let energyLevel = $state(0);
	let vizColors: VizColors = $state({ pr: 255, pg: 50, pb: 32, ar: 160, ag: 32, ab: 240 });

	// Previous and next are frequent phone targets; the desktop row keeps
	// its own press feedback.
	const phoneHitbox = $derived(mobileTransport ? 'frequent' : undefined);

	const phoneFailureId = $props.id();
	const playbackFailure = $derived(isError ? (errorMsg ?? 'Error') : null);
	const nowPlayingTargetDescribedBy = $derived(
		[nowPlayingTargetDescriptionId, playbackFailure && phoneFailureId].filter(Boolean).join(' ') ||
			undefined
	);

	const viz = new AudioVisualizer();
	const progressPercent = $derived(
		duration > 0 ? Math.max(0, Math.min(100, (currentTime / duration) * 100)) : 0
	);
	const boxShadow = $derived(isPlaying ? boxShadowStyle(energyLevel, vizColors) : '');
	const playFaceStyle = $derived(isPlaying ? `transform: scale(${1 + bassLevel * 0.15})` : '');
	const trackTitleGlowStyle = $derived(isPlaying ? titleGlowStyle(bassLevel, vizColors) : '');

	// Reported on unmount too: the app hides the whole bar under the
	// full-screen Now Playing surface, and an owner that kept the detached
	// button would hand focus to an element no longer on the page.
	$effect(() => {
		onNowPlayingTriggerBind?.(nowPlayingTrigger);
		return () => onNowPlayingTriggerBind?.(undefined);
	});

	$effect(() => {
		const playing = isPlaying;
		untrack(() => {
			if (playing) startVisualizerLoop();
			else stopVisualizerLoop();
		});
	});

	// Borrowed, never owned: the audio graph outlives this bar, which the app
	// unmounts whenever the full Now Playing surface takes over the transport.
	// Building or closing a context here would tear the playing element's
	// output out of its graph for good (issue #140).
	function connectAnalyser(): void {
		if (analyser) return;
		if (!playbackVisualizerAllowed()) return;
		try {
			const borrowed = audioPlayer.getAnalyser();
			if (!borrowed) return;
			borrowed.fftSize = FFT_SIZE;
			borrowed.smoothingTimeConstant = 0.82;
			frequencyData = new Uint8Array(borrowed.frequencyBinCount) as Uint8Array<ArrayBuffer>;
			waveformData = new Uint8Array(borrowed.fftSize) as Uint8Array<ArrayBuffer>;
			analyser = borrowed;
		} catch (e) {
			console.warn('Audio visualizer unavailable:', e);
		}
	}

	function startVisualizerLoop(): void {
		if (!vizCanvas) return;
		if (!playbackVisualizerAllowed()) return;
		connectAnalyser();
		if (!analyser || !frequencyData || !waveformData) return;
		audioPlayer.resumeAudioGraph();
		vizColors = readVizColors();
		viz.startLoop(vizCanvas, analyser, frequencyData, waveformData, vizColors, (bass, energy) => {
			bassLevel = bass;
			energyLevel = energy;
		});
	}

	function stopVisualizerLoop(): void {
		if (!vizCanvas) return;
		viz.stopLoop(vizCanvas);
	}

	function handleVisibilityChange(): void {
		if (document.hidden) {
			stopVisualizerLoop();
			return;
		}
		if (isPlaying) startVisualizerLoop();
	}

	// The whole phone bar is a handle for Now Playing, except its transport:
	// a finger that lands on previous, play or next means that button.
	function startSwipe(e: PointerEvent): void {
		swipeOpenedNowPlaying = false;
		swipeStart = null;
		if (!mobileTransport || nowPlayingDisabled) return;
		if (phoneTransportControls?.contains(e.target as Node)) return;
		swipeStart = { pointerId: e.pointerId, x: e.clientX, y: e.clientY };
	}

	function endSwipe(e: PointerEvent): void {
		if (swipeStart?.pointerId !== e.pointerId) return;
		const rise = swipeStart.y - e.clientY;
		const drift = Math.abs(e.clientX - swipeStart.x);
		swipeStart = null;
		if (rise < NOW_PLAYING_SWIPE_RISE_PX || rise <= drift) return;
		swipeOpenedNowPlaying = true;
		onOpenNowPlaying();
	}

	function cancelSwipe(): void {
		swipeStart = null;
	}

	// A swipe that starts and ends on the title also clicks it, and that click
	// would put a docked panel the swipe just opened away again. A swipe can
	// also end with no click at all, so only a pointer's click (one that
	// counts taps) is taken for its end; a keyboard press always acts.
	function swallowClickEndingSwipe(e: MouseEvent): void {
		const endsSwipe = swipeOpenedNowPlaying && e.detail > 0;
		swipeOpenedNowPlaying = false;
		if (endsSwipe) e.stopPropagation();
	}

	function seekFromClick(e: MouseEvent, el?: HTMLElement): void {
		if (duration <= 0) return;
		const target = el ?? (e.currentTarget as HTMLElement);
		const rect = target.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		onSeek(ratio * duration);
	}

	function seekFromRange(e: Event): void {
		const target = e.currentTarget as HTMLInputElement;
		onSeek(Number(target.value));
	}

	onDestroy(() => {
		viz.destroy();
	});
</script>

{#snippet stepAndPlay()}
	<button
		class="nav-btn"
		data-hitbox={phoneHitbox}
		onclick={onPrev}
		disabled={!canPrev}
		aria-label="Previous"
		title="Previous"
	>
		<Icon name="skip-back" size={21} />
	</button>
	<button
		class="play-btn"
		class:loading={isLoading}
		class:playing={isPlaying}
		class:errored={isError}
		onclick={onTogglePlay}
		aria-label={isError
			? TRANSPORT_RETRY_LABEL
			: isPlaying
				? TRANSPORT_PAUSE_LABEL
				: TRANSPORT_PLAY_LABEL}
		title={isError && errorMsg ? errorMsg : ''}
	>
		<span class="play-btn-face" style={playFaceStyle}>
			{#if isLoading}<span class="spinner"></span>{:else if isError}<Icon
					name="refresh-cw"
					size={24}
				/>{:else}<Icon name={isPlaying ? 'pause' : 'play'} size={26} />{/if}
		</span>
	</button>
	<button
		class="nav-btn"
		data-hitbox={phoneHitbox}
		onclick={onNext}
		disabled={!canNext}
		aria-label="Next"
		title="Next"
	>
		<Icon name="skip-forward" size={21} />
	</button>
{/snippet}

<svelte:document
	onvisibilitychange={handleVisibilityChange}
	onpointerup={endSwipe}
	onpointercancel={cancelSwipe}
/>

<footer
	class="player-bar"
	class:now-playing-open={nowPlayingOpen}
	class:mobile-transport={mobileTransport}
	style={boxShadow}
	onpointerdown={startSwipe}
	onclickcapture={swallowClickEndingSwipe}
>
	<canvas class="viz-fullscreen" bind:this={vizCanvas}></canvas>
	<div class="mobile-progress" aria-hidden="true">
		<div class="mobile-progress-fill" style:width="{progressPercent}%"></div>
	</div>
	<div class="player-content">
		{#if mobileTransport}
			{#if nowPlayingDisabled}
				<div class="phone-side track-info" aria-live="polite">
					{@render trackInfo(trackTitleGlowStyle, null)}
				</div>
			{:else}
				<button
					bind:this={nowPlayingTrigger}
					class="phone-side track-info open-now-playing"
					onclick={onOpenNowPlaying}
					aria-label={nowPlayingTargetLabel}
					aria-describedby={nowPlayingTargetDescribedBy}
					aria-haspopup={nowPlayingDocked ? undefined : 'dialog'}
					aria-expanded={nowPlayingOpen}
					aria-live="polite"
				>
					{@render trackInfo(trackTitleGlowStyle, null)}
				</button>
			{/if}
			<div class="transport-controls" bind:this={phoneTransportControls}>
				{@render stepAndPlay()}
			</div>
			<!-- The empty right side is only a wider tap target for the same
				action, so keyboards and screen readers meet the one on the left.
				It is also the only room wide enough to say why playback stopped. -->
			{#if nowPlayingDisabled}
				<span class="phone-side"></span>
			{:else}
				<button
					class="phone-side open-now-playing"
					onclick={onOpenNowPlaying}
					tabindex="-1"
					aria-hidden="true"
				>
					{#if playbackFailure}<span class="phone-failure" id={phoneFailureId}
							>{playbackFailure}</span
						>{/if}
				</button>
			{/if}
		{:else}
			<div class="transport-controls">
				{#if onToggleShuffle}
					<button
						class="nav-btn shuffle-btn"
						class:on={shuffle}
						data-hitbox="frequent"
						onclick={onToggleShuffle}
						aria-pressed={shuffle}
						aria-label={shuffleLabel}
						title={shuffleLabel}
					>
						<Icon name="shuffle" size={18} />
					</button>
				{/if}
				{@render stepAndPlay()}
			</div>
			<div class="track-info" aria-live="polite">
				{@render trackInfo(trackTitleGlowStyle, playbackFailure)}
			</div>
			<div class="timeline">
				<span class="time">{formatTime(currentTime)}</span>
				<input
					class="timeline-range"
					style={`--progress: ${progressPercent}%`}
					type="range"
					min="0"
					max={duration || 0}
					step="0.1"
					value={duration > 0 ? currentTime : 0}
					oninput={seekFromRange}
					onclick={(e) => seekFromClick(e)}
					disabled={duration <= 0}
					aria-label="Seek playback"
				/>
				<span class="time">{formatTime(duration)}</span>
			</div>
			<button
				bind:this={nowPlayingTrigger}
				class="now-playing-btn"
				data-hitbox="frequent"
				onclick={onOpenNowPlaying}
				disabled={nowPlayingDisabled}
				aria-label={NOW_PLAYING_LABEL}
				aria-haspopup={nowPlayingDocked ? undefined : 'dialog'}
				aria-expanded={nowPlayingOpen}
			>
				<span>{NOW_PLAYING_LABEL}</span>
				<Icon name="chevron-up" size={16} />
			</button>
		{/if}
	</div>
</footer>

<style>
	.player-bar {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		height: var(--transport-bar-height);
		background: var(--card-bg);
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		padding: 10px 18px calc(10px + env(safe-area-inset-bottom, 0px));
		z-index: 100;
		overflow: hidden;
		transition: box-shadow 0.3s;
	}
	.player-bar.now-playing-open {
		overflow: visible;
	}
	.player-content {
		position: relative;
		z-index: 1;
		display: grid;
		grid-template-columns: auto minmax(120px, 240px) minmax(100px, 1fr) auto;
		align-items: center;
		gap: 14px;
		width: 100%;
		min-width: 0;
	}
	.transport-controls {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
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
		flex-shrink: 0;
		cursor: pointer;
		position: relative;
		transition:
			background 0.2s,
			border-color 0.3s,
			color 0.2s;
	}
	.play-btn-face {
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.play-btn:hover {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		border-color: transparent;
		color: #fff;
	}
	.play-btn.loading {
		border-color: var(--text-decoration);
	}
	.play-btn.playing {
		border-color: var(--accent);
	}
	.play-btn.errored {
		border-color: #d34;
		color: #d34;
	}
	@supports (animation-timeline: auto) or (background-clip: border-box) {
		@media (prefers-reduced-motion: no-preference) {
			.play-btn.playing {
				border-color: transparent;
				background-origin: border-box;
				background-clip: padding-box, border-box;
				background-image:
					linear-gradient(var(--header-bg), var(--header-bg)),
					conic-gradient(
						from var(--border-angle, 0deg),
						var(--primary),
						var(--accent),
						var(--primary)
					);
				animation: rotate-border 2s linear infinite;
			}
		}
	}
	@keyframes rotate-border {
		to {
			--border-angle: 360deg;
		}
	}
	@property --border-angle {
		syntax: '<angle>';
		initial-value: 0deg;
		inherits: false;
	}
	.spinner {
		width: 24px;
		height: 24px;
		border: 2px solid transparent;
		border-radius: 50%;
		background-origin: border-box;
		background-clip: content-box, border-box;
		background-image:
			linear-gradient(transparent, transparent),
			conic-gradient(var(--primary), var(--accent), var(--primary));
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.nav-btn {
		width: 44px;
		height: 44px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
		border-radius: 50%;
		color: var(--text-muted);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		flex-shrink: 0;
		transition:
			background 0.15s,
			border-color 0.15s,
			color 0.15s,
			opacity 0.15s;
	}
	.nav-btn:hover:not(:disabled) {
		color: var(--text);
		border-color: color-mix(in srgb, var(--primary) 65%, var(--border));
		background: color-mix(in srgb, var(--primary) 12%, var(--surface));
	}
	.nav-btn:disabled {
		color: var(--text-disabled);
		cursor: default;
		opacity: 0.3;
	}
	.shuffle-btn.on {
		color: var(--accent);
		border-color: var(--accent);
	}
	.track-info {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
		overflow: hidden;
	}
	.timeline {
		display: grid;
		grid-template-columns: auto minmax(80px, 1fr) auto;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	.time {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		color: var(--text-muted);
		min-width: 36px;
		text-align: center;
		flex-shrink: 0;
	}

	.timeline-range {
		--track-bg: color-mix(in srgb, var(--border) 45%, transparent);
		appearance: none;
		-webkit-appearance: none;
		width: 100%;
		height: 34px;
		background: transparent;
		cursor: pointer;
		accent-color: var(--accent);
	}
	.timeline-range:disabled {
		cursor: default;
		opacity: 0.45;
	}
	.timeline-range::-webkit-slider-runnable-track {
		height: 8px;
		border-radius: 999px;
		background: linear-gradient(
			90deg,
			var(--primary) 0%,
			var(--accent) var(--progress),
			var(--track-bg) var(--progress),
			var(--track-bg) 100%
		);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 55%, transparent);
	}
	.timeline-range::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid var(--card-bg);
		background: var(--text);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent);
		margin-top: -5px;
	}
	.timeline-range:hover:not(:disabled)::-webkit-slider-thumb {
		background: #fff;
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	.timeline-range::-moz-range-track {
		height: 8px;
		border-radius: 999px;
		background: var(--track-bg);
	}
	.timeline-range::-moz-range-progress {
		height: 8px;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--primary), var(--accent));
	}
	.timeline-range::-moz-range-thumb {
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 2px solid var(--card-bg);
		background: var(--text);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent);
	}
	.now-playing-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
		padding: 0.4rem 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
		white-space: nowrap;
	}
	.now-playing-btn:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}
	.now-playing-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.viz-fullscreen {
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		bottom: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		z-index: 0;
	}
	.mobile-progress {
		display: none;
	}
	.mobile-progress-fill {
		height: 100%;
		background: linear-gradient(90deg, var(--primary), var(--accent));
	}

	@media (max-width: 900px) {
		.player-bar {
			padding: 8px 10px calc(8px + env(safe-area-inset-bottom, 0px));
		}
		.player-content {
			grid-template-columns: auto minmax(80px, 1fr) minmax(90px, 1fr) auto;
			gap: 10px;
		}
		.nav-btn {
			width: 40px;
			height: 40px;
		}
		.play-btn {
			width: 56px;
			height: 56px;
		}
		.now-playing-btn span {
			display: none;
		}
	}

	/* The phone's mini player (#1003, frames C2/C3): cover and title, then
	   previous · play · next, then an empty side. Both sides take the same
	   share of the row, so play sits on its exact centre line, and both open
	   Now Playing. The sides run to the bar's edges and meet the transport
	   with no gap, so every pixel beside it is a target and the title gets all
	   the room play's centre line leaves it (#1067). The seek timeline and
	   shuffle live in Now Playing; the
	   decorative .mobile-progress line stands in for the timeline here.
	   `.mobile-transport` is set from `subscribeCompactLayout` (JS mirrors
	   the same media query so jsdom tests can drive it via data-pointer). */
	/* The browser must not take a swipe on the bar for a page scroll, or it
	   cancels the pointer before the swipe can open Now Playing. */
	.player-bar.mobile-transport {
		--phone-bar-edge: 14px;
		touch-action: none;
		overflow: visible;
		padding: 0 0 env(safe-area-inset-bottom, 0px);
	}
	.mobile-transport .mobile-progress {
		display: block;
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		height: 2px;
		background: color-mix(in srgb, var(--border) 45%, transparent);
		z-index: 2;
	}
	.mobile-transport .player-content {
		display: flex;
		align-items: stretch;
		gap: 0;
		height: 100%;
	}
	.phone-side {
		flex: 1 1 0;
		min-width: 0;
	}
	.phone-side:first-child {
		padding-left: var(--phone-bar-edge);
	}
	.phone-side:last-child {
		padding-right: var(--phone-bar-edge);
	}
	.phone-failure {
		display: block;
		padding-left: 8px;
		font-size: 0.73rem;
		line-height: 1.25;
		color: #d34;
		overflow: hidden;
	}
	.open-now-playing {
		margin: 0;
		padding: 0;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.mobile-transport .transport-controls {
		flex: none;
	}
	.mobile-transport .nav-btn {
		width: 44px;
		height: 44px;
		border: none;
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text);
	}
	.mobile-transport .play-btn,
	.mobile-transport .play-btn.playing {
		width: 48px;
		height: 48px;
		border: none;
		background: var(--primary);
		color: #fff;
		animation: none;
	}
	.mobile-transport .play-btn.errored {
		background: #d34;
	}
	.mobile-transport .play-btn-face {
		transform: none !important;
	}
	.mobile-transport .spinner {
		background-image:
			linear-gradient(transparent, transparent), conic-gradient(#fff, transparent, #fff);
	}
</style>
