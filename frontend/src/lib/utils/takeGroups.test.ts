import { describe, expect, it } from 'vitest';
import { makeTakeOfVersion, makeTakesAcrossVersions } from '#lib/test-utils/factories.ts';
import { groupTakes, takeGroupKey, takesInGroupOrder } from './takeGroups';

const SONG_TAKES = makeTakesAcrossVersions();

describe('groupTakes (rules 1, 2 and 5, cells 1/8/9)', () => {
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
		expect(groupTakes([makeTakeOfVersion('a1', 2)], 3).current?.generations).toEqual([]);
		expect(groupTakes([makeTakeOfVersion('a1', 2)], null).current).toBeNull();
	});

	it('names the group of a take by its version, and Imported when it has none', () => {
		expect(takeGroupKey(makeTakeOfVersion('c1', 3))).toBe('v3');
		expect(takeGroupKey(makeTakeOfVersion('i1', null))).toBe('imported');
		expect(takeGroupKey(makeTakeOfVersion('i2', 3, { version_id: null }))).toBe('imported');
	});
});

describe('takesInGroupOrder', () => {
	it("lists the current version first, then the earlier ones, Imported last, keeping each version's order", () => {
		expect(takesInGroupOrder(groupTakes(SONG_TAKES, 3)).map((gen) => gen.id)).toEqual([
			'c1',
			'a1',
			'a2',
			'o1',
			'i1'
		]);
	});
});
