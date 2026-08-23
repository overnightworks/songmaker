import type { TrackScores } from '$lib/api/types';

export interface ScoreThreshold {
	good: number;
	ok: number;
}

export const SCORE_THRESHOLDS: Record<string, ScoreThreshold> = {
	user_rating: { good: 70, ok: 40 },
	audiobox_enjoyment: { good: 7, ok: 4 },
	audiobox_quality: { good: 7, ok: 4 },
	lyrical_coherence: { good: 7, ok: 4 },
	dynamics: { good: 60, ok: 30 },
	text_accuracy: { good: 70, ok: 40 }
};

export function scoreColor(key: string, value: number): string {
	const t = SCORE_THRESHOLDS[key];
	if (!t) return 'ok';
	return value >= t.good ? 'good' : value >= t.ok ? 'ok' : 'bad';
}

export type ScoreKey =
	| 'user_rating'
	| 'text_accuracy'
	| 'dynamics'
	| 'audiobox_quality'
	| 'audiobox_enjoyment'
	| 'lyrical_coherence';

// What a scorer's raw number is out of. Thresholds and colours are read on
// that raw scale; only the display normalizes.
type ScoreScale = 'hundred' | 'ten';

// How the panel writes the raw number out. The pill has its own rule.
type PanelFormat = 'integer' | 'percent' | 'decimal';

export interface ScoreMetric {
	key: ScoreKey;
	label: string;
	scale: ScoreScale;
	panelFormat: PanelFormat;
}

// The one table both take surfaces read: the row's score pill takes the first
// metric a take carries, the This-take panel lists every one of them, and both
// name it the same. Ordered by how much it tells the listener — their own
// verdict first, then the automatic scores. BPM is not here: it names the
// tempo that was detected, not how good the take is, and it colours itself
// from its deviation rather than from a threshold, so the panel keeps it as
// its own entry.
export const SCORE_METRICS: readonly ScoreMetric[] = [
	{ key: 'user_rating', label: 'Rating', scale: 'hundred', panelFormat: 'integer' },
	{ key: 'text_accuracy', label: 'Lyrics sung', scale: 'hundred', panelFormat: 'percent' },
	{ key: 'dynamics', label: 'Dynamics', scale: 'hundred', panelFormat: 'integer' },
	{ key: 'audiobox_quality', label: 'Quality', scale: 'ten', panelFormat: 'decimal' },
	{ key: 'audiobox_enjoyment', label: 'Enjoyment', scale: 'ten', panelFormat: 'decimal' },
	{ key: 'lyrical_coherence', label: 'Coherence', scale: 'ten', panelFormat: 'integer' }
];

const TEN_TO_HUNDRED = 10;

// The panel shows each score beside its own label, so it can keep the scorer's
// own scale. The pill shows a single unlabelled number in a take row, where an
// 8.15 out of 10 next to an 87 out of 100 reads as the worse take — so there
// every metric is put on the same 0-100 scale, rounded to a whole number.
export function formatScore(metric: ScoreMetric, value: number, display: 'panel' | 'pill'): string {
	if (display === 'pill') {
		return Math.round(metric.scale === 'ten' ? value * TEN_TO_HUNDRED : value).toString();
	}
	switch (metric.panelFormat) {
		case 'percent':
			return `${value.toFixed(0)}%`;
		case 'decimal':
			return value.toFixed(2);
		case 'integer':
			return value.toFixed(0);
	}
}

export interface ScoreReading {
	metric: ScoreMetric;
	value: number;
}

// Every metric the take actually carries, in table order: a take is scored by
// seven scorers that can land one at a time, so "scored" is never
// all-or-nothing.
export function scoreReadings(scores: TrackScores | null): ScoreReading[] {
	if (!scores) return [];
	const readings: ScoreReading[] = [];
	for (const metric of SCORE_METRICS) {
		const value = scores[metric.key];
		if (value !== undefined) readings.push({ metric, value });
	}
	return readings;
}
