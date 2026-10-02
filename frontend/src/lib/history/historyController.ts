import type { BeforeNavigate, NavigationType } from '@sveltejs/kit';
import { untrack } from 'svelte';
import { goto, pushState, replaceState } from '$app/navigation';
import {
	dropLayersFrom,
	keepLayerHistory,
	stackedLayers,
	type Layer,
	type LayerHistory
} from '$lib/stores/layers';

// The one owner of the tab's history (issue #1006, ruling of 01.10.2026): only
// this module writes or traverses history. Every entry it writes carries an
// id, so a landing -- a Back, a Forward, a jump of several entries, or one of
// the controller's own step-backs -- says by itself where history now stands,
// and which open layers and pending step-backs it has left behind. While the
// library history runs, every layer opened on the stack (stores/layers.ts)
// owns one entry on top of the page it covers.

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

export interface Landing {
	readonly dropLayers: readonly OpenLayerEntry[];
	readonly settled: readonly number[];
	readonly stepOff: boolean;
	readonly apply: boolean;
	readonly ledger: HistoryLedger;
}

// SvelteKit keeps an entry's page state under this key; its own constant is
// internal to the package and not exported.
const SVELTEKIT_HISTORY_STATES_KEY = 'sveltekit:states';
const SVELTEKIT_HISTORY_INDEX_KEY = 'sveltekit:history';
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
export function allocateEntryId(storage: TabStorage): number {
	const id = lastAllocatedEntryId(storage) + 1;
	storage.setItem(ENTRY_ID_COUNTER_KEY, String(id));
	return id;
}

function lastAllocatedEntryId(storage: Pick<Storage, 'getItem'>): number {
	return storedCount(storage, ENTRY_ID_COUNTER_KEY, 'history entry counter');
}

// Storage that refused writes forgets the counter with the document, while the
// tab's entries keep their ids: the counter catches up with every entry this
// document meets, so an id it hands out never repeats or undercuts one below.
// With storage that keeps the counter, no entry ever outranks it.
function countEntryMet(storage: TabStorage, met: HistoryEntry | null): void {
	if (met !== null && met.id > lastAllocatedEntryId(storage)) {
		storage.setItem(ENTRY_ID_COUNTER_KEY, String(met.id));
	}
}

function storedCount(storage: Pick<Storage, 'getItem'>, key: string, what: string): number {
	const stored = storage.getItem(key) ?? '0';
	if (!/^\d+$/.test(stored)) {
		throw new Error(`The ${what} holds ${JSON.stringify(stored)}, not a count`);
	}
	return Number(stored);
}

type TabStorage = Pick<Storage, 'getItem' | 'setItem'>;

// The names a browser refuses storage under: a full quota, a private mode that
// offers storage but will not keep anything in it, or site data blocked so that
// even reaching session storage is denied.
const STORAGE_REFUSALS: ReadonlySet<string> = new Set(['QuotaExceededError', 'SecurityError']);

function isStorageRefusal(error: unknown): boolean {
	return error instanceof DOMException && STORAGE_REFUSALS.has(error.name);
}

