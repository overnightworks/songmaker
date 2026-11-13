import type { GenerationItem, TrackScores } from '#lib/api/types.ts';
import { pageLanguage } from '#lib/utils/page-language.ts';

interface ScoreThreshold {
	good: number;
	ok: number;
}

const SCORE_THRESHOLDS: Record<string, ScoreThreshold> = {
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
	if (value >= t.good) return 'good';
	return value >= t.ok ? 'ok' : 'bad';
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

interface ScoreMetric {
	key: ScoreKey;
	scale: ScoreScale;
	panelFormat: PanelFormat;
}

// The one table both take surfaces read: the row's score pill takes the first
// metric a take carries and the This-take panel lists every one of them, each
// surface naming it under its own catalog key. Ordered by how much it tells
// the listener — their own verdict first, then the automatic scores. BPM is
// not here: it names the tempo that was detected, not how good the take is,
// and it colours itself from its deviation rather than from a threshold, so
// the panel keeps it as its own entry.
const SCORE_METRICS: readonly ScoreMetric[] = [
	{ key: 'user_rating', scale: 'hundred', panelFormat: 'integer' },
	{ key: 'text_accuracy', scale: 'hundred', panelFormat: 'percent' },
	{ key: 'dynamics', scale: 'hundred', panelFormat: 'integer' },
	{ key: 'audiobox_quality', scale: 'ten', panelFormat: 'decimal' },
	{ key: 'audiobox_enjoyment', scale: 'ten', panelFormat: 'decimal' },
	{ key: 'lyrical_coherence', scale: 'ten', panelFormat: 'integer' }
];

const TEN_TO_HUNDRED = 10;
const PERCENT_DIVISOR = 100;

function wholeNumber(value: number): string {
	return new Intl.NumberFormat(pageLanguage(), { maximumFractionDigits: 0 }).format(value);
}

// The panel shows each score beside its own label, so it can keep the scorer's
// own scale. The pill shows a single unlabelled number in a take row, where an
// 8.15 out of 10 next to an 87 out of 100 reads as the worse take — so there
// every metric is put on the same 0-100 scale, rounded to a whole number.
export function formatScore(metric: ScoreMetric, value: number, display: 'panel' | 'pill'): string {
	if (display === 'pill') {
		return wholeNumber(metric.scale === 'ten' ? value * TEN_TO_HUNDRED : value);
	}
	switch (metric.panelFormat) {
		case 'percent':
			return new Intl.NumberFormat(pageLanguage(), {
				style: 'percent',
				maximumFractionDigits: 0
			}).format(value / PERCENT_DIVISOR);
		case 'decimal':
			return new Intl.NumberFormat(pageLanguage(), {
				minimumFractionDigits: 2,
				maximumFractionDigits: 2
			}).format(value);
		case 'integer':
			return wholeNumber(value);
	}
}

interface ScoreReading {
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

// A take at or above this much uninterrupted silence reads as broken rather
// than merely quiet — well past an intentional dramatic pause, which rarely
// runs this long (issue #222).
const QUALITY_FLAG_SILENCE_SECONDS = 15;

export type QualityFlag = { kind: 'noVocals' } | { kind: 'longSilence'; seconds: number };

// The hard-failure flags a take can carry, independent of the headline pill —
// a take can carry a good headline score (e.g. a listener's own rating) while
// still having produced no vocals or gone silent partway through. "No vocals"
// is the take's own transcript coming back empty ("" — null means not yet
// transcribed) for a version that has lyrics.
export function qualityFlag(
	take: Pick<GenerationItem, 'scores' | 'whisper_text' | 'version_lyrics'>
): QualityFlag | null {
	if (take.whisper_text === '' && take.version_lyrics?.trim()) return { kind: 'noVocals' };
	const scores = take.scores;
	if (!scores) return null;
	if (
		scores.silence_longest !== undefined &&
		scores.silence_longest >= QUALITY_FLAG_SILENCE_SECONDS
	) {
		return { kind: 'longSilence', seconds: Math.round(scores.silence_longest) };
	}
	return null;
}
