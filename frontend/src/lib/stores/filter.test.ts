import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import type { SongItem } from '$lib/api/types';
import {
	METRICS,
	SORT_OPTIONS,
	activeFilters,
	addFilter,
	applyFilters,
	getMetric,
	getSortMetric,
	removeFilter,
	searchQuery,
	sortKey,
	updateFilterMin,
	updateFilterSelect
} from './filter';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		title: 'Test Song',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		duration: 180,
		key: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 5,
		best_scores: { dynamics: 60, text_accuracy: 80 },
		best_rating: 75,
		generations: [],
		created_at: null,
		...overrides
	};
}

describe('filter store', () => {
	it('METRICS includes expected keys', () => {
		const keys = METRICS.map((m) => m.key);
		expect(keys).toContain('dynamics');
		expect(keys).toContain('key');
		expect(keys).toContain('bpm');
		expect(keys).toContain('duration');
	});

	it('SORT_OPTIONS excludes select type', () => {
		expect(SORT_OPTIONS.every((m) => m.type === 'number')).toBe(true);
		expect(SORT_OPTIONS.find((m) => m.key === 'key')).toBeUndefined();
	});

	it('getMetric returns matching metric', () => {
		expect(getMetric('dynamics').label).toBe('Dynamics');
	});

	it('getMetric falls back to first metric', () => {
		expect(getMetric('nonexistent')).toBe(METRICS[0]);
	});

	it('getSortMetric returns matching sort option', () => {
		expect(getSortMetric('dynamics').key).toBe('dynamics');
	});

	it('getSortMetric falls back to first sort option', () => {
		expect(getSortMetric('nonexistent')).toBe(SORT_OPTIONS[0]);
	});

	it('initial stores are empty', () => {
		expect(get(sortKey)).toBe('lyrical_coherence');
		expect(get(searchQuery)).toBe('');
		expect(get(activeFilters)).toEqual([]);
	});

	it('addFilter adds a filter', () => {
		activeFilters.set([]);
		addFilter('dynamics');
		const filters = get(activeFilters);
		expect(filters).toHaveLength(1);
		expect(filters[0].metric.key).toBe('dynamics');
		activeFilters.set([]);
	});

	it('addFilter does not duplicate', () => {
		activeFilters.set([]);
		addFilter('dynamics');
		addFilter('dynamics');
		expect(get(activeFilters)).toHaveLength(1);
		activeFilters.set([]);
	});

	it('removeFilter removes a filter', () => {
		activeFilters.set([]);
		addFilter('dynamics');
		addFilter('text_accuracy');
		removeFilter('dynamics');
		const filters = get(activeFilters);
		expect(filters).toHaveLength(1);
		expect(filters[0].metric.key).toBe('text_accuracy');
		activeFilters.set([]);
	});

	it('updateFilterMin updates the min value', () => {
		activeFilters.set([]);
		addFilter('dynamics');
		updateFilterMin('dynamics', 50);
		expect(get(activeFilters)[0].min).toBe(50);
		activeFilters.set([]);
	});

	it('updateFilterSelect updates the select value', () => {
		activeFilters.set([]);
		addFilter('key');
		updateFilterSelect('key', 'Am');
		expect(get(activeFilters)[0].selectValue).toBe('Am');
		activeFilters.set([]);
	});
});

describe('applyFilters', () => {
	it('returns all songs with no filters', () => {
		const songs = [makeSong(), makeSong({ id: 's2' })];
		expect(applyFilters(songs, [])).toHaveLength(2);
	});

	it('filters by numeric min', () => {
		const songs = [
			makeSong({ id: 's1', best_scores: { dynamics: 30 } }),
			makeSong({ id: 's2', best_scores: { dynamics: 70 } })
		];
		const filters = [{ metric: getMetric('dynamics'), min: 50, selectValue: '' }];
		const result = applyFilters(songs, filters);
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('s2');
	});

	it('filters by select value', () => {
		const songs = [
			makeSong({ id: 's1', key: 'Am' }),
			makeSong({ id: 's2', key: 'C' })
		];
		const filters = [{ metric: getMetric('key'), min: 0, selectValue: 'Am' }];
		const result = applyFilters(songs, filters);
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('s1');
	});

	it('select filter with empty value passes all', () => {
		const songs = [makeSong({ key: 'Am' }), makeSong({ id: 's2', key: 'C' })];
		const filters = [{ metric: getMetric('key'), min: 0, selectValue: '' }];
		expect(applyFilters(songs, filters)).toHaveLength(2);
	});

	it('numeric filter with min 0 passes all', () => {
		const songs = [makeSong()];
		const filters = [{ metric: getMetric('dynamics'), min: 0, selectValue: '' }];
		expect(applyFilters(songs, filters)).toHaveLength(1);
	});

	it('AND-combines multiple filters', () => {
		const songs = [
			makeSong({ id: 's1', key: 'Am', best_scores: { dynamics: 80 } }),
			makeSong({ id: 's2', key: 'C', best_scores: { dynamics: 80 } }),
			makeSong({ id: 's3', key: 'Am', best_scores: { dynamics: 20 } })
		];
		const filters = [
			{ metric: getMetric('key'), min: 0, selectValue: 'Am' },
			{ metric: getMetric('dynamics'), min: 50, selectValue: '' }
		];
		const result = applyFilters(songs, filters);
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('s1');
	});

	it('getValue returns undefined for missing scores', () => {
		const song = makeSong({ best_scores: null });
		const metric = getMetric('dynamics');
		expect(metric.getValue(song)).toBeUndefined();
	});

	it('getValue returns bpm', () => {
		const song = makeSong({ bpm: 140 });
		expect(getMetric('bpm').getValue(song)).toBe(140);
	});

	it('getValue returns undefined for bpm=0', () => {
		const song = makeSong({ bpm: 0 });
		expect(getMetric('bpm').getValue(song)).toBeUndefined();
	});
});
