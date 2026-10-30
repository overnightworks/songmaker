<script lang="ts">
	import { SEEK_PLAYBACK_LABEL, seekPositionLabel } from '#lib/constants.ts';

	interface Props {
		currentTime: number;
		duration: number;
		formatTime: (seconds: number) => string;
		onSeek: (seconds: number) => void;
		// 'full' is the full player's finger-sized band; 'compact' fits the
		// desktop player bar's row.
		size: 'full' | 'compact';
	}

	let { currentTime, duration, formatTime, onSeek, size }: Props = $props();

	// A key press moves the song far enough to hear the difference: an arrow
	// by a few seconds, a page key by about a verse.
	const KEY_STEP_SECONDS = 5;
	const PAGE_STEP_SECONDS = 30;
	// The range's own step only sets how finely its value holds the position;
	// a coarser one would round the position it reports to that grid.
	const POSITION_STEP_SECONDS = 0.1;

	let band: HTMLDivElement | undefined = $state();
	// The pointer that holds the line, and where it would land. The song
	// itself only moves on release, so dragging never makes it stutter.
	let dragPointerId: number | null = null;
	let dragRatio: number | null = $state(null);

	const seekable = $derived(duration > 0);
	const playedRatio = $derived(seekable ? clampRatio(currentTime / duration) : 0);
	const shownRatio = $derived(dragRatio ?? playedRatio);
	const valueText = $derived(seekPositionLabel(formatTime(currentTime), formatTime(duration)));

	function clampRatio(ratio: number): number {
		return Math.max(0, Math.min(1, ratio));
	}

	function ratioAt(clientX: number, line: HTMLElement): number {
		const rect = line.getBoundingClientRect();
		return clampRatio((clientX - rect.left) / rect.width);
	}

	// A press anywhere on the band takes the line there, so a tap jumps
	// without first finding the knob -- which a native range on iOS demands.
	function startDrag(e: PointerEvent): void {
		if (!seekable || !band || e.button !== 0 || dragPointerId !== null) return;
		e.preventDefault();
		band.setPointerCapture(e.pointerId);
		dragPointerId = e.pointerId;
		dragRatio = ratioAt(e.clientX, band);
	}

	function moveDrag(e: PointerEvent): void {
		if (e.pointerId !== dragPointerId || !band) return;
		dragRatio = ratioAt(e.clientX, band);
	}

	function endDrag(e: PointerEvent): void {
		if (e.pointerId !== dragPointerId || !band) return;
		const landing = ratioAt(e.clientX, band) * duration;
		cancelDrag();
		onSeek(landing);
	}

	function cancelDrag(): void {
		dragPointerId = null;
		dragRatio = null;
	}

	function keyLanding(key: string): number | null {
		switch (key) {
			case 'ArrowRight':
			case 'ArrowUp':
				return currentTime + KEY_STEP_SECONDS;
			case 'ArrowLeft':
			case 'ArrowDown':
				return currentTime - KEY_STEP_SECONDS;
			case 'PageUp':
				return currentTime + PAGE_STEP_SECONDS;
			case 'PageDown':
				return currentTime - PAGE_STEP_SECONDS;
			case 'Home':
				return 0;
			case 'End':
				return duration;
			default:
				return null;
		}
	}

	// The range input stays the keyboard's and the screen reader's way in.
	// Keys step from where the song is rather than from the range's rounded
	// value, and each step seeks at once.
	function seekFromKey(e: KeyboardEvent): void {
		const landing = keyLanding(e.key);
		if (landing === null) return;
		e.preventDefault();
		onSeek(Math.max(0, Math.min(duration, landing)));
	}

	// A screen reader that moves the range itself seeks wherever it set it.
	function seekFromInput(e: Event): void {
		onSeek(Number((e.currentTarget as HTMLInputElement).value));
	}
</script>

<div
	bind:this={band}
	class="seek {size}"
	class:dragging={dragRatio !== null}
	class:disabled={!seekable}
	style:--seek-ratio={shownRatio}
	role="presentation"
	onpointerdown={startDrag}
	onpointermove={moveDrag}
	onpointerup={endDrag}
	onpointercancel={cancelDrag}
>
	<input
		class="seek-input"
		type="range"
		min="0"
		max={duration || 0}
		step={POSITION_STEP_SECONDS}
		value={seekable ? currentTime : 0}
		onkeydown={seekFromKey}
		oninput={seekFromInput}
		disabled={!seekable}
		aria-label={SEEK_PLAYBACK_LABEL}
		aria-valuetext={valueText}
	/>
	<span class="seek-line" aria-hidden="true"><span class="seek-played"></span></span>
	<span class="seek-knob" aria-hidden="true"></span>
	{#if dragRatio !== null}
		<span class="seek-time" aria-hidden="true">{formatTime(dragRatio * duration)}</span>
	{/if}
</div>

<style>
	.seek {
		--seek-band: 48px;
		--seek-line: 6px;
		--seek-knob: 22px;
		--seek-knob-dragging: 28px;
		--seek-time-gap: 8px;
		position: relative;
		width: 100%;
		height: var(--seek-band);
		cursor: pointer;
		/* The band is the finger's: a drag on it moves the song, never the page. */
		touch-action: none;
		user-select: none;
		-webkit-user-select: none;
	}
	.seek.compact {
		--seek-band: 34px;
		--seek-line: 8px;
		--seek-knob: 18px;
		--seek-knob-dragging: 22px;
		--seek-time-gap: 2px;
	}
	.seek.disabled {
		cursor: default;
		opacity: 0.45;
	}
	.seek-input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		pointer-events: none;
	}
	.seek-line {
		position: absolute;
		left: 0;
		right: 0;
		top: 50%;
		height: var(--seek-line);
		transform: translateY(-50%);
		border-radius: var(--seek-line);
		overflow: hidden;
		background: color-mix(in srgb, var(--border) 45%, transparent);
	}
	.seek-played {
		display: block;
		width: calc(var(--seek-ratio) * 100%);
		height: 100%;
		background: var(--accent);
	}
	.seek-knob {
		position: absolute;
		top: 50%;
		left: calc(var(--seek-ratio) * 100%);
		width: var(--seek-knob);
		height: var(--seek-knob);
		transform: translate(-50%, -50%);
		border: 2px solid var(--bg);
		border-radius: 50%;
		background: var(--text);
	}
	.seek.dragging .seek-knob {
		width: var(--seek-knob-dragging);
		height: var(--seek-knob-dragging);
	}
	.seek-input:focus-visible ~ .seek-knob {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.seek-time {
		position: absolute;
		bottom: calc(100% + var(--seek-time-gap));
		left: calc(var(--seek-ratio) * 100%);
		transform: translateX(-50%);
		padding: 0.25rem 0.5rem;
		border-radius: var(--btn-radius-sm);
		background: var(--text);
		color: var(--bg);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		line-height: 1;
		white-space: nowrap;
		pointer-events: none;
	}
	@media (prefers-reduced-motion: no-preference) {
		.seek-knob {
			transition:
				width 0.12s ease,
				height 0.12s ease;
		}
	}
</style>
