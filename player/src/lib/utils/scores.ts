export type ScoreLevel = 'good' | 'ok' | 'bad';

export function scoreLevel(value: number): ScoreLevel {
	if (value >= 7) return 'good';
	if (value >= 4) return 'ok';
	return 'bad';
}
