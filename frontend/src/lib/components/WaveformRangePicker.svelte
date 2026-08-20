<script lang="ts">
	import { onMount } from 'svelte';

	interface Props {
		audioUrl: string;
		duration: number;
		startPercent: number;
		endPercent: number;
		onchange: (start: number, end: number) => void;
	}

	let { audioUrl, duration, startPercent, endPercent, onchange }: Props = $props();

	let canvas: HTMLCanvasElement | undefined = $state();
	let container: HTMLDivElement | undefined = $state();
	let audioEl: HTMLAudioElement | undefined = $state();
	let peaks: number[] = $state([]);
	let dragging = $state<'start' | 'end' | null>(null);
	let containerRect = $state<DOMRect | null>(null);
	let playing = $state(false);
	let playbackRaf = 0;

	const BAR_COUNT = 300;
	const LATENT_FRAME_SECONDS = 0.04;

	function formatTime(seconds: number): string {
		const m = Math.floor(seconds / 60);
		const s = seconds % 60;
		const whole = Math.floor(s);
		const ms = Math.round((s - whole) * 100);
		return `${m}:${whole.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
	}

	const startTime = $derived(formatTime(startPercent * duration));
	const endTime = $derived(formatTime(endPercent * duration));

	onMount(() => {
		loadAudio();
	});

	async function loadAudio(): Promise<void> {
		try {
			const response = await fetch(audioUrl);
			const buffer = await response.arrayBuffer();
			const audioCtx = new AudioContext();
			const decoded = await audioCtx.decodeAudioData(buffer);
			const channelData = decoded.getChannelData(0);

			const blockSize = Math.floor(channelData.length / BAR_COUNT);
			const newPeaks: number[] = [];
			for (let i = 0; i < BAR_COUNT; i++) {
				let max = 0;
				const start = i * blockSize;
				for (let j = start; j < start + blockSize && j < channelData.length; j++) {
					const abs = Math.abs(channelData[j]);
					if (abs > max) max = abs;
				}
				newPeaks.push(max);
			}

			const peakMax = Math.max(...newPeaks, 0.01);
			peaks = newPeaks.map((p) => p / peakMax);

			await audioCtx.close();
			drawWaveform();
		} catch {
			peaks = Array(BAR_COUNT).fill(0.1);
			drawWaveform();
		}
	}

	$effect(() => {
		if (peaks.length > 0) {
			drawWaveform();
		}
	});

	function drawWaveform(): void {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;

		canvas.width = canvas.clientWidth * dpr;
		canvas.height = canvas.clientHeight * dpr;
		ctx.scale(dpr, dpr);

		const cw = canvas.clientWidth;
		const ch = canvas.clientHeight;
		ctx.clearRect(0, 0, cw, ch);

		const barWidth = cw / BAR_COUNT;
		const startX = startPercent * cw;
		const endX = endPercent * cw;

		for (let i = 0; i < peaks.length; i++) {
			const x = i * barWidth;
			const barH = Math.max(2, peaks[i] * (ch - 4));
			const y = (ch - barH) / 2;
			const inRange = x >= startX && x <= endX;

			ctx.fillStyle = inRange ? 'rgba(160, 32, 240, 0.8)' : 'rgba(160, 32, 240, 0.2)';
			ctx.fillRect(x + 0.5, y, Math.max(1, barWidth - 1), barH);
		}
	}

	function getPercent(clientX: number): number {
		if (!containerRect) return 0;
		const x = clientX - containerRect.left;
		return Math.max(0, Math.min(1, x / containerRect.width));
	}

	function onPointerDown(e: PointerEvent, handle: 'start' | 'end'): void {
		e.preventDefault();
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
		dragging = handle;
		containerRect = container?.getBoundingClientRect() ?? null;
	}

	function onPointerMove(e: PointerEvent): void {
		if (!dragging) return;
		const pct = getPercent(e.clientX);
		const stepSize = LATENT_FRAME_SECONDS / duration;
		const snap = Math.round(pct / stepSize) * stepSize;
		if (dragging === 'start') {
			const newStart = Math.min(snap, endPercent - stepSize);
			onchange(Math.max(0, newStart), endPercent);
		} else {
			const newEnd = Math.max(snap, startPercent + stepSize);
			onchange(startPercent, Math.min(1, newEnd));
		}
	}

	function onPointerUp(): void {
		dragging = null;
	}

	function togglePreview(): void {
		if (playing) {
			stopPreview();
			return;
		}
		if (!audioEl) return;
		audioEl.currentTime = startPercent * duration;
		audioEl.play();
		playing = true;
		scheduleStop();
	}

	function scheduleStop(): void {
		cancelAnimationFrame(playbackRaf);
		playbackRaf = requestAnimationFrame(() => {
			if (!audioEl || !playing) return;
			if (audioEl.currentTime >= endPercent * duration) {
				stopPreview();
				return;
			}
			scheduleStop();
		});
	}

	function stopPreview(): void {
		cancelAnimationFrame(playbackRaf);
		if (audioEl) {
			audioEl.pause();
		}
		playing = false;
	}
</script>

<div class="waveform-picker" bind:this={container}>
	<canvas class="waveform-canvas" bind:this={canvas}></canvas>
	<div
		class="handle handle-start"
		style="left: {startPercent * 100}%"
		onpointerdown={(e) => onPointerDown(e, 'start')}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		role="slider"
		aria-label="Repaint start"
		aria-valuenow={Math.round(startPercent * 100)}
		tabindex="0"
	></div>
	<div
		class="handle handle-end"
		style="left: {endPercent * 100}%"
		onpointerdown={(e) => onPointerDown(e, 'end')}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		role="slider"
		aria-label="Repaint end"
		aria-valuenow={Math.round(endPercent * 100)}
		tabindex="0"
	></div>
	<audio bind:this={audioEl} src={audioUrl} preload="auto" onended={stopPreview}></audio>
	<div class="time-display">
		<span>{startTime}</span>
		<button class="preview-btn" onclick={togglePreview} title="Preview selected range">
			{playing ? '\u25A0' : '\u25B6'}
		</button>
		<span>{endTime}</span>
	</div>
</div>

<style>
	.waveform-picker {
		position: relative;
		padding-bottom: 1.2rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.4rem 0.4rem 1.4rem;
	}

	.waveform-canvas {
		width: 100%;
		height: 64px;
		display: block;
		border-radius: 3px;
	}

	.handle {
		position: absolute;
		top: 0.4rem;
		width: 24px;
		height: 64px;
		transform: translateX(-50%);
		cursor: ew-resize;
		touch-action: none;
		z-index: 1;
	}

	.handle::before {
		content: '';
		position: absolute;
		top: 0;
		left: 50%;
		transform: translateX(-50%);
		width: 4px;
		height: 100%;
		background: #fff;
		border-radius: 2px;
		box-shadow: 0 0 6px rgba(160, 32, 240, 0.8);
	}

	.handle::after {
		content: '';
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: 12px;
		height: 20px;
		background: #fff;
		border-radius: 3px;
		border: 2px solid var(--accent);
	}

	.handle:hover::before,
	.handle:active::before {
		width: 5px;
		box-shadow: 0 0 12px rgba(160, 32, 240, 1);
	}

	@media (pointer: coarse) {
		.handle {
			width: 44px;
		}
	}

	.time-display {
		position: absolute;
		bottom: 0.2rem;
		left: 0.4rem;
		right: 0.4rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.7rem;
		color: var(--text-subtle);
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.preview-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-subtle);
		cursor: pointer;
		font-size: 0.65rem;
		padding: 0 0.35rem;
		line-height: 1.4;
	}

	.preview-btn:hover {
		color: var(--accent);
		border-color: var(--accent);
	}
</style>
