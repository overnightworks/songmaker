import { makeGeneration } from '$lib/test-utils/factories';
import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import type { GenerationItem } from '$lib/api/types';
import { selectedSongId } from './player';
import {
	groupTakes,
	isGroupOpen,
	renderedTakes,
	revealTakeGroup,
	settleTakeFolds,
	takeFolds,
	takeGroupKey,
	toggleTakeGroup
} from './takeFolds';

function takeOf(id: string, versionNumber: number | null, overrides: Partial<GenerationItem> = {}) {
	return makeGeneration({
		id,
		version_id: versionNumber === null ? null : `ver-${versionNumber}`,
		version_number: versionNumber,
		...overrides
	});
}

const SONG_TAKES = [
	takeOf('c1', 3),
	takeOf('a1', 2, { is_picked: true }),
	takeOf('a2', 2, { is_archived: true }),
	takeOf('o1', 1, { is_archived: true }),
	takeOf('i1', null)
];

let songSequence = 0;

beforeEach(() => {
	selectedSongId.set(`song-${(songSequence += 1)}`);
});

describe('groupTakes', () => {
	it('puts the latest version first, the earlier ones newest first and Imported last', () => {
		const groups = groupTakes(SONG_TAKES, 3);

		expect(groups.current?.key).toBe('v3');
		expect(groups.earlier.map((group) => group.key)).toEqual(['v2', 'v1', 'imported']);
	});

	it('counts the archived takes of a group and names its album pick', () => {
		const [second, first] = groupTakes(SONG_TAKES, 3).earlier;

		expect(second.archivedCount).toBe(1);
		expect(second.pick?.id).toBe('a1');
		expect(first.archivedCount).toBe(1);
		expect(first.pick).toBeNull();
	});

	it('keeps the current version with no takes, and none at all for a song with no saved version', () => {
		expect(groupTakes([takeOf('a1', 2)], 3).current?.generations).toEqual([]);
		expect(groupTakes([takeOf('a1', 2)], null).current).toBeNull();
	});

	it('names the group of a take by its version, and Imported when it has none', () => {
		expect(takeGroupKey(takeOf('c1', 3))).toBe('v3');
		expect(takeGroupKey(takeOf('i1', null))).toBe('imported');
		expect(takeGroupKey(takeOf('i2', 3, { version_id: null }))).toBe('imported');
	});
});

describe('the rendered takes', () => {
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

describe('revealTakeGroup', () => {
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

describe('Imported starts open by default', () => {
	const importedOnly = [takeOf('i1', null)];

	it('when no version of the song holds a take', () => {
		const groups = groupTakes(importedOnly, 1);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(true);
	});

	it('only once: a fold by hand stays, and a later generated take does not fold it', () => {
		const groups = groupTakes(importedOnly, 1);
		settleTakeFolds(groups);
		toggleTakeGroup('imported', groups);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(false);
	});

	it('not when a version holds a take', () => {
		const groups = groupTakes([...importedOnly, takeOf('c1', 1)], 1);
		settleTakeFolds(groups);

		expect(isGroupOpen(get(takeFolds), groups, 'imported')).toBe(false);
	});

	it('keeps the default through a take arriving on a version', () => {
		settleTakeFolds(groupTakes(importedOnly, 1));
		const later = groupTakes([...importedOnly, takeOf('c1', 1)], 1);
		settleTakeFolds(later);

		expect(isGroupOpen(get(takeFolds), later, 'imported')).toBe(true);
	});
});

describe('folds belong to the song they were made on', () => {
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
