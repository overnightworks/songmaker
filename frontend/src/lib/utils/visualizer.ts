export const FFT_SIZE = 1024;
const MAX_PARTICLES = 150;
const BASS_THRESHOLD = 0.35;

export function playbackVisualizerAllowed(): boolean {
	if (typeof window === 'undefined' || typeof document === 'undefined') return false;
	if (document.hidden || document.documentElement.dataset.pointer === 'coarse') return false;
	return (
		!window.matchMedia('(max-width: 640px)').matches &&
		!window.matchMedia('(any-pointer: coarse)').matches
	);
}

export interface Particle {
	x: number;
	y: number;
	vx: number;
	vy: number;
	life: number;
	decay: number;
	r: number;
	g: number;
	b: number;
	size: number;
}

export interface VizColors {
	pr: number;
	pg: number;
	pb: number;
	ar: number;
	ag: number;
	ab: number;
}

export function lerpColor(c: VizColors, t: number): { r: number; g: number; b: number } {
	return {
		r: Math.round(c.pr + (c.ar - c.pr) * t),
		g: Math.round(c.pg + (c.ag - c.pg) * t),
		b: Math.round(c.pb + (c.ab - c.pb) * t)
	};
}

export function readVizColors(): VizColors {
	const s = getComputedStyle(document.documentElement);
	return {
		pr: Number.parseInt(s.getPropertyValue('--viz-primary-r')) || 255,
		pg: Number.parseInt(s.getPropertyValue('--viz-primary-g')) || 50,
		pb: Number.parseInt(s.getPropertyValue('--viz-primary-b')) || 32,
		ar: Number.parseInt(s.getPropertyValue('--viz-accent-r')) || 160,
		ag: Number.parseInt(s.getPropertyValue('--viz-accent-g')) || 32,
		ab: Number.parseInt(s.getPropertyValue('--viz-accent-b')) || 240
	};
}

export function boxShadowStyle(energy: number, c: VizColors): string {
	const r = Math.round(c.pr - energy * (c.pr - c.ar) * 0.4);
	const g = Math.round(c.pg + energy * (c.ag - c.pg) * 0.3);
	const b = Math.round(c.pb + energy * (c.ab - c.pb) * 0.8);
	return `height: calc(var(--player-height) + ${energy * 14}px); box-shadow: 0 ${-2 - energy * 8}px ${6 + energy * 18}px rgba(${r}, ${g}, ${b}, ${0.1 + energy * 0.3})`;
}

export function titleGlowStyle(bass: number, c: VizColors): string {
	return `text-shadow: 0 0 ${8 + bass * 20}px rgba(${c.ar}, ${c.ag}, ${c.ab}, ${0.3 + bass * 0.5}), 0 0 ${4 + bass * 10}px rgba(${c.pr}, ${c.pg}, ${c.pb}, ${bass * 0.4})`;
}

interface EnergyBands {
	bass: number;
	mid: number;
	high: number;
	avg: number;
}

function computeEnergy(smoothedFreq: Float32Array, binCount: number): EnergyBands {
	let bassE = 0,
		midE = 0,
		highE = 0,
		totalE = 0;
	const bassEnd = Math.floor(binCount * 0.08);
	const midEnd = Math.floor(binCount * 0.4);
	for (let i = 0; i < binCount; i++) {
		totalE += smoothedFreq[i];
		if (i < bassEnd) bassE += smoothedFreq[i];
		else if (i < midEnd) midE += smoothedFreq[i];
		else highE += smoothedFreq[i];
	}
	return {
		bass: bassE / bassEnd,
		mid: midE / (midEnd - bassEnd),
		high: highE / (binCount - midEnd),
		avg: totalE / binCount
	};
}

