import { derived, writable, type Readable } from 'svelte/store';
import { fetchLibraryContinue, type LibraryContinueItem } from '$lib/api/library';
import { LIBRARY_WALL_RECENT_PAGE_SIZE, type LibraryWallOrder } from '$lib/constants';
import { libraryWallOrder } from '$lib/stores/ui';
import { compareByCreatedAt } from '$lib/utils/recency';

type LibraryPlaceType = LibraryContinueItem['type'];
type OrderedItem = { id: string; title: string; created_at?: string | null };
type LibraryPlace = { type: LibraryPlaceType; item: OrderedItem };
type LastWork = { rank: number; at: string };
type LibraryPlaceComparator = (a: LibraryPlace, b: LibraryPlace) => number;

const recentWork = writable<ReadonlyMap<string, LastWork>>(new Map());
let recentWorkRequest = 0;
let recentWorkPresent: Promise<boolean> | null = null;

export const lastWorkByPlace: Readable<ReadonlyMap<string, LastWork>> = {
	subscribe: recentWork.subscribe
};

function placeKey(type: LibraryPlaceType, id: string): string {
	return `${type}:${id}`;
}

export function lastWorkOf(
	lastWork: ReadonlyMap<string, LastWork>,
	place: LibraryPlace
): LastWork | undefined {
	return lastWork.get(placeKey(place.type, place.item.id));
}

function compareTitles(a: LibraryPlace, b: LibraryPlace): number {
	return compareByCreatedAt(a.item, b.item, 'title');
}

function compareAdded(a: LibraryPlace, b: LibraryPlace): number {
	return compareByCreatedAt(a.item, b.item, 'newest');
}

// A place newer than the last read of Recent has no rank yet; it waits at
// the end in title order until the next read ranks it.
function compareByLastWork(lastWork: ReadonlyMap<string, LastWork>): LibraryPlaceComparator {
	return (a, b) => {
		const aRank = lastWorkOf(lastWork, a)?.rank ?? Number.POSITIVE_INFINITY;
		const bRank = lastWorkOf(lastWork, b)?.rank ?? Number.POSITIVE_INFINITY;
		if (aRank === bRank) return compareTitles(a, b);
		return aRank < bRank ? -1 : 1;
	};
}

function comparatorFor(
	order: LibraryWallOrder,
	lastWork: ReadonlyMap<string, LastWork>
): LibraryPlaceComparator {
	if (order === 'recent') return compareByLastWork(lastWork);
	if (order === 'added') return compareAdded;
	return compareTitles;
}

export const libraryPlaceOrder: Readable<LibraryPlaceComparator> = derived(
	[libraryWallOrder, recentWork],
	([order, lastWork]) => comparatorFor(order, lastWork)
);

export function inLibraryOrder<T extends OrderedItem>(
	type: LibraryPlaceType,
	items: readonly T[],
	compare: LibraryPlaceComparator
): T[] {
	return items.toSorted((a, b) => compare({ type, item: a }, { type, item: b }));
}

async function readEveryRecentPlace(): Promise<LibraryContinueItem[] | null> {
	const places: LibraryContinueItem[] = [];
	try {
		for (;;) {
			const page = await fetchLibraryContinue({
				offset: places.length,
				limit: LIBRARY_WALL_RECENT_PAGE_SIZE
			});
			places.push(...page.items);
			if (page.items.length < LIBRARY_WALL_RECENT_PAGE_SIZE) return places;
		}
	} catch {
		return null;
	}
}

// A failed read keeps the ranking already known; only the newest read may
// replace it. Resolves true when this read became the ranking.
export async function readRecentWork(): Promise<boolean> {
	const request = ++recentWorkRequest;
	const places = await readEveryRecentPlace();
	if (places === null || request !== recentWorkRequest) return false;
	recentWork.set(
		new Map(
			places.map((place, rank) => [placeKey(place.type, place.id), { rank, at: place.activity_at }])
		)
	);
	return true;
}

export function ensureRecentWorkRead(): Promise<boolean> {
	recentWorkPresent ??= readRecentWork().then((applied) => {
		if (!applied) recentWorkPresent = null;
		return applied;
	});
	return recentWorkPresent;
}

export function resetLibraryOrderForTests(): void {
	recentWorkRequest = 0;
	recentWorkPresent = null;
	recentWork.set(new Map());
}
