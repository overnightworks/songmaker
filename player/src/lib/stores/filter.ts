import { writable } from 'svelte/store';
import type { Track } from '$lib/api/types';

export interface MetricDef {
	key: string;
	label: string;
	max: number;
	step: number;
	getValue: (t: Track) => number | string | undefined;
	type: 'number' | 'select';
}

export const METRICS: MetricDef[] = [
	{
		key: 'lyrical_coherence',
		label: 'Lyrical Coherence',
		max: 10,
		step: 0.5,
		getValue: (t) => t.scores?.lyrical_coherence,
		type: 'number'
	},
	{
		key: 'dynamics',
		label: 'Dynamics',
		max: 100,
		step: 5,
		getValue: (t) => t.scores?.dynamics,
		type: 'number'
	},
	{
		key: 'text_accuracy',
		label: 'Text Accuracy',
		max: 100,
		step: 5,
		getValue: (t) => t.scores?.text_accuracy,
		type: 'number'
	},
	{
		key: 'audiobox_enjoyment',
		label: 'Enjoyment',
		max: 10,
		step: 0.5,
		getValue: (t) => t.scores?.audiobox_enjoyment,
		type: 'number'
	},
	{
		key: 'audiobox_understanding',
		label: 'Understanding',
		max: 10,
		step: 0.5,
		getValue: (t) => t.scores?.audiobox_understanding,
		type: 'number'
	},
	{
		key: 'audiobox_complexity',
		label: 'Complexity',
		max: 10,
		step: 0.5,
		getValue: (t) => t.scores?.audiobox_complexity,
		type: 'number'
	},
	{
		key: 'audiobox_quality',
		label: 'Production Quality',
		max: 10,
		step: 0.5,
		getValue: (t) => t.scores?.audiobox_quality,
		type: 'number'
	},
	{
		key: 'user_rating',
		label: 'User Rating',
		max: 100,
		step: 5,
		getValue: (t) => t.scores?.user_rating,
		type: 'number'
	},
	{
		key: 'bpm',
		label: 'BPM',
		max: 200,
		step: 5,
		getValue: (t) => t.generation?.bpm,
		type: 'number'
	},
	{
		key: 'key',
		label: 'Key',
		max: 0,
		step: 0,
		getValue: (t) => t.generation?.key,
		type: 'select'
	}
];

export const SORT_OPTIONS = METRICS.filter((m) => m.type === 'number');

export interface ActiveFilter {
	metric: MetricDef;
	min: number;
	selectValue: string;
}

export const sortKey = writable('lyrical_coherence');
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

export function applyFilters(tracks: Track[], filters: ActiveFilter[]): Track[] {
	return tracks.filter((t) =>
		filters.every((f) => {
			if (f.metric.type === 'select') {
				if (!f.selectValue) return true;
				return f.metric.getValue(t) === f.selectValue;
			}
			if (f.min <= 0) return true;
			const val = f.metric.getValue(t);
			return typeof val === 'number' && val >= f.min;
		})
	);
}
