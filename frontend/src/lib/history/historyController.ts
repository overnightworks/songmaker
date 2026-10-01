import type { NavigationType } from '@sveltejs/kit';
import { goto, pushState, replaceState } from '$app/navigation';

// The one owner of the tab's history (issue #1006, ruling of 01.10.2026): only
// this module writes or traverses history. Every entry it writes carries an
// id, so a landing -- a Back, a Forward, a jump of several entries, or one of
// the controller's own step-backs -- says by itself where history now stands,
// and which open layers and pending step-backs it has left behind.

// What the controller stamps into an entry's page state. `layer` marks an entry
// an open layer pushed over the page it covers.
export interface HistoryEntry {
	readonly id: number;
	readonly layer?: string;
}

interface OpenLayerEntry {
	readonly layer: string;
	readonly entry: number;
}

// What the controller knows between two landings: the open layers that own an
// entry (lowest first), the targets of its own step-backs that have not landed
// yet, and the page entry the screen shows under every open layer.
interface HistoryLedger {
	readonly layers: readonly OpenLayerEntry[];
	readonly stepBacks: readonly number[];
	readonly current: HistoryEntry | null;
}

interface Landing {
	readonly dropLayers: readonly OpenLayerEntry[];
	readonly settled: readonly number[];
	readonly stepOff: boolean;
	readonly apply: boolean;
	readonly ledger: HistoryLedger;
}

// SvelteKit keeps an entry's page state under this key; its own constant is
// internal to the package and not exported.
const SVELTEKIT_HISTORY_STATES_KEY = 'sveltekit:states';
const ENTRY_ID_COUNTER_KEY = 'songmaker:history-entry-id';
const FIRST_ENTRY_KEY = 'songmaker:history-first-entry';
const FOREIGN_ENTRY_RANK = Number.NEGATIVE_INFINITY;
const EMPTY_LEDGER: HistoryLedger = { layers: [], stepBacks: [], current: null };

function rankOf(entry: HistoryEntry | null): number {
	return entry?.id ?? FOREIGN_ENTRY_RANK;
}

function isSameEntry(a: HistoryEntry | null, b: HistoryEntry | null): boolean {
	return a !== null && b !== null && a.id === b.id;
}

// Ids grow with every push, so an entry below the landing has a lower id. An
// entry without one was not written by the controller -- the page the tab
// loaded onto, or one from before it -- and ranks below every id. Whoever
// caused the landing, it settles every step-back it reached, which is how a
// user's Back racing one of the controller's own converges on the last one.
export function land(ledger: HistoryLedger, landed: HistoryEntry | null): Landing {
	const rank = rankOf(landed);
	const layers = ledger.layers.filter((open) => open.entry <= rank);
	const onLayerEntry = landed?.layer !== undefined;
	const ownedByOpenLayer = layers.some(
		(open) => open.entry === rank && open.layer === landed?.layer
	);
	const apply = !onLayerEntry && !isSameEntry(landed, ledger.current);
	return {
		dropLayers: ledger.layers.filter((open) => open.entry > rank).reverse(),
		settled: ledger.stepBacks.filter((target) => target >= rank),
		stepOff: onLayerEntry && !ownedByOpenLayer,
		apply,
		ledger: {
			layers,
			stepBacks: ledger.stepBacks.filter((target) => target < rank),
			current: onLayerEntry ? ledger.current : landed
		}
	};
}

// Read and incremented on every allocation, never cached: a reload, a
// bfcache restore or a return from another document starts this module afresh
// in the same tab, and must still never hand out an id an entry already has.
export function allocateEntryId(storage: Pick<Storage, 'getItem' | 'setItem'>): number {
	const id = lastAllocatedEntryId(storage) + 1;
	storage.setItem(ENTRY_ID_COUNTER_KEY, String(id));
	return id;
}

function lastAllocatedEntryId(storage: Pick<Storage, 'getItem'>): number {
	return storedCount(storage, ENTRY_ID_COUNTER_KEY, 'history entry counter');
}

