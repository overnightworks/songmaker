import type { GenerationItem } from '#lib/api/types.ts';
import { takeVersion, type TakeVersion } from '#lib/constants/now-playing.ts';

export type TakeGroupKey = `v${number}` | 'imported';

export interface TakeGroup {
	key: TakeGroupKey;
	// Null for Imported, and for a current version that holds no take yet.
	version: TakeVersion | null;
	versionNumber: number | null;
	generations: GenerationItem[];
	archivedCount: number;
	pick: GenerationItem | null;
}

export interface TakeGroups {
	// The latest saved version: always open, even with no takes.
	current: TakeGroup | null;
	// Newest first, Imported last.
	earlier: TakeGroup[];
}

export const IMPORTED_KEY: TakeGroupKey = 'imported';

export function takeGroupKey(gen: GenerationItem): TakeGroupKey {
	const version = takeVersion(gen.version_id, gen.version_number);
	return version ? `v${version.versionNumber}` : IMPORTED_KEY;
}

function newGroup(key: TakeGroupKey, versionNumber: number | null): TakeGroup {
	return {
		key,
		version: null,
		versionNumber,
		generations: [],
		archivedCount: 0,
		pick: null
	};
}

// `latestVersionNumber` is the current version; a song with no saved version has none.
export function groupTakes(
	generations: GenerationItem[],
	latestVersionNumber: number | null
): TakeGroups {
	const byKey = new Map<TakeGroupKey, TakeGroup>();
	for (const gen of generations) {
		const key = takeGroupKey(gen);
		const version = takeVersion(gen.version_id, gen.version_number);
		let group = byKey.get(key);
		if (!group) {
			group = newGroup(key, version?.versionNumber ?? null);
			group.version = version;
			byKey.set(key, group);
		}
		group.generations.push(gen);
		if (gen.is_archived) group.archivedCount += 1;
		if (gen.is_picked) group.pick = gen;
	}
	const currentKey: TakeGroupKey | null =
		latestVersionNumber === null ? null : `v${latestVersionNumber}`;
	const current =
		currentKey === null
			? null
			: (byKey.get(currentKey) ?? newGroup(currentKey, latestVersionNumber));
	const earlier = [...byKey.values()]
		.filter((group) => group.key !== currentKey)
		.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
	return { current, earlier };
}

// Every take in the order the take list shows them with all versions open.
export function takesInGroupOrder(groups: TakeGroups): GenerationItem[] {
	return [groups.current, ...groups.earlier].flatMap((group) => group?.generations ?? []);
}