// The tab's counts live in session storage so that a reload keeps them. Once
// the browser refuses storage -- reaching it, reading it or writing it -- they
// live in this document's memory instead, seeded by whatever storage still
// gives and raised by every entry the document meets, rather than the page
// failing to render. Storage is never reached unguarded: not on use, and not
// while the module loads onto an entry and counts it.
function tabStorage(reachStorage: () => TabStorage): TabStorage {
	let memoryAfterRefusal: Map<string, string> | null = null;

	function memoryAfter(error: unknown): Map<string, string> {
		if (!isStorageRefusal(error)) throw error;
		memoryAfterRefusal ??= new Map();
		return memoryAfterRefusal;
	}

	return {
		getItem: (key) => {
			const remembered = memoryAfterRefusal?.get(key);
			if (remembered !== undefined) return remembered;
			try {
				return reachStorage().getItem(key);
			} catch (error) {
				memoryAfter(error);
				return null;
			}
		},
		setItem: (key, value) => {
			if (memoryAfterRefusal !== null) {
				memoryAfterRefusal.set(key, value);
				return;
			}
			try {
				reachStorage().setItem(key, value);
			} catch (error) {
				memoryAfter(error).set(key, value);
			}
		}
	};
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

// The entry history stands on, as the controller stamped it.
function standingEntry(): HistoryEntry | null {
	return entryOfHistoryState(history.state);
}

// SvelteKit's place for an entry among the tab's entries: one more than the
// entry it was pushed over, the same as the entry it was written over.
function routerIndexOf(state: unknown): number | undefined {
	const index = isRecord(state) ? state[SVELTEKIT_HISTORY_INDEX_KEY] : undefined;
	return typeof index === 'number' ? index : undefined;
}

export function landedEntry(event: PopStateEvent): HistoryEntry | null {
	return entryOfHistoryState(event.state);
}

// SvelteKit's start writes its own entry over the one the page loads onto and
// drops the page state that entry carried, so the state is read while this
// module loads, before the router starts.
let historyStorage = tabStorage(() => sessionStorage);
let stateOnLoad: unknown = readStateOnLoad();
let ledger: HistoryLedger = EMPTY_LEDGER;
// Whether history stands on its top entry, the only place an id-less entry may
// get an id: ids grow bottom to top, so a first id given further down would
// outrank the entries above it, and a step-back from one of those would never
// see its landing as reaching its target. A landing leaves the top as far as
// the controller can tell, a push reaches it again.
let standsOnTop = standsOnTopOnLoad();
// The router's place of the entry history stood on when the controller last
// looked, which tells a router push from a router replace.
let lastRouterIndex = routerIndexOf(history.state);
const stepBackWaiters = new Map<number, (() => void)[]>();
let stepBacksLandedWaiters: (() => void)[] = [];
let navigationsUnderway = 0;
let loadingMount: NavigateOptions | null = null;
const entryOfLayer = new Map<Layer, number>();
let layersAwaitingEntry: Layer[] = [];

function readStateOnLoad(): unknown {
	countEntryMet(historyStorage, entryOfHistoryState(history.state));
	return history.state;
}

function standsOnTopOnLoad(): boolean {
	const loaded = entryOfHistoryState(stateOnLoad);
	if (loaded !== null) return loaded.id === lastAllocatedEntryId(historyStorage);
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
	const id = allocateEntryId(historyStorage);
	return layer === undefined ? { id } : { id, layer };
}

// The id an id-less entry on top gets; the tab's only entry is its first one,
// below which nothing is left to step back to.
function firstIdOnTop(): HistoryEntry | null {
	if (!standsOnTop) return null;
	const entry = newEntry();
	if (history.length === 1) historyStorage.setItem(FIRST_ENTRY_KEY, String(entry.id));
	return entry;
}

function stampedPageState(state: App.PageState, entry: HistoryEntry | null): App.PageState {
	return entry === null ? state : { ...state, entry };
}

function settleOnPage(entry: HistoryEntry | null): void {
	if (entry?.layer === undefined) ledger = { ...ledger, current: entry };
}

// A page pushed on top closes the layers open below it (issue #1006, ruling
// of 01.10.2026): an overlay belongs to the page it covers.
function pushedPage(entry: HistoryEntry): void {
	standsOnTop = true;
	dropLayers(ledger.layers);
	ledger = { ...ledger, layers: [], current: entry };
}

// A push allocates an id; an entry pushed for a layer belongs to that layer
// until a landing leaves it.
export function pushEntry(url: string, state: App.PageState, layer?: string): HistoryEntry {
	const entry = newEntry(layer);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	pushState(url, stampedPageState(state, entry));
	lastRouterIndex = routerIndexOf(history.state);
	if (layer === undefined) {
		pushedPage(entry);
		return entry;
	}
	standsOnTop = true;
	ledger = { ...ledger, layers: [...ledger.layers, { layer, entry: entry.id }] };
	return entry;
}

// A replace rewrites what an entry shows, never which entry it is: it keeps
// the id and the layer mark. An id-less entry gets its first id here while it
// is the top entry, and stays foreign below it.
export function replaceEntry(url: string, state: App.PageState): HistoryEntry | null {
	const entry = entryOfHistoryState(history.state) ?? firstIdOnTop();
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	replaceState(url, stampedPageState(state, entry));
	lastRouterIndex = routerIndexOf(history.state);
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
// While it loads, history is not still: the router writes its entry only
// once the route has loaded, over whatever entry stands then. A replace to
// the address history already stands on moves nothing: it mounts the route of
// the entry standing there, and history stays still meanwhile.
export async function navigateTo(url: string, options: NavigateOptions): Promise<void> {
	const entry = options.replaceState
		? (entryOfHistoryState(history.state) ?? firstIdOnTop())
		: newEntry();
	const mount = options.replaceState && standsOnAddress(url) ? options : null;
	if (mount === null) navigationsUnderway += 1;
	else loadingMount = mount;
	try {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
		await goto(url, { ...options, state: stampedPageState(options.state, entry) });
		if (entry !== null && standingEntry()?.id === entry.id) navigatedOnto(entry, options);
	} finally {
		if (mount === null) navigationsUnderway -= 1;
		else if (loadingMount === mount) loadingMount = null;
		settleStillness();
	}
}

function standsOnAddress(url: string): boolean {
	return new URL(url, location.href).href === location.href;
}

// Shallow routing leaves the mounted route where the last navigation put it,
// so a route can mount, or resolve, under an address it does not name: Back
// from another page onto an entry shallow routing wrote has the router load
// the route of the page that entry was written over (album A, album B opened
// over it, Settings, Back), and an entry put back over a landing moves the
// address on while the landed route loads. The address wins (issue #1006, H3):
// the route of the address history stands on is mounted over it, under the
// same entry, superseding the other route's load if it is still loading.
export type RouteOnAddress = 'stands' | 'remounts';

export function mountAddressOver(routeUrl: string): RouteOnAddress {
	if (new URL(routeUrl, location.href).pathname === location.pathname) return 'stands';
	const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
	void navigateTo(location.href, {
		replaceState: true,
		noScroll: true,
		keepFocus: true,
		state: pageState
	});
	return 'remounts';
}

// A Back or Forward that navigates mounts the address it lands on before the
// router loads anything of the page under it. Every other navigation's target
// is an address history has yet to move to.
export function mountRouteOfLandedAddress(navigation: Pick<BeforeNavigate, 'type' | 'to'>): void {
	if (navigation.type === 'popstate' && navigation.to !== null) {
		mountAddressOver(navigation.to.url.href);
	}
}

// A shallow write while a route mounts issues the mount again over the entry
// it wrote: the router writes over whichever entry stands once the route has
// loaded, so the older mount would land on that entry with the page state it
// started with, and the entry would lose its own.
export function remountOverStandingEntry(url: string, state: App.PageState): Promise<void> {
	if (loadingMount === null) return Promise.resolve();
	return navigateTo(url, { ...loadingMount, state });
}

// A navigation another one superseded wrote no entry of its own, so only one
// whose entry stands settles the page.
function navigatedOnto(entry: HistoryEntry, options: NavigateOptions): void {
	lastRouterIndex = routerIndexOf(history.state);
	if (options.replaceState) settleOnPage(entry);
	else pushedPage(entry);
}

// Every navigation the router reports once it has written its entry: a link
// or a `goto` from anywhere, or -- on `enter` -- its start over the entry the
// page loaded onto. An entry the navigation carried stands as it is, one the
// start dropped gets back the id it was loaded with, and any other gets a
// first id on top. A Back or Forward is the landing listener's.
export function stampNavigatedEntry(type: NavigationType): void {
	if (type === 'popstate') {
		lastRouterIndex = routerIndexOf(history.state);
		return;
	}
	const routerPushed = isRouterPush();
	lastRouterIndex = routerIndexOf(history.state);
	const carried = entryOfHistoryState(history.state);
	if (carried !== null) {
		if (carried.id === lastAllocatedEntryId(historyStorage)) standsOnTop = true;
		if (routerPushed) pushedPage(carried);
		else settleOnPage(carried);
		return;
	}
	if (routerPushed) standsOnTop = true;
	const loaded = type === 'enter' ? entryOfHistoryState(stateOnLoad) : null;
	const entry = loaded ?? firstIdOnTop();
	if (entry !== null) {
		const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- the address the router has just written
		replaceState(location.href, stampedPageState(pageState, entry));
	}
	if (routerPushed && entry !== null) pushedPage(entry);
	else settleOnPage(entry);
}

// A router push -- a link, or a `goto` from anywhere -- stands one place above
// the entry the controller last saw, a replace on that same place.
function isRouterPush(): boolean {
	const index = routerIndexOf(history.state);
	return index !== undefined && lastRouterIndex !== undefined && index === lastRouterIndex + 1;
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
	if (historyStorage.getItem(FIRST_ENTRY_KEY) === null) return FOREIGN_ENTRY_RANK;
	return storedCount(historyStorage, FIRST_ENTRY_KEY, 'first history entry');
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

export function ownStepBacksUnderway(): boolean {
	return ledger.stepBacks.length > 0;
}

// Resolves once none of the controller's own step-backs is still underway: a
// write issued after one lands on the entry it steps back to.
export function ownStepBacksLanded(): Promise<void> {
	if (!ownStepBacksUnderway()) return Promise.resolve();
	return new Promise((resolve) => stepBacksLandedWaiters.push(resolve));
}

// Once history stands still -- no own step-back underway and no navigation
// loading -- the layers opened meanwhile get their entries, in the order they
// opened, on top of the entry that then stands.
function settleStillness(): void {
	if (ownStepBacksUnderway()) return;
	const waiting = stepBacksLandedWaiters;
	stepBacksLandedWaiters = [];
	for (const resolve of waiting) resolve();
	if (navigationsUnderway > 0) return;
	const awaiting = layersAwaitingEntry;
	layersAwaitingEntry = [];
	for (const layer of awaiting) pushLayerEntry(layer);
}

// The controller's side of the layer stack: a layer held while history moves
// waits for it to stand still, since an entry pushed meanwhile would land
// under the step's own landing. A layer held while a route only mounts gets
// its entry at once, or a Back pressed before the route has loaded would
// leave the page under it instead of closing it. A layer leaving from the
// entry history stands on steps back off it; one whose entry stands lower
// leaves it to the landing that reaches it, which steps off an entry no open
// layer owns.
const layerEntries: LayerHistory = {
	held(layer) {
		if (ownStepBacksUnderway() || navigationsUnderway > 0) {
			layersAwaitingEntry = [...layersAwaitingEntry, layer];
			return;
		}
		pushLayerEntry(layer);
	},
	left(layer) {
		if (layersAwaitingEntry.includes(layer)) {
			layersAwaitingEntry = layersAwaitingEntry.filter((awaiting) => awaiting !== layer);
			return;
		}
		const entry = entryOfLayer.get(layer);
		if (entry === undefined) return;
		entryOfLayer.delete(layer);
		ledger = { ...ledger, layers: ledger.layers.filter((open) => open.entry !== entry) };
		if (standingEntry()?.id === entry) void stepBackOffStandingEntry();
	}
};

// The entry is a copy of the page it covers, at the same address. Pushed from
// inside an effect -- a dialog holding its layer as it mounts -- SvelteKit's
// shallow writer would read `page.url` into that effect and re-run it on the
// next Back, pushing an entry nobody owns.
function pushLayerEntry(layer: Layer): void {
	untrack(() => {
		const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
		entryOfLayer.set(layer, pushEntry(location.href, pageState, layer.id).id);
		void remountOverStandingEntry(location.href, pageState);
	});
}

function dropLayers(open: readonly OpenLayerEntry[]): void {
	const left = new Set(open.map((layer) => layer.entry));
	const depth = stackedLayers().findIndex((layer) => left.has(entryOfLayer.get(layer) ?? NaN));
	for (const [layer, entry] of entryOfLayer) if (left.has(entry)) entryOfLayer.delete(layer);
	if (depth !== -1) dropLayersFrom(depth);
}

// A layer entry history stands on that no open layer owns -- one a reload
// came back onto -- is a copy of the page below it, where Back would visibly
// do nothing.
function stepOffUnownedLayerEntry(): void {
	const standing = standingEntry();
	if (standing?.layer === undefined) return;
	if (ledger.layers.some((open) => open.entry === standing.id)) return;
	void stepBackTo(standing.id - 1);
}

// The library history stops: the overlays still open keep their layers, which
// own no history entry any more, and nothing waits for a landing nobody hears.
export function forgetLayerEntries(): void {
	keepLayerHistory(null);
	entryOfLayer.clear();
	layersAwaitingEntry = [];
	ledger = { ...ledger, layers: [], stepBacks: [] };
	for (const target of Array.from(stepBackWaiters.keys())) {
		while (stepBackWaiters.has(target)) settleStepBack(target);
	}
	settleStillness();
}

// The landing handler hears each landing once the controller has closed the
// layers it left, settled its step-backs and, on a layer entry no open layer
// owns, started stepping off it. While it listens, every layer opened owns an
// entry.
export function listenForLandings(
	onLanding: (landing: Landing, event: PopStateEvent) => void
): () => void {
	function onPopstate(event: PopStateEvent): void {
		const landed = landedEntry(event);
		countEntryMet(historyStorage, landed);
		const landing = land(ledger, landed);
		ledger = landing.ledger;
		standsOnTop = false;
		lastRouterIndex = routerIndexOf(event.state);
		dropLayers(landing.dropLayers);
		for (const target of landing.settled) settleStepBack(target);
		if (landing.stepOff) void stepBackTo(rankOf(landed) - 1);
		settleStillness();
		onLanding(landing, event);
	}
	window.addEventListener('popstate', onPopstate);
	keepLayerHistory(layerEntries);
	stepOffUnownedLayerEntry();
	return () => {
		window.removeEventListener('popstate', onPopstate);
		forgetLayerEntries();
	};
}

// A page load, as far as history goes: the state the page loaded onto is read
// again, the way this module's own load reads it.
export function loadHistoryPageForTests(): void {
	stateOnLoad = readStateOnLoad();
	standsOnTop = standsOnTopOnLoad();
}

export function resetHistoryControllerForTests(): void {
	historyStorage = tabStorage(() => sessionStorage);
	stateOnLoad = readStateOnLoad();
	ledger = EMPTY_LEDGER;
	standsOnTop = true;
	lastRouterIndex = routerIndexOf(history.state);
	stepBackWaiters.clear();
	stepBacksLandedWaiters = [];
	navigationsUnderway = 0;
	loadingMount = null;
	entryOfLayer.clear();
	layersAwaitingEntry = [];
}
