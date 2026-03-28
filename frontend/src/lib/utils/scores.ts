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
