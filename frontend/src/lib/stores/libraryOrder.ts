import { derived, get, readonly, writable, type Readable } from 'svelte/store';
import { fetchLibraryListen, type LibraryListenItem } from '#lib/api/library.ts';
import { LIBRARY_WALL_PLAYED_PAGE_SIZE, type LibraryWallOrder } from '#lib/constants.ts';
import { libraryWallOrder } from '#lib/stores/ui.ts';
import { compareByCreatedAt } from '#lib/utils/recency.ts';

type LibraryPlaceType = LibraryListenItem['type'];
type OrderedItem = { id: string; title: string };
type LibraryPlace = { type: LibraryPlaceType; item: OrderedItem };
type LastPlayed = { rank: number; at: string };
type LibraryPlaceComparator = (a: LibraryPlace, b: LibraryPlace) => number;

// `known` is false while a page that opens in Last played has not yet heard
// back from Listen: the places stand in no order yet, and showing them in
// title order would be a flash of the wrong one.
type LibraryPlaceOrder = {
	readonly known: boolean;
	readonly compare: LibraryPlaceComparator;
};

// 'failed' only while no read has ranked the places yet: a failed read keeps
// a ranking already known. 'outdated' is a ranking that a listen recorded
// since has overtaken: it keeps the places in order until the next read.
export type ListenReadState = 'unread' | 'failed' | 'ranked' | 'outdated';

const lastPlayed = writable<ReadonlyMap<string, LastPlayed>>(new Map());
const listenRead = writable<ListenReadState>('unread');
const listenedPlaces = writable<readonly LibraryListenItem[]>([]);
export const libraryListenItems = readonly(listenedPlaces);
export const libraryListenState = readonly(listenRead);
let lastPlayedGeneration = 0;
let lastPlayedRead: Promise<boolean> | null = null;
// A listen recorded while a read is out may not be in what it brings back.
let listenRecordedDuringRead = false;
// Places deleted or archived here while a read is out: that read may predate
// the removal, so its answer must not name them. A read started after the
// removal is authoritative, because the server already knows it.
const forgottenDuringRead = new Set<string>();

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

// The order the places last stood in on screen. A viewer who switches to Last
// played keeps seeing it until Listen has answered, while a page that opens
// in Last played has nothing to keep and holds its places instead.
let standingOrder: LibraryPlaceOrder | null = null;

export const libraryPlaceOrder: Readable<LibraryPlaceOrder> = derived(
	[libraryWallOrder, lastPlayed, listenRead],
	([order, byPlace, read]) => {
		const wanted = {
			known: order === 'title' || read !== 'unread',
			compare: comparatorFor(order, byPlace)
		};
		if (wanted.known) standingOrder = wanted;
		return standingOrder ?? wanted;
	}
);

// Holds every place back while the order is not yet known, so no reader
// decides on its own what to show in the meantime.
export function inLibraryOrder<T extends OrderedItem>(
	type: LibraryPlaceType,
	items: readonly T[],
	{ known, compare }: LibraryPlaceOrder
): T[] {
	if (!known) return [];
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

// One read at a time: a caller that asks while a read is out joins it, so
// the wall and both rail groups opening together start a single read. A
// failed read still lets the page stop waiting, standing the places in title
// order until the next read ranks them.
export function readLastPlayed(): Promise<boolean> {
	if (lastPlayedRead !== null) return lastPlayedRead;
	const generation = lastPlayedGeneration;
	listenRecordedDuringRead = false;
	const read = readEveryPlayedPlace().then((places) => {
		if (generation !== lastPlayedGeneration) return false;
		lastPlayedRead = null;
		const forgotten = new Set(forgottenDuringRead);
		forgottenDuringRead.clear();
		if (places === null) {
			listenRead.update((state) => (state === 'ranked' || state === 'outdated' ? state : 'failed'));
			return false;
		}
		const current = places.filter((place) => !forgotten.has(placeKey(place.type, place.id)));
		listenedPlaces.set(current);
		lastPlayed.set(rankedPlaces(current));
		listenRead.set(listenRecordedDuringRead ? 'outdated' : 'ranked');
		return true;
	});
	lastPlayedRead = read;
	return read;
}

function rankedPlaces(places: readonly LibraryListenItem[]): Map<string, LastPlayed> {
	return new Map(
		places.map((place, rank) => [placeKey(place.type, place.id), { rank, at: place.played_at }])
	);
}

// For a caller that only needs a ranking present: it reads only while no
// read has ranked the places, or once a recorded listen has outdated it.
export function ensureLastPlayedRead(): Promise<boolean> {
	return get(listenRead) === 'ranked' ? Promise.resolve(true) : readLastPlayed();
}

// The player calls this once a listen is recorded: a take merely loaded or
// restored is no listen, and Listen ranks only what was recorded.
export function outdateLastPlayedRanking(): void {
	if (lastPlayedRead !== null) listenRecordedDuringRead = true;
	listenRead.update((state) => (state === 'ranked' ? 'outdated' : state));
}

// A place deleted or archived here leaves Listen at once and stays off it
// whatever the collection reloads do meanwhile: Listen stops naming it
// before any read can confirm the removal, and a read already out cannot
// bring it back.
export function forgetListenedPlace(type: LibraryPlaceType, id: string): void {
	if (lastPlayedRead !== null) forgottenDuringRead.add(placeKey(type, id));
	listenedPlaces.update((places) =>
		places.filter((place) => place.type !== type || place.id !== id)
	);
}

// An Undo has put a forgotten place back: Listen reads again and ranks it
// where its listens put it. A read already out may predate the Undo and lack
// the place, so the read that answers starts only after it, and the ranking
// stays outdated until that read succeeds, so the next opening reads again.
export async function readRestoredPlace(type: LibraryPlaceType, id: string): Promise<boolean> {
	forgottenDuringRead.delete(placeKey(type, id));
	if (lastPlayedRead !== null) await lastPlayedRead;
	outdateLastPlayedRanking();
	return readLastPlayed();
}

// Bumping the generation also discards a read still in flight from the test
// before.
export function resetLibraryOrderForTests(): void {
	lastPlayedGeneration++;
	lastPlayedRead = null;
	lastPlayed.set(new Map());
	listenedPlaces.set([]);
	listenRecordedDuringRead = false;
	forgottenDuringRead.clear();
	standingOrder = null;
	listenRead.set('unread');
}
