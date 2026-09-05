import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import type { GenerationItem } from '$lib/api/types';
import {
	clearSelection,
	enterSelectionMode,
	exitSelectionMode,
	isSelected,
	selectAll,
	selectAllUnkept,
	selectedIds,
	selectionCount,
	selectionMode,
	toggleSelection
} from './selection';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: '/audio/g1.mp3',
		wav_path: null,
		seed: 1,
		status: 'complete',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		share_slug: null,
		model_mode: 'base',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		audio_duration_sec: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

beforeEach(() => {
	clearSelection();
});

describe('selection', () => {
	it('enters selection mode when an item is selected and leaves it after the last item is removed', () => {
		toggleSelection('g1');

		expect(get(selectionMode)).toBe(true);
		expect(get(selectionCount)).toBe(1);
		expect(isSelected('g1')).toBe(true);

		toggleSelection('g1');

		expect(get(selectionMode)).toBe(false);
		expect(get(selectedIds)).toEqual(new Set());
	});

	it('keeps existing selections when adding all ids and clears them when selection mode exits', () => {
		toggleSelection('g1');
		selectAll(['g1', 'g2']);

		expect(get(selectedIds)).toEqual(new Set(['g1', 'g2']));
		expect(get(selectionCount)).toBe(2);

		exitSelectionMode();

		expect(get(selectionMode)).toBe(false);
		expect(get(selectionCount)).toBe(0);
	});

	it('selects only generations that are neither picked nor kept', () => {
		enterSelectionMode();
		selectAllUnkept([
			generation({ id: 'available' }),
			generation({ id: 'picked', is_picked: true }),
			generation({ id: 'kept', is_kept: true })
		]);

		expect(get(selectedIds)).toEqual(new Set(['available']));
		expect(get(selectionMode)).toBe(true);
	});
});
