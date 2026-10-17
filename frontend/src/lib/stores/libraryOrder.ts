import { derived, get, writable, type Readable } from 'svelte/store';
import { fetchLibraryListen, type LibraryListenItem } from '$lib/api/library';
import { LIBRARY_WALL_PLAYED_PAGE_SIZE, type LibraryWallOrder } from '$lib/constants';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { libraryWallOrder } from '$lib/stores/ui';
import { compareByCreatedAt } from '$lib/utils/recency';

type LibraryPlaceType = LibraryListenItem['type'];
type OrderedItem = { id: string; title: string };
type LibraryPlace = { type: LibraryPlaceType; item: OrderedItem };
type LastPlayed = { rank: number; at: string };
type LibraryPlaceComparator = (a: LibraryPlace, b: LibraryPlace) => number;

// `known` is false while a page that opens in Last played has not yet heard
// back from Listen: the places stand in no order yet, and showing them in
// title order would be a flash of the wrong one.
export type LibraryPlaceOrder = {
	readonly known: boolean;
	readonly compare: LibraryPlaceComparator;
};

// 'failed' only while no read has ranked the places yet: a failed read keeps
// a ranking already known.
type ListenReadState = 'unread' | 'failed' | 'ranked';

const lastPlayed = writable<ReadonlyMap<string, LastPlayed>>(new Map());
const listenRead = writable<ListenReadState>('unread');
let lastPlayedGeneration = 0;
let lastPlayedRead: Promise<boolean> | null = null;
// Playing another take records a listen the ranking has not seen.
let takeInPlaybackWhenRanked: string | null = null;

function takeInPlayback(): string | null {
	return audioPlayer.current?.generation.id ?? null;
}

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
	if (lastPlayedRead) return lastPlayedRead;
	const generation = lastPlayedGeneration;
	const takeInPlaybackWhenAsked = takeInPlayback();
	const read = readEveryPlayedPlace().then((places) => {
		if (generation !== lastPlayedGeneration) return false;
		lastPlayedRead = null;
		if (places === null) {
			listenRead.update((state) => (state === 'ranked' ? state : 'failed'));
			return false;
		}
		lastPlayed.set(rankedPlaces(places));
		takeInPlaybackWhenRanked = takeInPlaybackWhenAsked;
		listenRead.set('ranked');
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
// read has ranked the places, or once another take has started playing.
export function ensureLastPlayedRead(): Promise<boolean> {
	const outdatedByPlayback = takeInPlayback() !== takeInPlaybackWhenRanked;
	return get(listenRead) === 'ranked' && !outdatedByPlayback
		? Promise.resolve(true)
		: readLastPlayed();
}

// Bumping the generation also discards a read still in flight from the test
// before.
export function resetLibraryOrderForTests(): void {
	lastPlayedGeneration++;
	lastPlayedRead = null;
	lastPlayed.set(new Map());
	takeInPlaybackWhenRanked = null;
	standingOrder = null;
	listenRead.set('unread');
}
