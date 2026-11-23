import { makeTakeOfVersion, makeTakesAcrossVersions } from '#lib/test-utils/factories.ts';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { selectedSongId } from './player';
import {
	isGroupOpen,
	renderedTakes,
	revealTakeGroup,
	settleTakeFolds,
	takeFolds,
	toggleTakeGroup
} from './takeFolds';
import { groupTakes } from '#lib/utils/takeGroups.ts';

const SONG_TAKES = makeTakesAcrossVersions();

let songSequence = 0;

beforeEach(() => {
	selectedSongId.set(`song-${(songSequence += 1)}`);
});

describe('the rendered takes (rules 1 and 3, cells 3/5)', () => {
	function renderedIds(groups = groupTakes(SONG_TAKES, 3)): string[] {
		return renderedTakes(get(takeFolds), groups).map((gen) => gen.id);
	}

	it('are the current version only until a version is unfolded', () => {
		const groups = groupTakes(SONG_TAKES, 3);
		settleTakeFolds(groups);

		expect(renderedIds(groups)).toEqual(['c1']);

		toggleTakeGroup('v2', groups);

		expect(renderedIds(groups)).toEqual(['c1', 'a1', 'a2']);
		expect(isGroupOpen(get(takeFolds), groups, 'v2')).toBe(true);
	});

	it('fold again on a second toggle', () => {
		const groups = groupTakes(SONG_TAKES, 3);
		toggleTakeGroup('v2', groups);
		toggleTakeGroup('v2', groups);

		expect(renderedIds(groups)).toEqual(['c1']);
	});

	it('never keep a version open once it is no longer the current one', () => {
		const withV3 = groupTakes(SONG_TAKES, 3);
		settleTakeFolds(withV3);
		revealTakeGroup('v3');
		const withV4 = groupTakes(SONG_TAKES, 4);
		settleTakeFolds(withV4);

		expect(isGroupOpen(get(takeFolds), withV4, 'v3')).toBe(false);
	});
});

describe('revealTakeGroup (rule 10, cell 43)', () => {
	it('opens a folded version', () => {
		const groups = groupTakes(SONG_TAKES, 3);
		settleTakeFolds(groups);

		revealTakeGroup('v1');

		expect(isGroupOpen(get(takeFolds), groups, 'v1')).toBe(true);
	});

	it('leaves the current version out of the open set', () => {
		const groups = groupTakes(SONG_TAKES, 3);
		settleTakeFolds(groups);

		revealTakeGroup('v3');

		expect(get(takeFolds).open.has('v3')).toBe(false);
	});
});

describe('Imported starts open by default (rule 5, Q1 (a), cell 47)', () => {
	const importedOnly = [makeTakeOfVersion('i1', null)];

	it('when no version of the song holds a take', () => {
		const groups = groupTakes(importedOnly, 1);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(true);
	});

	it('only once: a fold by hand stays through a second settle', () => {
		const groups = groupTakes(importedOnly, 1);
		settleTakeFolds(groups);
		toggleTakeGroup('imported', groups);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(false);
	});

	it('not when a version holds a take', () => {
		const groups = groupTakes([...importedOnly, makeTakeOfVersion('c1', 1)], 1);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(false);
	});

	it('keeps the default through a take arriving on a version', () => {
		settleTakeFolds(groupTakes(importedOnly, 1));
		const later = groupTakes([...importedOnly, makeTakeOfVersion('c1', 1)], 1);
		settleTakeFolds(later);

		expect(isGroupOpen(get(takeFolds), later, 'imported')).toBe(true);
	});
});

describe('folds belong to the song they were made on (rule 12, cells 36/39)', () => {
	function unfoldV2(): void {
		toggleTakeGroup('v2', groupTakes(SONG_TAKES, 3));
	}

	it('keeps the open versions while the same song stays on screen or no song is shown', () => {
		selectedSongId.set('song-a');
		unfoldV2();

		selectedSongId.set(null);
		selectedSongId.set('song-a');

		expect(get(takeFolds).open.has('v2')).toBe(true);
	});

	it('folds everything on returning to a song after another song was shown, with no list mounted', () => {
		selectedSongId.set('song-a');
		unfoldV2();

		selectedSongId.set('song-b');
		selectedSongId.set('song-a');

		expect(get(takeFolds).open.size).toBe(0);
	});
});