function drawBars(
	ctx: CanvasRenderingContext2D,
	smoothedFreq: Float32Array,
	binCount: number,
	w: number,
	h: number,
	cy: number,
	colors: VizColors
): void {
	const barCount = Math.min(binCount, Math.floor(w / 3));
	const barW = w / barCount;
	for (let i = 0; i < barCount; i++) {
		const freqIdx = Math.floor((i / barCount) * binCount * 0.7);
		const val = smoothedFreq[freqIdx];
		const barH = val * h * 1.4;
		const x = i * barW;
		const t = i / barCount;
		const { r, g, b } = lerpColor(colors, t);
		ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${0.04 + val * 0.2})`;
		ctx.fillRect(x, cy - barH / 2, barW - 0.5, barH);
	}
}

interface WaveformDrawArgs {
	ctx: CanvasRenderingContext2D;
	waveformData: Uint8Array<ArrayBuffer>;
	w: number;
	h: number;
	cy: number;
	colors: VizColors;
	avgE: number;
	midE: number;
	phase: number;
}

function drawWaveform({
	ctx,
	waveformData,
	w,
	h,
	cy,
	colors,
	avgE,
	midE,
	phase
}: WaveformDrawArgs): void {
	const waveLen = waveformData.length;

	ctx.beginPath();
	ctx.strokeStyle = `rgba(${colors.pr}, ${colors.pg}, ${colors.pb}, ${0.15 + avgE * 0.35})`;
	ctx.lineWidth = 1 + avgE * 1.5;
	for (let i = 0; i < waveLen; i++) {
		const x = (i / waveLen) * w;
		const v = waveformData[i] / 128 - 1;
		const y = cy + v * h * (0.4 + avgE * 0.6);
		if (i === 0) ctx.moveTo(x, y);
		else ctx.lineTo(x, y);
	}
	ctx.stroke();

	if (avgE > 0.1) {
		ctx.save();
		ctx.shadowColor = `rgba(${colors.pr}, ${colors.pg}, ${colors.pb}, ${avgE * 0.6})`;
		ctx.shadowBlur = 6 + avgE * 14;
		ctx.stroke();
		ctx.restore();
	}

	ctx.beginPath();
	ctx.strokeStyle = `rgba(${colors.ar}, ${colors.ag}, ${colors.ab}, ${0.1 + midE * 0.3})`;
	ctx.lineWidth = 0.8 + midE * 1;
	for (let i = 0; i < waveLen; i++) {
		const x = (i / waveLen) * w;
		const v = waveformData[i] / 128 - 1;
		const offset = Math.sin(phase * 3 + i * 0.02) * midE * 15;
		const y = cy + v * h * (0.25 + midE * 0.4) + offset;
		if (i === 0) ctx.moveTo(x, y);
		else ctx.lineTo(x, y);
	}
	ctx.stroke();
}

interface RingDrawArgs {
	ctx: CanvasRenderingContext2D;
	smoothedFreq: Float32Array;
	binCount: number;
	w: number;
	h: number;
	cy: number;
	colors: VizColors;
	energy: EnergyBands;
	phase: number;
}

function ringEnergy(ringIndex: number, energy: EnergyBands): number {
	if (ringIndex < 2) return energy.bass;
	if (ringIndex < 4) return energy.mid;
	return energy.high;
}

function drawRings({
	ctx,
	smoothedFreq,
	binCount,
	w,
	h,
	cy,
	colors,
	energy,
	phase
}: RingDrawArgs): void {
	const ringCount = 6;
	for (let r2 = 0; r2 < ringCount; r2++) {
		const ringT = r2 / ringCount;
		const baseRadius = 10 + r2 * (Math.min(w, h) * 0.1);
		const e = ringEnergy(r2, energy);
		const points = 80;

		ctx.beginPath();
		const { r: rr, g: rg, b: rb } = lerpColor(colors, ringT);
		ctx.strokeStyle = `rgba(${rr}, ${rg}, ${rb}, ${0.06 + e * 0.35})`;
		ctx.lineWidth = 0.8 + e * 1.5;

		for (let p = 0; p <= points; p++) {
			const a = (p / points) * Math.PI * 2;
			const freqI = Math.floor((p / points) * binCount * 0.6);
			const fv = smoothedFreq[freqI];
			const pulse = baseRadius + fv * 25 + e * 15;
			const x = w / 2 + Math.cos(a + phase * (1 + r2 * 0.3)) * pulse;
			const y = cy + Math.sin(a + phase * (1 + r2 * 0.3)) * pulse * 0.6;
			if (p === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		}
		ctx.closePath();
		ctx.stroke();

		if (e > 0.3) {
			ctx.save();
			ctx.shadowColor = `rgba(${rr}, ${rg}, ${rb}, ${(e - 0.3) * 0.5})`;
			ctx.shadowBlur = 4 + e * 10;
			ctx.stroke();
			ctx.restore();
		}
	}
}

function spawnParticles(
	particles: Particle[],
	bassE: number,
	w: number,
	cy: number,
	colors: VizColors
): void {
	for (let i = 0; i < Math.floor(bassE * 20); i++) {
		if (particles.length >= MAX_PARTICLES) break;
		const angle = Math.random() * Math.PI * 2; // NOSONAR Animation particles do not generate secrets or security tokens.
		const speed = 2 + bassE * 8;
		const dist = 10 + Math.random() * 30; // NOSONAR Animation particles do not generate secrets or security tokens.
		const pt = Math.random(); // NOSONAR Animation particles do not generate secrets or security tokens.
		const { r, g, b } = lerpColor(colors, pt * 0.4);
		particles.push({
			x: w / 2 + Math.cos(angle) * dist,
			y: cy + Math.sin(angle) * dist * 0.6,
			vx: Math.cos(angle) * speed * (0.5 + Math.random()), // NOSONAR Animation particles do not generate secrets or security tokens.
			vy: Math.sin(angle) * speed * 0.6 * (0.5 + Math.random()), // NOSONAR Animation particles do not generate secrets or security tokens.
			life: 1,
			decay: 0.01 + Math.random() * 0.02, // NOSONAR Animation particles do not generate secrets or security tokens.
			r,
			g,
			b,
			size: 1.5 + Math.random() * 3 // NOSONAR Animation particles do not generate secrets or security tokens.
		});
	}
}

function updateAndDrawParticles(
	ctx: CanvasRenderingContext2D,
	particles: Particle[],
	vizOpacity: number
): void {
	for (let i = particles.length - 1; i >= 0; i--) {
		const p = particles[i];
		p.x += p.vx;
		p.y += p.vy;
		p.vx *= 0.96;
		p.vy *= 0.96;
		p.life -= p.decay;
		if (p.life <= 0) {
			particles.splice(i, 1);
			continue;
		}
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
}

export class AudioVisualizer {
	private smoothedFreq = new Float32Array(FFT_SIZE / 2);
	private particles: Particle[] = [];
	private prevBassHit = false;
	private phase = 0;
	private _opacity = 0;
	private _animFrameId: number | undefined;

	private _onEnergy: ((bass: number, energy: number) => void) | undefined;

	drawFrame(
		canvas: HTMLCanvasElement,
		analyser: AnalyserNode,
		frequencyData: Uint8Array<ArrayBuffer>,
		waveformData: Uint8Array<ArrayBuffer>,
		colors: VizColors
	): void {
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;
		const rect = canvas.getBoundingClientRect();
		const w = rect.width;
		const h = rect.height;

		if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
			canvas.width = Math.round(w * dpr);
			canvas.height = Math.round(h * dpr);
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		}

		ctx.clearRect(0, 0, w, h);
		analyser.getByteFrequencyData(frequencyData);
		analyser.getByteTimeDomainData(waveformData);

		const binCount = frequencyData.length;
		for (let i = 0; i < binCount; i++) {
			this.smoothedFreq[i] = this.smoothedFreq[i] * 0.8 + (frequencyData[i] / 255) * 0.2;
		}

		if (this._opacity < 1) this._opacity = Math.min(1, this._opacity + 0.05);
		this.phase += 0.02;

		const cy = h / 2;
		const energy = computeEnergy(this.smoothedFreq, binCount);
		if (this._onEnergy) this._onEnergy(energy.bass, energy.avg);

		ctx.globalAlpha = this._opacity;
		drawBars(ctx, this.smoothedFreq, binCount, w, h, cy, colors);
		drawWaveform({
			ctx,
			waveformData,
			w,
			h,
			cy,
			colors,
			avgE: energy.avg,
			midE: energy.mid,
			phase: this.phase
		});
		drawRings({
			ctx,
			smoothedFreq: this.smoothedFreq,
			binCount,
			w,
			h,
			cy,
			colors,
			energy,
			phase: this.phase
		});

		const bassHit = energy.bass > BASS_THRESHOLD;
		if (bassHit && !this.prevBassHit) {
			spawnParticles(this.particles, energy.bass, w, cy, colors);
		}
		this.prevBassHit = bassHit;

		updateAndDrawParticles(ctx, this.particles, this._opacity);
		ctx.globalAlpha = 1;
	}

	startLoop(
		canvas: HTMLCanvasElement,
		analyser: AnalyserNode,
		frequencyData: Uint8Array<ArrayBuffer>,
		waveformData: Uint8Array<ArrayBuffer>,
		colors: VizColors,
		onEnergy?: (bass: number, energy: number) => void
	): void {
		if (this._animFrameId) return;
		this._opacity = 0;
		this._onEnergy = onEnergy;

		const loop = () => {
			this.drawFrame(canvas, analyser, frequencyData, waveformData, colors);
			this._animFrameId = requestAnimationFrame(loop);
		};
		loop();
	}

	stopLoop(canvas: HTMLCanvasElement): void {
		if (this._animFrameId) {
			cancelAnimationFrame(this._animFrameId);
			this._animFrameId = undefined;
		}
		this.fadeOut(canvas);
	}

	private fadeOut(canvas: HTMLCanvasElement): void {
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const fade = () => {
			this._opacity *= 0.9;
			for (let i = 0; i < this.smoothedFreq.length; i++) this.smoothedFreq[i] *= 0.9;
			for (let i = this.particles.length - 1; i >= 0; i--) {
				this.particles[i].life -= 0.04;
				if (this.particles[i].life <= 0) this.particles.splice(i, 1);
			}
			if (this._opacity < 0.01) {
				ctx.clearRect(0, 0, canvas.width, canvas.height);
				this.smoothedFreq.fill(0);
				this._opacity = 0;
				this.particles = [];
				return;
			}
			requestAnimationFrame(fade);
		};
		requestAnimationFrame(fade);
	}

	destroy(): void {
		if (this._animFrameId) {
			cancelAnimationFrame(this._animFrameId);
			this._animFrameId = undefined;
		}
	}
}
