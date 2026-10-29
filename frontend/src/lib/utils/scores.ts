import type { GenerationItem, TrackScores } from '#lib/api/types.ts';

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

type ScoreKey =
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
const SCORE_METRICS: readonly ScoreMetric[] = [
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

interface QualityFlag {
	label: string;
	title: string;
}

// The hard-failure flags a take can carry, independent of the headline pill —
// a take can carry a good headline score (e.g. a listener's own rating) while
// still having produced no vocals or gone silent partway through. "No vocals"
// is the take's own transcript coming back empty ("" — null means not yet
// transcribed) for a version that has lyrics.
export function qualityFlag(
	take: Pick<GenerationItem, 'scores' | 'whisper_text' | 'version_lyrics'>
): QualityFlag | null {
	if (take.whisper_text === '' && take.version_lyrics?.trim()) {
		return { label: 'No vocals', title: 'No vocals detected in this take' };
	}
	const scores = take.scores;
	if (!scores) return null;
	if (
		scores.silence_longest !== undefined &&
		scores.silence_longest >= QUALITY_FLAG_SILENCE_SECONDS
	) {
		return {
			label: 'Long silence',
			title: `${Math.round(scores.silence_longest)}s of silence detected`
		};
	}
	return null;
}
