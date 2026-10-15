import { derived, writable, type Readable } from 'svelte/store';
import { fetchLibraryListen, type LibraryListenItem } from '$lib/api/library';
import { LIBRARY_WALL_PLAYED_PAGE_SIZE, type LibraryWallOrder } from '$lib/constants';
import { libraryWallOrder } from '$lib/stores/ui';
import { compareByCreatedAt } from '$lib/utils/recency';

type LibraryPlaceType = LibraryListenItem['type'];
type OrderedItem = { id: string; title: string };
type LibraryPlace = { type: LibraryPlaceType; item: OrderedItem };
type LastPlayed = { rank: number; at: string };
type LibraryPlaceComparator = (a: LibraryPlace, b: LibraryPlace) => number;

const lastPlayed = writable<ReadonlyMap<string, LastPlayed>>(new Map());
let lastPlayedRequest = 0;
let lastPlayedPresent: Promise<boolean> | null = null;

export const lastPlayedByPlace: Readable<ReadonlyMap<string, LastPlayed>> = {
	subscribe: lastPlayed.subscribe
};

function placeKey(type: LibraryPlaceType, id: string): string {
	return `${type}:${id}`;
}

export function lastPlayedOf(
	byPlace: ReadonlyMap<string, LastPlayed>,
	place: LibraryPlace
): LastPlayed | undefined {
	return byPlace.get(placeKey(place.type, place.item.id));
}

function compareTitles(a: LibraryPlace, b: LibraryPlace): number {
	return compareByCreatedAt(a.item, b.item, 'title');
}

// A place without a rank waits at the end in title order: one the viewer
// has never listened in, which Listen never ranks, and one newer than the
// last read of Listen until the next read ranks it.
function compareByLastPlayed(byPlace: ReadonlyMap<string, LastPlayed>): LibraryPlaceComparator {
	return (a, b) => {
		const aRank = lastPlayedOf(byPlace, a)?.rank ?? Number.POSITIVE_INFINITY;
		const bRank = lastPlayedOf(byPlace, b)?.rank ?? Number.POSITIVE_INFINITY;
		if (aRank === bRank) return compareTitles(a, b);
		return aRank < bRank ? -1 : 1;
	};
}

function comparatorFor(
	order: LibraryWallOrder,
	byPlace: ReadonlyMap<string, LastPlayed>
): LibraryPlaceComparator {
	return order === 'played' ? compareByLastPlayed(byPlace) : compareTitles;
}

export const libraryPlaceOrder: Readable<LibraryPlaceComparator> = derived(
	[libraryWallOrder, lastPlayed],
	([order, byPlace]) => comparatorFor(order, byPlace)
);

export function inLibraryOrder<T extends OrderedItem>(
	type: LibraryPlaceType,
	items: readonly T[],
	compare: LibraryPlaceComparator
): T[] {
	return items.toSorted((a, b) => compare({ type, item: a }, { type, item: b }));
}

async function readEveryPlayedPlace(): Promise<LibraryListenItem[] | null> {
	const places: LibraryListenItem[] = [];
	try {
		for (;;) {
			const page = await fetchLibraryListen({
				offset: places.length,
				limit: LIBRARY_WALL_PLAYED_PAGE_SIZE
			});
			places.push(...page.items);
			if (page.items.length < LIBRARY_WALL_PLAYED_PAGE_SIZE) return places;
		}
	} catch {
		return null;
	}
}

// A failed read keeps the ranking already known; only the newest read may
// replace it.
export async function readLastPlayed(): Promise<boolean> {
	const request = ++lastPlayedRequest;
	const places = await readEveryPlayedPlace();
	if (places === null || request !== lastPlayedRequest) return false;
	lastPlayed.set(
		new Map(
			places.map((place, rank) => [placeKey(place.type, place.id), { rank, at: place.played_at }])
		)
	);
	return true;
}

export function ensureLastPlayedRead(): Promise<boolean> {
	lastPlayedPresent ??= readLastPlayed().then((applied) => {
		if (!applied) lastPlayedPresent = null;
		return applied;
	});
	return lastPlayedPresent;
}

// Bumping the request number rather than zeroing it also discards a read
// still in flight from the test before.
export function resetLibraryOrderForTests(): void {
	lastPlayedRequest++;
	lastPlayedPresent = null;
	lastPlayed.set(new Map());
}
