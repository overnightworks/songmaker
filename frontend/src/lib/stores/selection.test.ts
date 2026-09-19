import { makeGeneration as generation } from '$lib/test-utils/factories';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import {
	clearSelection,
	selectAllUnkept,
	selectedIds,
	selectionCount,
	selectionMode,
	toggleSelection
} from './selection';

beforeEach(() => {
	clearSelection();
});

describe('selection', () => {
	it('enters selection mode when an item is selected and leaves it after the last item is removed', () => {
		toggleSelection('g1');

		expect(get(selectionMode)).toBe(true);
		expect(get(selectionCount)).toBe(1);
		expect(get(selectedIds).has('g1')).toBe(true);

		toggleSelection('g1');

		expect(get(selectionMode)).toBe(false);
		expect(get(selectedIds)).toEqual(new Set());
	});

	it('keeps selection mode active while another item remains selected', () => {
		toggleSelection('g1');
		toggleSelection('g2');
		toggleSelection('g1');

		expect(get(selectionMode)).toBe(true);
		expect(get(selectedIds)).toEqual(new Set(['g2']));
	});

	it('keeps existing selections when adding all ids and clears them when selection mode exits', () => {
		toggleSelection('g1');
		selectAllUnkept([
			generation({ mp3_path: '/audio/g1.mp3', seed: 1, status: 'complete', model_mode: 'base' }),
			generation({
				mp3_path: '/audio/g1.mp3',
				seed: 1,
				status: 'complete',
				model_mode: 'base',
				id: 'g2'
			})
		]);

		expect(get(selectedIds)).toEqual(new Set(['g1', 'g2']));
		expect(get(selectionCount)).toBe(2);

		clearSelection();

		expect(get(selectionMode)).toBe(false);
		expect(get(selectionCount)).toBe(0);
	});

	it('selects only generations that are neither picked nor kept', () => {
		selectAllUnkept([
			generation({
				mp3_path: '/audio/g1.mp3',
				seed: 1,
				status: 'complete',
				model_mode: 'base',
				id: 'available'
			}),
			generation({
				mp3_path: '/audio/g1.mp3',
				seed: 1,
				status: 'complete',
				model_mode: 'base',
				id: 'picked',
				is_picked: true
			}),
			generation({
				mp3_path: '/audio/g1.mp3',
				seed: 1,
				status: 'complete',
				model_mode: 'base',
				id: 'kept',
				is_kept: true
			})
		]);

		expect(get(selectedIds)).toEqual(new Set(['available']));
		expect(get(selectionMode)).toBe(true);
	});
});