function storedCount(storage: Pick<Storage, 'getItem'>, key: string, what: string): number {
	const stored = storage.getItem(key) ?? '0';
	if (!/^\d+$/.test(stored)) {
		throw new Error(`The ${what} holds ${JSON.stringify(stored)}, not a count`);
	}
	return Number(stored);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function isHistoryEntry(value: unknown): value is HistoryEntry {
	return (
		isRecord(value) &&
		Number.isSafeInteger(value.id) &&
		(value.id as number) > 0 &&
		(value.layer === undefined || typeof value.layer === 'string')
	);
}

// The one reader of SvelteKit's page state in a history entry, which it keeps
// under its own key beside its router bookkeeping; an entry without it was
// not written by the router.
export function pageStateOfHistoryState(state: unknown): Record<string, unknown> | null {
	if (!isRecord(state)) return null;
	const pageState = state[SVELTEKIT_HISTORY_STATES_KEY];
	return isRecord(pageState) ? pageState : null;
}

function entryOfHistoryState(state: unknown): HistoryEntry | null {
	const entry = pageStateOfHistoryState(state)?.entry;
	return isHistoryEntry(entry) ? entry : null;
}

export function landedEntry(event: PopStateEvent): HistoryEntry | null {
	return entryOfHistoryState(event.state);
}

// SvelteKit's start writes its own entry over the one the page loads onto and
// drops the page state that entry carried, so the state is read while this
// module loads, before the router starts.
let stateOnLoad: unknown = history.state;
let ledger: HistoryLedger = EMPTY_LEDGER;
// Whether history stands on its top entry, the only place an id-less entry may
// get an id: ids grow bottom to top, so a first id given further down would
// outrank the entries above it, and a step-back from one of those would never
// see its landing as reaching its target. A landing leaves the top as far as
// the controller can tell, a push reaches it again.
let standsOnTop = standsOnTopOnLoad();
const stepBackWaiters = new Map<number, (() => void)[]>();

function standsOnTopOnLoad(): boolean {
	const loaded = entryOfHistoryState(stateOnLoad);
	if (loaded !== null) return loaded.id === lastAllocatedEntryId(sessionStorage);
	return !documentReturnedTo();
}

// A reload or a Back or Forward from another document returns to an entry
// that may have entries above it; any other load is a new entry on top.
// jsdom reports no navigation timing, which reads as a new entry.
function documentReturnedTo(): boolean {
	const [timing] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
	return timing?.type === 'reload' || timing?.type === 'back_forward';
}

export function historyStateOnLoad(): unknown {
	return stateOnLoad;
}

function newEntry(layer?: string): HistoryEntry {
	const id = allocateEntryId(sessionStorage);
	return layer === undefined ? { id } : { id, layer };
}

// The id an id-less entry on top gets; the tab's only entry is its first one,
// below which nothing is left to step back to.
function firstIdOnTop(): HistoryEntry | null {
	if (!standsOnTop) return null;
	const entry = newEntry();
	if (history.length === 1) sessionStorage.setItem(FIRST_ENTRY_KEY, String(entry.id));
	return entry;
}

function stampedPageState(state: App.PageState, entry: HistoryEntry | null): App.PageState {
	return entry === null ? state : { ...state, entry };
}

function settleOnPage(entry: HistoryEntry | null): void {
	if (entry?.layer === undefined) ledger = { ...ledger, current: entry };
}

// A push allocates an id; an entry pushed for a layer belongs to that layer
// until a landing leaves it.
export function pushEntry(url: string, state: App.PageState, layer?: string): HistoryEntry {
	const entry = newEntry(layer);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	pushState(url, stampedPageState(state, entry));
	standsOnTop = true;
	ledger =
		layer === undefined
			? { ...ledger, current: entry }
			: { ...ledger, layers: [...ledger.layers, { layer, entry: entry.id }] };
	return entry;
}

// A replace rewrites what an entry shows, never which entry it is: it keeps
// the id and the layer mark. An id-less entry gets its first id here while it
// is the top entry, and stays foreign below it.
export function replaceEntry(url: string, state: App.PageState): HistoryEntry | null {
	const entry = entryOfHistoryState(history.state) ?? firstIdOnTop();
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	replaceState(url, stampedPageState(state, entry));
	settleOnPage(entry);
	return entry;
}

interface NavigateOptions {
	readonly replaceState: boolean;
	readonly noScroll: boolean;
	readonly keepFocus: boolean;
	readonly state: App.PageState;
}

// A navigation through the router carries its entry the way a shallow write
// does: a push a fresh id, a replace the id of the entry it writes over.
export function navigateTo(url: string, options: NavigateOptions): Promise<void> {
	const entry = options.replaceState
		? (entryOfHistoryState(history.state) ?? firstIdOnTop())
		: newEntry();
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	return goto(url, { ...options, state: stampedPageState(options.state, entry) });
}

// Every navigation the router reports once it has written its entry: a link
// or a `goto` from anywhere, or -- on `enter` -- its start over the entry the
// page loaded onto. An entry the navigation carried stands as it is, one the
// start dropped gets back the id it was loaded with, and any other gets a
// first id on top. A Back or Forward is the landing listener's.
export function stampNavigatedEntry(type: NavigationType): void {
	if (type === 'popstate') return;
	const carried = entryOfHistoryState(history.state);
	if (carried !== null) {
		if (carried.id === lastAllocatedEntryId(sessionStorage)) standsOnTop = true;
		settleOnPage(carried);
		return;
	}
	const loaded = type === 'enter' ? entryOfHistoryState(stateOnLoad) : null;
	const entry = loaded ?? firstIdOnTop();
	if (entry !== null) {
		const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- the address the router has just written
		replaceState(location.href, stampedPageState(pageState, entry));
	}
	settleOnPage(entry);
}

// Steps back once and resolves when a landing at or below `target` settles the
// step, whichever Back or Forward that landing came from. Below the tab's
// first entry there is nothing to step back to, and no landing would follow.
export function stepBackTo(target: number): Promise<void> {
	if (target < firstEntryOfTab()) return Promise.resolve();
	ledger = { ...ledger, stepBacks: [...ledger.stepBacks, target] };
	const settled = new Promise<void>((resolve) => {
		stepBackWaiters.set(target, [...(stepBackWaiters.get(target) ?? []), resolve]);
	});
	history.back();
	return settled;
}

function firstEntryOfTab(): number {
	if (sessionStorage.getItem(FIRST_ENTRY_KEY) === null) return FOREIGN_ENTRY_RANK;
	return storedCount(sessionStorage, FIRST_ENTRY_KEY, 'first history entry');
}

// From an entry with an id, any landing below it is the step's; from a
// foreign one nothing tells the step's landing apart, so the next landing is.
export function stepBackOffStandingEntry(): Promise<void> {
	const standing = entryOfHistoryState(history.state);
	return stepBackTo(standing === null ? Number.POSITIVE_INFINITY : standing.id - 1);
}

function settleStepBack(target: number): void {
	const [settle, ...waiting] = stepBackWaiters.get(target) ?? [];
	if (waiting.length > 0) stepBackWaiters.set(target, waiting);
	else stepBackWaiters.delete(target);
	settle?.();
}

// The landing handler hears each landing once the controller has settled its
// step-backs and, on a layer entry no open layer owns, started stepping off it.
export function listenForLandings(
	onLanding: (landing: Landing, event: PopStateEvent) => void
): () => void {
	function onPopstate(event: PopStateEvent): void {
		const landed = landedEntry(event);
		const landing = land(ledger, landed);
		ledger = landing.ledger;
		standsOnTop = false;
		for (const target of landing.settled) settleStepBack(target);
		if (landing.stepOff) void stepBackTo(rankOf(landed) - 1);
		onLanding(landing, event);
	}
	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

// A page load, as far as history goes: the state the page loaded onto is read
// again, the way this module's own load reads it.
export function loadHistoryPageForTests(): void {
	stateOnLoad = history.state;
	standsOnTop = standsOnTopOnLoad();
}

export function resetHistoryControllerForTests(): void {
	stateOnLoad = history.state;
	ledger = EMPTY_LEDGER;
	standsOnTop = true;
	stepBackWaiters.clear();
}
