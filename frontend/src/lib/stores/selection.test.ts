import { makeGeneration as generation } from '#lib/test-utils/factories.ts';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { selectedSongId } from './player';

import {
	clearSelection,
	keepOnlySelected,
	selectAllUnkept,
	selectedIds,
	selectionMode,
	toggleSelection
} from './selection';

beforeEach(() => {
	selectedSongId.set(null);
	clearSelection();
});

describe('selection', () => {
	it('enters selection mode when an item is selected and leaves it after the last item is removed', () => {
		toggleSelection('g1');

		expect(get(selectionMode)).toBe(true);
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

		clearSelection();

		expect(get(selectionMode)).toBe(false);
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

	it('starts empty with select mode off when the song on screen changes', () => {
		selectedSongId.set('song-a');
		toggleSelection('g1');
		toggleSelection('g2');

		selectedSongId.set('song-b');

		expect(get(selectedIds)).toEqual(new Set());
		expect(get(selectionMode)).toBe(false);
	});

	it('starts empty on returning to a song after another one was shown with no take list mounted', () => {
		selectedSongId.set('song-a');
		toggleSelection('g1');

		selectedSongId.set('song-b');
		selectedSongId.set('song-a');

		expect(get(selectedIds)).toEqual(new Set());
		expect(get(selectionMode)).toBe(false);
	});

	it('keeps the selection while the same song stays on screen or no song is shown', () => {
		selectedSongId.set('song-a');
		toggleSelection('g1');

		selectedSongId.set('song-a');
		selectedSongId.set(null);

		expect(get(selectedIds)).toEqual(new Set(['g1']));
		expect(get(selectionMode)).toBe(true);
	});

	it('keeps a new selection on returning to the same song after Cancel', () => {
		selectedSongId.set('song-a');
		toggleSelection('g1');
		clearSelection();
		toggleSelection('g2');

		selectedSongId.set(null);
		selectedSongId.set('song-a');

		expect(get(selectedIds)).toEqual(new Set(['g2']));
		expect(get(selectionMode)).toBe(true);
	});
});

describe('keepOnlySelected (rule 6, cells 18/21/26/27)', () => {
	it('removes every selected id outside the given ones and keeps select mode while some remain', () => {
		toggleSelection('g1');
		toggleSelection('g2');
		toggleSelection('g3');

		keepOnlySelected(new Set(['g1', 'g3', 'g9']));

		expect(get(selectedIds)).toEqual(new Set(['g1', 'g3']));
		expect(get(selectionMode)).toBe(true);
	});

	it('ends select mode when it removed the last selected id', () => {
		toggleSelection('g1');

		keepOnlySelected(new Set(['g2']));

		expect(get(selectedIds)).toEqual(new Set());
		expect(get(selectionMode)).toBe(false);
	});

	it('leaves select mode on when nothing was selected to remove', () => {
		selectionMode.set(true);

		keepOnlySelected(new Set(['g1']));

		expect(get(selectionMode)).toBe(true);
	});
});
