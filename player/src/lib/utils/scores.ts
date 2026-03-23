import type { Track } from '$lib/api/types';

export function getLyricalCoherence(track: Track): number {
	return track.scores?.lyrical_coherence ?? 0;
}

export function getDynamics(track: Track): number {
	return track.scores?.dynamics ?? 0;
}

export type ScoreLevel = 'good' | 'ok' | 'bad';

export function scoreLevel(value: number): ScoreLevel {
	if (value >= 7) return 'good';
	if (value >= 4) return 'ok';
	return 'bad';
}
