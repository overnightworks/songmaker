<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		playingGeneration,
		playback,
		playbackTime,
		playbackDuration,
		navigateToPlaying,
		isAudioPlaying,
		requestTogglePlay,
		playNextGeneration,
		playPrevGeneration,
		playNextSong,
		playPrevSong,
		canPlayPrevGen,
		canPlayNextGen,
		canPlayPrevSong,
		canPlayNextSong
	} from '$lib/stores/player';
	import { formatTime } from '$lib/utils/format';
	import WaveSurfer from 'wavesurfer.js';

	const FFT_SIZE = 1024;
	const MAX_PARTICLES = 150;
	const BASS_THRESHOLD = 0.35;

	interface Particle {
		x: number; y: number;
		vx: number; vy: number;
		life: number; decay: number;
		r: number; g: number; b: number;
		size: number;
	}

	let waveContainer: HTMLDivElement | undefined = $state();
	let vizCanvas: HTMLCanvasElement | undefined = $state();
	let wavesurfer: WaveSurfer | undefined = $state();
	let isPlaying = $state(false);
	let isLoading = $state(false);
	const toggleRequest = $derived($requestTogglePlay);
	let currentTime = $state(0);
	let duration = $state(0);

	const gen = $derived($playingGeneration);
	const pb = $derived($playback);
	const prevGen = $derived($canPlayPrevGen);
	const nextGen = $derived($canPlayNextGen);
	const prevSong = $derived($canPlayPrevSong);
	const nextSong = $derived($canPlayNextSong);

	let prevFile = $state('');

	let audioCtx: AudioContext | undefined;
	let analyser: AnalyserNode | undefined;
	let sourceNode: MediaElementAudioSourceNode | undefined;
	let animFrameId: number | undefined;
	let frequencyData: Uint8Array<ArrayBuffer> | undefined;
	let waveformData: Uint8Array<ArrayBuffer> | undefined;
	let smoothedFreq: Float32Array = new Float32Array(FFT_SIZE / 2);
	let vizOpacity = 0;
	let particles: Particle[] = [];
	let prevBassHit = false;
	let phase = 0;

	function makeProgressGradient(): CanvasGradient {
		const ctx = document.createElement('canvas').getContext('2d') as CanvasRenderingContext2D;
		const w = waveContainer?.clientWidth ?? 300;
		const gradient = ctx.createLinearGradient(0, 0, w, 0);
		gradient.addColorStop(0, 'rgba(42, 26, 46, 0.3)');
		gradient.addColorStop(1, 'rgba(42, 26, 46, 0.15)');
		return gradient;
	}

	function connectAnalyser(): void {
		if (!wavesurfer || audioCtx) return;
		try {
			const media = wavesurfer.getMediaElement();
			if (!media) return;
			audioCtx = new AudioContext();
			analyser = audioCtx.createAnalyser();
			analyser.fftSize = FFT_SIZE;
			analyser.smoothingTimeConstant = 0.82;
			sourceNode = audioCtx.createMediaElementSource(media);
			sourceNode.connect(analyser);
			analyser.connect(audioCtx.destination);
			frequencyData = new Uint8Array(analyser.frequencyBinCount) as Uint8Array<ArrayBuffer>;
			waveformData = new Uint8Array(analyser.fftSize) as Uint8Array<ArrayBuffer>;
		} catch { /* Already connected */ }
	}

	function drawVisualizer(): void {
		if (!vizCanvas || !analyser || !frequencyData || !waveformData) return;
		const ctx = vizCanvas.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;
		const rect = vizCanvas.getBoundingClientRect();
		const w = rect.width;
		const h = rect.height;

		if (vizCanvas.width !== Math.round(w * dpr) || vizCanvas.height !== Math.round(h * dpr)) {
			vizCanvas.width = Math.round(w * dpr);
			vizCanvas.height = Math.round(h * dpr);
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		}

		ctx.clearRect(0, 0, w, h);
		analyser.getByteFrequencyData(frequencyData);
		analyser.getByteTimeDomainData(waveformData);

		const binCount = frequencyData.length;
		for (let i = 0; i < binCount; i++) {
			smoothedFreq[i] = smoothedFreq[i] * 0.8 + (frequencyData[i] / 255) * 0.2;
		}

		if (vizOpacity < 1) vizOpacity = Math.min(1, vizOpacity + 0.05);
		phase += 0.02;

		const cy = h / 2;

		let bassE = 0, midE = 0, highE = 0, totalE = 0;
		const bassEnd = Math.floor(binCount * 0.08);
		const midEnd = Math.floor(binCount * 0.4);
		for (let i = 0; i < binCount; i++) {
			totalE += smoothedFreq[i];
			if (i < bassEnd) bassE += smoothedFreq[i];
			else if (i < midEnd) midE += smoothedFreq[i];
			else highE += smoothedFreq[i];
		}
		bassE /= bassEnd;
		midE /= (midEnd - bassEnd);
		highE /= (binCount - midEnd);
		const avgE = totalE / binCount;

		ctx.globalAlpha = vizOpacity;

		const barCount = Math.min(binCount, Math.floor(w / 3));
		const barW = w / barCount;

		for (let i = 0; i < barCount; i++) {
			const freqIdx = Math.floor((i / barCount) * binCount * 0.7);
			const val = smoothedFreq[freqIdx];
			const barH = val * h * 0.85;
			const x = i * barW;

			const t = i / barCount;
			const r = Math.round(255 - t * 120);
			const g = Math.round(20 + t * 30);
			const b = Math.round(32 + t * 210);
			const alpha = 0.03 + val * 0.12;

			ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
			ctx.fillRect(x, cy - barH / 2, barW - 0.5, barH);
		}

		const waveLen = waveformData.length;
		ctx.beginPath();
		ctx.strokeStyle = `rgba(255, 50, 32, ${0.15 + avgE * 0.35})`;
		ctx.lineWidth = 1 + avgE * 1.5;
		for (let i = 0; i < waveLen; i++) {
			const x = (i / waveLen) * w;
			const v = (waveformData[i] / 128 - 1);
			const y = cy + v * h * (0.3 + avgE * 0.4);
			if (i === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.stroke();

		if (avgE > 0.15) {
			ctx.save();
			ctx.shadowColor = `rgba(255, 50, 32, ${avgE * 0.4})`;
			ctx.shadowBlur = 4 + avgE * 8;
			ctx.stroke();
			ctx.restore();
		}

		ctx.beginPath();
		ctx.strokeStyle = `rgba(160, 32, 240, ${0.1 + midE * 0.3})`;
		ctx.lineWidth = 0.8 + midE * 1;
		for (let i = 0; i < waveLen; i++) {
			const x = (i / waveLen) * w;
			const v = (waveformData[i] / 128 - 1);
			const offset = Math.sin(phase * 3 + i * 0.02) * midE * 8;
			const y = cy + v * h * (0.15 + midE * 0.25) + offset;
			if (i === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.stroke();

		const ringCount = 6;
		for (let r2 = 0; r2 < ringCount; r2++) {
			const ringT = r2 / ringCount;
			const baseRadius = 8 + r2 * (Math.min(w, h) * 0.06);
			const energy = r2 < 2 ? bassE : r2 < 4 ? midE : highE;

			const points = 80;
			ctx.beginPath();

			const rr = Math.round(255 - ringT * 140);
			const rg = Math.round(15 + ringT * 35);
			const rb = Math.round(32 + ringT * 220);
			ctx.strokeStyle = `rgba(${rr}, ${rg}, ${rb}, ${0.06 + energy * 0.35})`;
			ctx.lineWidth = 0.8 + energy * 1.5;

			for (let p = 0; p <= points; p++) {
				const a = (p / points) * Math.PI * 2;
				const freqI = Math.floor((p / points) * binCount * 0.6);
				const fv = smoothedFreq[freqI];
				const pulse = baseRadius + fv * 15 + energy * 8;
				const x = w / 2 + Math.cos(a + phase * (1 + r2 * 0.3)) * pulse;
				const y = cy + Math.sin(a + phase * (1 + r2 * 0.3)) * pulse * 0.6;
				if (p === 0) ctx.moveTo(x, y);
				else ctx.lineTo(x, y);
			}
			ctx.closePath();
			ctx.stroke();

			if (energy > 0.3) {
				ctx.save();
				ctx.shadowColor = `rgba(${rr}, ${rg}, ${rb}, ${(energy - 0.3) * 0.5})`;
				ctx.shadowBlur = 4 + energy * 10;
				ctx.stroke();
				ctx.restore();
			}
		}

		const bassHit = bassE > BASS_THRESHOLD;
		if (bassHit && !prevBassHit) {
			for (let i = 0; i < Math.floor(bassE * 20); i++) {
				if (particles.length >= MAX_PARTICLES) break;
				const angle = Math.random() * Math.PI * 2;
				const speed = 2 + bassE * 8;
				const dist = 10 + Math.random() * 30;
				particles.push({
					x: w / 2 + Math.cos(angle) * dist,
					y: cy + Math.sin(angle) * dist * 0.6,
					vx: Math.cos(angle) * speed * (0.5 + Math.random()),
					vy: Math.sin(angle) * speed * 0.6 * (0.5 + Math.random()),
					life: 1, decay: 0.01 + Math.random() * 0.02,
					r: Math.round(200 + Math.random() * 55),
					g: Math.round(20 + Math.random() * 30),
					b: Math.round(32 + Math.random() * 100),
					size: 1.5 + Math.random() * 3
				});
			}
		}
		prevBassHit = bassHit;

		for (let i = particles.length - 1; i >= 0; i--) {
			const p = particles[i];
			p.x += p.vx; p.y += p.vy;
			p.vx *= 0.96; p.vy *= 0.96;
			p.life -= p.decay;
			if (p.life <= 0) { particles.splice(i, 1); continue; }
			const a = p.life * 0.8;
			ctx.save();
			ctx.globalAlpha = a * vizOpacity;
			ctx.shadowColor = `rgba(${p.r}, ${p.g}, ${p.b}, ${a * 0.6})`;
			ctx.shadowBlur = 4 + p.size * 2;
			ctx.fillStyle = `rgba(${p.r}, ${p.g}, ${p.b}, ${a})`;
			ctx.beginPath();
			ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
			ctx.fill();
			ctx.restore();
		}

		const progressT = duration > 0 ? currentTime / duration : 0;
		if (progressT > 0) {
			const px = progressT * w;
			ctx.fillStyle = `rgba(160, 32, 240, ${0.08 + avgE * 0.15})`;
			ctx.fillRect(0, h - 2, px, 2);
			const dot = ctx.createRadialGradient(px, h - 2, 0, px, h - 2, 6);
			dot.addColorStop(0, `rgba(160, 32, 240, ${0.5 + avgE * 0.4})`);
			dot.addColorStop(1, 'transparent');
			ctx.fillStyle = dot;
			ctx.fillRect(px - 6, h - 8, 12, 12);
		}

		ctx.globalAlpha = 1;
		animFrameId = requestAnimationFrame(drawVisualizer);
	}

	function startVisualizerLoop(): void {
		if (animFrameId) return;
		if (!audioCtx) connectAnalyser();
		if (audioCtx?.state === 'suspended') audioCtx.resume();
		vizOpacity = 0;
		drawVisualizer();
	}

	function stopVisualizerLoop(): void {
		if (animFrameId) { cancelAnimationFrame(animFrameId); animFrameId = undefined; }
		fadeOut();
	}

	function fadeOut(): void {
		if (!vizCanvas) return;
		const ctx = vizCanvas.getContext('2d');
		if (!ctx) return;
		function fade(): void {
			if (!vizCanvas || !ctx) return;
			vizOpacity *= 0.9;
			for (let i = 0; i < smoothedFreq.length; i++) smoothedFreq[i] *= 0.9;
			for (let i = particles.length - 1; i >= 0; i--) {
				particles[i].life -= 0.04;
				if (particles[i].life <= 0) particles.splice(i, 1);
			}
			if (vizOpacity < 0.01) {
				ctx.clearRect(0, 0, vizCanvas.width, vizCanvas.height);
				smoothedFreq.fill(0); vizOpacity = 0; particles = [];
				return;
			}
			requestAnimationFrame(fade);
		}
		requestAnimationFrame(fade);
	}

	function handleCanvasClick(e: MouseEvent): void {
		if (!vizCanvas || !wavesurfer || duration <= 0) return;
		const rect = vizCanvas.getBoundingClientRect();
		wavesurfer.seekTo(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)));
	}

	function createWavesurfer(): void {
		if (!waveContainer) return;
		wavesurfer?.destroy();
		wavesurfer = WaveSurfer.create({
			container: waveContainer, height: 0,
			waveColor: 'transparent', progressColor: 'transparent',
			cursorColor: 'transparent', cursorWidth: 0,
			normalize: true, hideScrollbar: true, interact: false
		});
		wavesurfer.on('loading', () => { isLoading = true; });
		wavesurfer.on('ready', () => {
			isLoading = false; duration = wavesurfer?.getDuration() ?? 0;
			playbackDuration.set(duration); connectAnalyser();
		});
		wavesurfer.on('timeupdate', (time: number) => { currentTime = time; playbackTime.set(time); });
		wavesurfer.on('finish', handleEnded);
		wavesurfer.on('play', () => { isPlaying = true; isAudioPlaying.set(true); startVisualizerLoop(); });
		wavesurfer.on('pause', () => { isPlaying = false; isAudioPlaying.set(false); stopVisualizerLoop(); });
	}

	$effect(() => {
		if (!gen || !waveContainer) return;
		if (gen.mp3_path !== prevFile) {
			prevFile = gen.mp3_path;
			isLoading = true;
			if (!wavesurfer) createWavesurfer();
			try { wavesurfer?.load(`/audio/${gen.mp3_path}`); } catch { /* harmless */ }
			if (pb?.autoplay) { wavesurfer?.once('ready', () => wavesurfer?.play()); }
		}
	});

	let prevToggle = 0;
	$effect(() => {
		if (toggleRequest !== prevToggle) { prevToggle = toggleRequest; if (wavesurfer) wavesurfer.playPause(); }
	});

	onDestroy(() => { if (animFrameId) cancelAnimationFrame(animFrameId); wavesurfer?.destroy(); if (audioCtx) audioCtx.close(); });

	function togglePlay(): void { if (!gen || !wavesurfer || isLoading) return; wavesurfer.playPause(); }

	function handleEnded(): void {
		isPlaying = false; isAudioPlaying.set(false);
		stopVisualizerLoop(); playNextGeneration();
	}
</script>

<footer class="player-bar">
	<div class="player-controls">
		<button class="nav-btn" onclick={playPrevSong} disabled={!prevSong} aria-label="Previous song" title="Previous song"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><rect x="3" y="5" width="3" height="14"/><polygon points="20,5 9,12 20,19"/></svg></button>
		<button class="nav-btn" onclick={playPrevGeneration} disabled={!prevGen} aria-label="Previous generation" title="Previous generation"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="12,5 2,12 12,19"/><polygon points="22,5 12,12 22,19"/></svg></button>
		<button class="play-btn" class:loading={isLoading} class:playing={isPlaying} onclick={togglePlay} disabled={isLoading} aria-label={isPlaying ? 'Pause' : 'Play'}>
			{#if isLoading}<span class="spinner"></span>{:else}{isPlaying ? '⏸' : '▶'}{/if}
		</button>
		<button class="nav-btn" onclick={playNextGeneration} disabled={!nextGen} aria-label="Next generation" title="Next generation"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="2,5 12,12 2,19"/><polygon points="12,5 22,12 12,19"/></svg></button>
		<button class="nav-btn" onclick={playNextSong} disabled={!nextSong} aria-label="Next song" title="Next song"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="4,5 15,12 4,19"/><rect x="18" y="5" width="3" height="14"/></svg></button>
	</div>
	<button class="track-info" onclick={navigateToPlaying} aria-label="Go to playing song">
		{#if pb}
			<span class="track-title" class:glowing={isPlaying}>{pb.songTitle}</span>
			<span class="track-detail">{pb.artist} · gen{gen?.generation_number}{#if isLoading}<span class="loading-text">Loading...</span>{/if}</span>
		{/if}
	</button>
	<span class="time">{formatTime(currentTime)}</span>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="viz-area" onclick={handleCanvasClick}>
		<div class="wave-hidden" bind:this={waveContainer}></div>
		<canvas class="viz-canvas" bind:this={vizCanvas}></canvas>
	</div>
	<span class="time">{formatTime(duration)}</span>
</footer>

<style>
	.player-bar {
		position: fixed; bottom: 0; left: 0; right: 0;
		height: var(--player-height); background: #0a0a0a;
		border-top: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex; align-items: center; gap: 12px; padding: 0 16px; z-index: 100;
	}
	.player-controls { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
	.play-btn {
		width: 40px; height: 40px; border-radius: 50%;
		border: 2px solid var(--primary); background: transparent;
		color: var(--primary); font-size: 16px;
		display: flex; align-items: center; justify-content: center;
		flex-shrink: 0; cursor: pointer; position: relative; transition: border-color 0.3s;
	}
	.play-btn:hover:not(:disabled) { background: linear-gradient(135deg, var(--primary), var(--accent)); border-color: transparent; color: #fff; }
	.play-btn:disabled { opacity: 0.5; cursor: wait; }
	.play-btn.loading { border-color: var(--text-dim); }
	@media (prefers-reduced-motion: no-preference) {
		.play-btn.playing {
			border-color: transparent; background-origin: border-box;
			background-clip: padding-box, border-box;
			background-image: linear-gradient(#0a0a0a, #0a0a0a),
				conic-gradient(from var(--border-angle, 0deg), var(--primary), var(--accent), var(--primary));
			animation: rotate-border 2s linear infinite;
		}
	}
	@keyframes rotate-border { to { --border-angle: 360deg; } }
	@property --border-angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
	.spinner {
		width: 16px; height: 16px; border: 2px solid transparent; border-radius: 50%;
		background-origin: border-box; background-clip: content-box, border-box;
		background-image: linear-gradient(transparent, transparent), conic-gradient(var(--primary), var(--accent), var(--primary));
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin { to { transform: rotate(360deg); } }
	.nav-btn {
		background: none; border: none; color: var(--text-muted); font-size: 14px;
		cursor: pointer; padding: 6px; display: flex; align-items: center;
		min-width: 32px; min-height: 32px; justify-content: center;
	}
	.nav-btn:hover:not(:disabled) { color: var(--text); }
	.nav-btn:disabled { color: var(--text-dim); cursor: default; opacity: 0.3; }
	.track-info {
		display: flex; flex-direction: column; min-width: 100px; max-width: 200px;
		overflow: hidden; background: none; border: none; cursor: pointer;
		text-align: left; padding: 4px 8px; border-radius: 4px; flex-shrink: 0;
	}
	.track-info:hover { background: var(--surface-hover); }
	.track-title {
		font-family: var(--font-display); font-size: 13px; color: #fff;
		text-transform: uppercase; letter-spacing: 1px;
		white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: text-shadow 0.3s;
	}
	@media (prefers-reduced-motion: no-preference) {
		.track-title.glowing { text-shadow: 0 0 8px rgba(160, 32, 240, 0.5), 0 0 16px rgba(160, 32, 240, 0.2); }
	}
	.track-detail { font-size: 10px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.loading-text { color: var(--primary); margin-left: 4px; }
	.time { font-family: var(--font-display); font-size: 12px; color: var(--text-muted); min-width: 36px; text-align: center; flex-shrink: 0; }
	.viz-area { flex: 1; min-width: 80px; height: 52px; position: relative; cursor: pointer; }
	.wave-hidden { position: absolute; width: 0; height: 0; overflow: hidden; pointer-events: none; }
	.viz-canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
	@media (max-width: 768px) {
		.player-bar { gap: 8px; padding: 0 8px; }
		.track-info { display: none; }
		.nav-btn { font-size: 12px; min-width: 28px; min-height: 28px; padding: 4px; }
		.time { font-size: 10px; min-width: 28px; }
	}
</style>
