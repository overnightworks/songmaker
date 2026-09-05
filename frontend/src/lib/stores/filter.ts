import { writable } from 'svelte/store';
import type { SongItem } from '$lib/api/types';

export interface MetricDef {
	key: string;
	label: string;
	max: number;
	step: number;
	getValue: (s: SongItem) => number | string | undefined;
	type: 'number' | 'select';
}

export const METRICS: MetricDef[] = [
	{
		key: 'lyrical_coherence',
		label: 'Lyrical Coherence',
		max: 10,
		step: 0.5,
		getValue: (s) => s.best_scores?.lyrical_coherence,
		type: 'number'
	},
	{
		key: 'dynamics',
		label: 'Dynamics',
		max: 100,
		step: 5,
		getValue: (s) => s.best_scores?.dynamics,
		type: 'number'
	},
	{
		key: 'text_accuracy',
		label: 'Text Accuracy',
		max: 100,
		step: 5,
		getValue: (s) => s.best_scores?.text_accuracy,
		type: 'number'
	},
	{
		key: 'audiobox_enjoyment',
		label: 'Enjoyment',
		max: 10,
		step: 0.5,
		getValue: (s) => s.best_scores?.audiobox_enjoyment,
		type: 'number'
	},
	{
		key: 'audiobox_quality',
		label: 'Production Quality',
		max: 10,
		step: 0.5,
		getValue: (s) => s.best_scores?.audiobox_quality,
		type: 'number'
	},
	{
		key: 'user_rating',
		label: 'User Rating',
		max: 100,
		step: 5,
		getValue: (s) => s.best_rating ?? undefined,
		type: 'number'
	},
	{
		key: 'generation_count',
		label: 'Generations',
		max: 50,
		step: 1,
		getValue: (s) => s.generation_count,
		type: 'number'
	},
	{
		key: 'key_scale',
		label: 'Key',
		max: 0,
		step: 0,
		getValue: (s) => s.key_scale ?? undefined,
		type: 'select'
	},
	{
		key: 'bpm',
		label: 'BPM',
		max: 300,
		step: 10,
		getValue: (s) => s.bpm || undefined,
		type: 'number'
	},
	{
		key: 'audio_duration',
		label: 'Duration',
		max: 600,
		step: 30,
		getValue: (s) => s.audio_duration || undefined,
		type: 'number'
	}
];

export const SORT_OPTIONS = METRICS.filter((m) => m.type === 'number');

export interface ActiveFilter {
	metric: MetricDef;
	min: number;
	selectValue: string;
}

export const sortKey = writable('lyrical_coherence');
// The rail owns the only visible library search field. Its query deliberately
// stays in memory: returning to a page must restore navigation, not a stale
// narrowed tree.
export const railTreeQuery = writable('');
// Retained for restoring existing library history until 2B moves the
// server-search contract behind the rail field.
export const searchQuery = writable('');
export const activeFilters = writable<ActiveFilter[]>([]);

export function getMetric(key: string): MetricDef {
	return METRICS.find((m) => m.key === key) ?? METRICS[0];
}

export function getSortMetric(key: string): MetricDef {
	return SORT_OPTIONS.find((m) => m.key === key) ?? SORT_OPTIONS[0];
}

export function addFilter(key: string): void {
	const metric = getMetric(key);
	activeFilters.update((filters) => {
		if (filters.some((f) => f.metric.key === key)) return filters;
		return [...filters, { metric, min: 0, selectValue: '' }];
	});
}

export function removeFilter(key: string): void {
	activeFilters.update((filters) => filters.filter((f) => f.metric.key !== key));
}

export function updateFilterMin(key: string, min: number): void {
	activeFilters.update((filters) => filters.map((f) => (f.metric.key === key ? { ...f, min } : f)));
}

export function updateFilterSelect(key: string, value: string): void {
	activeFilters.update((filters) =>
		filters.map((f) => (f.metric.key === key ? { ...f, selectValue: value } : f))
	);
}

export function applyFilters(songs: SongItem[], filters: ActiveFilter[]): SongItem[] {
	return songs.filter((s) =>
		filters.every((f) => {
			if (f.metric.type === 'select') {
				if (!f.selectValue) return true;
				return f.metric.getValue(s) === f.selectValue;
			}
			if (f.min <= 0) return true;
			const val = f.metric.getValue(s);
			return typeof val === 'number' && val >= f.min;
		})
	);
}
