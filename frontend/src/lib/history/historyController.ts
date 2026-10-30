import type { BeforeNavigate, NavigationType } from '@sveltejs/kit';
import { untrack } from 'svelte';
import { goto, pushState, replaceState } from '$app/navigation';
import { page } from '$app/state';
import { browserDocumentLoads, documentAddress, type DocumentLoads } from './documentLoads';
import { tabStorage, type TabStorage } from './tabStorage';
import { pageStateOfHistoryState, routerIndexOf } from '#lib/history/routerHistoryState.ts';
import {
	dropLayersFrom,
	keepLayerHistory,
	stackedLayers,
	type Layer,
	type LayerHistory
} from '#lib/stores/layers.ts';

// The one owner of the tab's history (issue #1006, ruling of 01.10.2026): only
// this module writes or traverses history. Every entry it writes carries an
// id, so a landing -- a Back, a Forward, a jump of several entries, or one of
// the controller's own step-backs -- says by itself where history now stands,
// and which open layers and pending step-backs it has left behind. Installed
// once by the root layout, on every page, it gives every layer opened on the
// stack (stores/layers.ts) one entry on top of the page it covers, so Back
// closes the topmost overlay before it leaves the page.

// What the controller stamps into an entry's page state. `layer` marks an entry
// an open layer pushed over the page it covers; `below` is the address of the
// page a pushed page entry stands over, so a page's own Back can name where it
// goes (#1389).
export interface HistoryEntry {
	readonly id: number;
	readonly layer?: string;
	readonly below?: string;
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
	readonly apply: boolean;
	readonly ledger: HistoryLedger;
}

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
	const apply = !onLayerEntry && !isSameEntry(landed, ledger.current);
	return {
		dropLayers: ledger.layers.filter((open) => open.entry > rank).reverse(),
		settled: ledger.stepBacks.filter((target) => target >= rank),
		apply,
		ledger: {
			layers,
			stepBacks: ledger.stepBacks.filter((target) => target < rank),
			current: onLayerEntry ? ledger.current : landed
		}
	};
}

// A layer entry no open layer owns -- one a reload or a Forward came back
// onto -- is a copy of the page below it, where Back would do nothing.
function isUnownedLayerEntry(ledger: HistoryLedger, entry: HistoryEntry | null): boolean {
	return entry?.layer !== undefined && !ledger.layers.some((open) => open.entry === entry.id);
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

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function isHistoryEntry(value: unknown): value is HistoryEntry {
	return (
		isRecord(value) &&
		Number.isSafeInteger(value.id) &&
		(value.id as number) > 0 &&
		(value.layer === undefined || typeof value.layer === 'string') &&
		(value.below === undefined || typeof value.below === 'string')
	);
}

function entryOfHistoryState(state: unknown): HistoryEntry | null {
	const entry = pageStateOfHistoryState(state)?.entry;
	return isHistoryEntry(entry) ? entry : null;
}

export const standingHistoryState = (): unknown => history.state;

// The entry history stands on, as the controller stamped it.
const standingEntry = (): HistoryEntry | null => entryOfHistoryState(standingHistoryState());

// The page entry history stands on: the standing entry, or under an open
// layer's entry the page that layer covers. An entry without an id has none.
function standingPageEntry(standing: HistoryEntry | null): HistoryEntry | null {
	return standing?.layer === undefined ? standing : ledger.current;
}

export function standingPageEntryId(): number | null {
	return standingPageEntry(standingEntry())?.id ?? null;
}

// The library starts showing the page entry history stands on, so that entry
// is the page the screen shows from now on, whichever of the library's paths
// showed it -- a landing on it is no news, and one elsewhere it did not hear
// is (`attachLandingHandler`). Answers that entry's id.
export function showStandingPage(): number | null {
	settleOnPage(standingEntry());
	return standingPageEntryId();
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
// Where history stood when the controller last looked: the router's place,
// which tells a router push from a router replace, and the address, which is
// the page a router push stands over.
let lastRouterIndex = routerIndexOf(history.state);
let lastAddress = location.href;
const stepBackWaiters = new Map<number, (() => void)[]>();
let stillnessWaiters: (() => void)[] = [];
let navigationsUnderway = 0;
let loadingMount: RouteMount | null = null;
let addressMountedUnderKeptPage: string | null = null;
const entryOfLayer = new Map<Layer, number>();
let layersAwaitingEntry: Layer[] = [];
let routerStarting = false;

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

function newPageEntryOver(below: string): HistoryEntry {
	return { ...newEntry(), below };
}

function lookAtStandingEntry(state: unknown = history.state): void {
	lastRouterIndex = routerIndexOf(state);
	lastAddress = location.href;
}

// The id an id-less entry on top gets. The tab's only entry is its first one,
// below which nothing is left to step back to; so is every entry the app is
// entered on from another site or a typed address, below which that site's
// pages or the tab's older visits stand -- not the page the person just left.
// An entry the app is entered on from one of its own pages, by a load of a
// fresh document, stands over that page, so a page's own Back steps back onto
// it and can name it (#1389).
function firstIdOnTop(entering: boolean): HistoryEntry | null {
	if (!standsOnTop) return null;
	const pageLeft = entering && history.length > 1 ? appPageEnteredFrom() : null;
	if (pageLeft !== null) return newPageEntryOver(pageLeft);
	const entry = newEntry();
	if (history.length === 1 || entering) historyStorage.setItem(FIRST_ENTRY_KEY, String(entry.id));
	return entry;
}

// The server sends `strict-origin-when-cross-origin`, so a page of the app's
// own origin names itself, by its whole address, as the referrer, and another
// site or a typed address leaves either a foreign origin or nothing.
function appPageEnteredFrom(): string | null {
	const referrer = document.referrer;
	if (referrer === '' || new URL(referrer).origin !== location.origin) return null;
	return referrer;
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

// A push allocates an id; a page entry remembers the page it stands over, and
// an entry pushed for a layer belongs to that layer until a landing leaves it.
export function pushEntry(url: string, state: App.PageState, layer?: string): HistoryEntry {
	const entry = layer === undefined ? newPageEntryOver(location.href) : newEntry(layer);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	pushState(url, stampedPageState(state, entry));
	lookAtStandingEntry();
	if (layer === undefined) {
		pushedPage(entry);
		return entry;
	}
	standsOnTop = true;
	ledger = { ...ledger, layers: [...ledger.layers, { layer, entry: entry.id }] };
	return entry;
}

// A replace rewrites what an entry shows, never which entry it is: it keeps
// the id, the layer mark and the page it stands over. An id-less entry gets
// its first id here while it is the top entry, and stays foreign below it.
export function replaceEntry(url: string, state: App.PageState): HistoryEntry | null {
	const entry = entryOfHistoryState(history.state) ?? firstIdOnTop(false);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	replaceState(url, stampedPageState(state, entry));
	lookAtStandingEntry();
	settleOnPage(entry);
	return entry;
}

interface NavigateOptions {
	readonly replaceState: boolean;
	readonly noScroll: boolean;
	readonly keepFocus: boolean;
	readonly state: App.PageState;
}

// A navigation that mounts the route of the address history already stands
// on, while it loads.
interface RouteMount {
	readonly address: string;
	readonly options: NavigateOptions;
}

// A navigation through the router carries its entry the way a shallow write
// does: a push a fresh id over the page it leaves, a replace the entry it
// writes over.
// While it loads, history is not still: the router writes its entry only
// once the route has loaded, over whatever entry stands then. A replace to
// the address history already stands on moves nothing: it mounts the route of
// the entry standing there, and history stays still meanwhile.
export async function navigateTo(url: string, options: NavigateOptions): Promise<void> {
	const entry = options.replaceState
		? (entryOfHistoryState(history.state) ?? firstIdOnTop(false))
		: newPageEntryOver(location.href);
	const mount =
		options.replaceState && standsOnAddress(url) ? { address: location.href, options } : null;
	keepTrackOfKeptPage(url);
	if (mount === null) navigationsUnderway += 1;
	else loadingMount = mount;
	try {
		await startNavigation(url, {
			replaceState: options.replaceState,
			noScroll: options.noScroll,
			keepFocus: options.keepFocus,
			state: stampedPageState(options.state, entry)
		});
		if (entry !== null && standingEntry()?.id === entry.id) navigatedOnto(entry, options);
	} finally {
		if (mount === null) navigationsUnderway -= 1;
		else if (loadingMount === mount) loadingMount = null;
		settleStillness();
	}
}

// A navigation to the address the router's page names keeps that page, so a
// route it mounts there stands under the params of the route before
// (`mountAddressOver`) until the router reports a navigation to another
// address (`stampNavigatedEntry`).
function keepTrackOfKeptPage(url: string): void {
	const target = new URL(url, location.href).href;
	if (target === untrack(() => page.url.href)) addressMountedUnderKeptPage = target;
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
//
// The router keeps the page it shows -- its route and its params -- when it
// navigates to the address that page already names, whatever route it mounts
// there. A Back it routes shallowly moves that page's address on without
// mounting anything (see `mountRouteOfLandedAddress`), so the route mounted
// over the address afterwards stands under the params of the page before --
// none for Settings -- until the router navigates to another address: its
// params name no page of the address, and resolving them would write the page
// they do name over the entry (issue #1006, H5).
type RouteOnAddress = 'stands' | 'remounts' | 'stands-under-kept-page';

export function mountAddressOver(routeUrl: string): RouteOnAddress {
	if (new URL(routeUrl, location.href).pathname !== location.pathname) {
		mountStandingAddress();
		return 'remounts';
	}
	return addressMountedUnderKeptPage === location.href ? 'stands-under-kept-page' : 'stands';
}

function mountStandingAddress(): void {
	const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
	void navigateTo(location.href, {
		replaceState: true,
		noScroll: true,
		keepFocus: true,
		state: pageState
	});
}

// Every navigation started since the page loaded: each one the controller
// issues, the moment it issues it, and each one the router reports. The router
// reports a navigation in `beforeNavigate` only once it has resolved its
// route, and not at all while an aborted one still counts as loading, so a
// navigation that aborts another is known to have started only here.
let navigationsStarted = 0;

function startNavigation(...navigation: Parameters<typeof goto>): Promise<void> {
	navigationsStarted += 1;
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	return goto(...navigation);
}

// A Back or Forward that navigates mounts the address it lands on before the
// router loads anything of the page under it. Every other navigation's target
// is an address history has yet to move to.
//
// The router mounts a route only once a navigation completes, and a Back
// pressed while one loads aborts it. A Back onto an entry of the navigation
// the router was heading to -- the first of two quick Backs from Settings
// lands on the album, the second on the wall shallow routing wrote it over --
// is shallow routing to the router: it starts no navigation of its own, and
// the page before stays on screen under the address (issue #1006, H5). Unless
// a navigation started after it, the route of the address history stands on
// is mounted then: a navigation started later is the one that aborted it, and
// a mount issued over that one would abort it in turn (#1340). The mount the
// landing issues over its own address belongs to its start, not to a later
// navigation: the next Back of the same task aborts that mount as well, and
// then nothing else is left to mount the address it lands on (#1340, the
// song's entry written over the album's page, two Backs from Settings).
// That mount itself aborts the router's Back navigation -- the router takes
// it as its current navigation at once and reports nothing of it while the
// Back still counts as loading -- so a landing that remounts mounts its
// address a second time. That is harmless: both mounts target the one address
// history stands on, and the second only supersedes the first (#1006).
export function mountRouteOfLandedAddress(
	navigation: Pick<BeforeNavigate, 'type' | 'to' | 'complete'>
): void {
	navigationsStarted += 1;
	if (navigation.type === 'popstate' && navigation.to !== null) {
		mountAddressOver(navigation.to.url.href);
	}
	const startedAs = navigationsStarted;
	navigation.complete.catch(() => {
		if (navigationsStarted === startedAs) mountStandingAddress();
	});
}

// A shallow write while a route mounts issues the mount again over the entry
// it wrote: the router writes over whichever entry stands once the route has
// loaded, so the older mount would land on that entry with the page state it
// started with, and the entry would lose its own.
export function remountOverStandingEntry(url: string, state: App.PageState): Promise<void> {
	if (loadingMount === null) return Promise.resolve();
	return navigateTo(url, { ...loadingMount.options, state });
}

// A navigation another one superseded wrote no entry of its own, so only one
// whose entry stands settles the page.
function navigatedOnto(entry: HistoryEntry, options: NavigateOptions): void {
	lookAtStandingEntry();
	if (options.replaceState) settleOnPage(entry);
	else pushedPage(entry);
}

// Every navigation the router reports once it has written its entry: a link
// or a `goto` from anywhere, or -- on `enter` -- its start over the entry the
// page loaded onto. An entry the navigation carried stands as it is, one the
// start dropped gets back the id it was loaded with, a router push a fresh id
// over the page it left, and any other a first id on top. The start drops the
// layer mark and the page below too, so only once it has the mark back can the
// installed controller step off a layer entry a reload came back onto
// (`followRouterStart`). A Back or Forward is the landing listener's.
export function stampNavigatedEntry(type: NavigationType): void {
	if (location.href !== addressMountedUnderKeptPage) addressMountedUnderKeptPage = null;
	if (type === 'popstate') {
		lookAtStandingEntry();
		return;
	}
	if (type === 'enter') followRouterStart();
	const pushedOver = pageARouterPushStandsOver();
	lookAtStandingEntry();
	const entry = entryTheNavigationCarried() ?? stampEntryTheNavigationDropped(type, pushedOver);
	if (pushedOver !== null && entry !== null) pushedPage(entry);
	else settleOnPage(entry);
}

// An entry the navigation carried keeps its id; the newest id stands on top.
function entryTheNavigationCarried(): HistoryEntry | null {
	const carried = entryOfHistoryState(history.state);
	if (carried?.id === lastAllocatedEntryId(historyStorage)) standsOnTop = true;
	return carried;
}

// An entry the navigation wrote without one gets back the id it was loaded
// with on the router's start, a fresh id over the page a router push left,
// or a first id on top.
function stampEntryTheNavigationDropped(
	type: NavigationType,
	pushedOver: string | null
): HistoryEntry | null {
	const loaded = type === 'enter' ? entryOfHistoryState(stateOnLoad) : null;
	const entry =
		loaded ?? (pushedOver === null ? firstIdOnTop(type === 'enter') : newPageEntryOver(pushedOver));
	if (entry !== null) {
		const pageState = (pageStateOfHistoryState(history.state) ?? {}) as App.PageState;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- the address the router has just written
		replaceState(location.href, stampedPageState(pageState, entry));
	}
	return entry;
}

// A router push -- a link, or a `goto` from anywhere -- stands one place above
// the entry the controller last saw, a replace on that same place. Answers the
// address of the page a push stands over, null for a replace.
function pageARouterPushStandsOver(): string | null {
	const index = routerIndexOf(history.state);
	const pushed =
		index !== undefined && lastRouterIndex !== undefined && index === lastRouterIndex + 1;
	return pushed ? lastAddress : null;
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

// The address of the page a page's own Back steps back onto: the page the
// page history stands on was pushed over, while that page is an entry of the
// tab's own. Null where there is none -- on the tab's first entry, on an entry
// without an id, which is never the tab's own, or on one that does not know
// what it was pushed over -- and there that Back goes elsewhere (#1389).
export function pageBelowStandingPage(): string | null {
	const standing = standingEntry();
	if (standing === null || standing.id <= firstEntryOfTab()) return null;
	return standingPageEntry(standing)?.below ?? null;
}

// A page's own Back control: one step back onto the page below while there is
// one; otherwise `openList` writes the page's list over the page, never
// pushing it, so the browser's Back from there does not return to the page.
export function stepBackOr(openList: () => Promise<void>): Promise<void> {
	if (pageBelowStandingPage() === null) return openList();
	return stepBackOffStandingEntry();
}

// The same Back for a page whose list is a plain route, written over it.
export function stepBackOrGoTo(fallback: string): Promise<void> {
	return stepBackOr(() => startNavigation(fallback, { replaceState: true }));
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

function ownStepBacksUnderway(): boolean {
	return ledger.stepBacks.length > 0;
}
export { ownStepBacksUnderway as ownStepBacksUnderwayForTests };

// History moves while one of the controller's own step-backs is underway or a
// navigation is loading the route it writes its entry for: an entry written
// meanwhile would land under the step's landing, or be superseded along with
// the navigation's own entry.
export function historyMoves(): boolean {
	return ownStepBacksUnderway() || navigationsUnderway > 0 || routerStarting;
}

// Resolves once history stands still, so a write issued while it moves stands
// on the entry the move lands on.
export function historyStandsStill(): Promise<void> {
	if (!historyMoves()) return Promise.resolve();
	return new Promise((resolve) => stillnessWaiters.push(resolve));
}

// Resolves once history has come to rest: a write released when history
// stands still may navigate and move it again, so the wait starts over until
// nothing is left to land.
export function historyComesToRest(): Promise<void> {
	if (!historyMoves()) return Promise.resolve();
	return historyStandsStill().then(historyComesToRest);
}

// Once history stands still the layers held meanwhile get their entries
// first, then the held writes are written over the entry that then stands:
// each waiter resolves a promise whose callback runs only after this
// function has pushed the layers.
function settleStillness(): void {
	if (historyMoves()) return;
	const still = stillnessWaiters;
	stillnessWaiters = [];
	for (const resolve of still) resolve();
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
		if (historyMoves()) {
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
	const depth = stackedLayers().findIndex((layer) =>
		left.has(entryOfLayer.get(layer) ?? Number.NaN)
	);
	for (const [layer, entry] of entryOfLayer) if (left.has(entry)) entryOfLayer.delete(layer);
	if (depth !== -1) dropLayersFrom(depth);
}

// A step back off the entry already underway is not started again.
function stepOffUnownedLayerEntry(entry: HistoryEntry | null): void {
	if (entry === null || !isUnownedLayerEntry(ledger, entry)) return;
	if (ledger.stepBacks.includes(entry.id - 1)) return;
	void stepBackTo(entry.id - 1);
}

// The controller stops owning the open layers' entries -- as a reload leaves
// it -- and settles every step-back still waiting for a landing that,
// uninstalled, it no longer hears.
function releaseLayerEntries(): void {
	entryOfLayer.clear();
	layersAwaitingEntry = [];
	ledger = { ...ledger, layers: [], stepBacks: [] };
	for (const target of Array.from(stepBackWaiters.keys())) {
		while (stepBackWaiters.has(target)) settleStepBack(target);
	}
	settleStillness();
}
export { releaseLayerEntries as releaseLayerEntriesForTests };

// Leaving the app's state behind -- a sign-out the server confirmed, a session
// the server no longer holds -- loads a fresh document rather than routing
// inside this one, so nothing the signed-in page held survives in memory
// (#1340, ruling A of 14.10.2026). The load waits until history has come to
// rest, so it leaves from the entry a navigation already under way lands on.
// Over a layer's entry it replaces that entry (a form POST is pushed instead):
// Back finds no copy of the page to step off again, and nothing steps back
// meanwhile (#1230). Over a page entry it is pushed, keeping the page, so Back
// loads it afresh and asks for the session again. With two or more layers
// open, the lower layers' entries stay (accepted residual of the ruling). A
// page leaves once: the leave counts from its first call, so a second refusal
// arriving meanwhile -- two library requests refused together -- loads nothing
// more, where each further load would abort the one before it.
let documentLoads: DocumentLoads = browserDocumentLoads;
let leftForFreshDocument = false;

function standsOnLayerEntry(): boolean {
	return standingEntry()?.layer !== undefined;
}

// Whether this page is on its way to a fresh document: the server holds no
// session for it any more, so nothing it sends on the way out is answered.
export function leavesForFreshDocument(): boolean {
	return leftForFreshDocument;
}

async function leaveOnce(load: () => void): Promise<void> {
	if (leftForFreshDocument) return;
	leftForFreshDocument = true;
	await historyComesToRest();
	load();
}

export function loadAfresh(url: string): Promise<void> {
	return leaveOnce(() => {
		const address = documentAddress(url);
		if (standsOnLayerEntry()) documentLoads.replace(address);
		else documentLoads.assign(address);
	});
}

// The address history stands on, loaded afresh. Over a page entry this is a
// reload: the entry keeps the id the controller stamped into it, and a reload
// loads the document whatever `#` part the address has.
export function reloadAfresh(): Promise<void> {
	return leaveOnce(() => {
		if (standsOnLayerEntry()) documentLoads.replace(documentAddress(location.href));
		else documentLoads.reload();
	});
}

// A form POST cannot replace an entry, so it is pushed over the standing one,
// a page's or a layer's; Back then reaches the entry it left, which a restore
// from the cache loads afresh and a plain load asks the server about.
export function leaveByPostingForm(action: string): Promise<void> {
	return leaveOnce(() => documentLoads.submitPost(action));
}

// A browser that kept the page left for a fresh document in its back-forward
// cache shows it again, with the signed-in state in memory, on Back; it is
// loaded afresh instead.
function loadAfreshWhenRestored(event: PageTransitionEvent): void {
	if (event.persisted && leftForFreshDocument) documentLoads.reload();
}

type LandingHandler = (landing: Landing, landedState: unknown) => void;

let landingHandler: LandingHandler | null = null;
let uninstall: (() => void) | null = null;

// Nobody handles landings between two pages of the library -- back from
// Settings, the library attaches only once its page has loaded -- so a Back
// pressed meanwhile lands unheard: the second of two quick Backs from
// Settings stands on the wall while the screen still shows the album the
// first one reached (issue #1006, H5). A page entry history stands on that is
// not the page the screen shows is heard as the landing it was once a handler
// attaches. Before the controller has seen any page there is nothing to tell
// it from.
function hearLandingMissedWhileDetached(onLanding: LandingHandler): void {
	const standing = standingEntry();
	if (standing === null || standing.layer !== undefined || ledger.current === null) return;
	if (isSameEntry(standing, ledger.current)) return;
	const landing = land(ledger, standing);
	ledger = landing.ledger;
	onLanding(landing, history.state);
}

// Every landing closes the layers it left, settles the step-backs it reached
// and, on a layer entry no open layer owns, starts stepping off it. Only an
// attached handler moves the page the screen shows: without one, that page
// stays where the last navigation put it, so the handler attaching next still
// hears the landing it missed.
function onPopstate(event: PopStateEvent): void {
	const landed = landedEntry(event);
	countEntryMet(historyStorage, landed);
	const landing = land(ledger, landed);
	ledger =
		landingHandler === null ? { ...landing.ledger, current: ledger.current } : landing.ledger;
	standsOnTop = false;
	lookAtStandingEntry(event.state);
	dropLayers(landing.dropLayers);
	for (const target of landing.settled) settleStepBack(target);
	stepOffUnownedLayerEntry(landed);
	settleStillness();
	landingHandler?.(landing, event.state);
}

// The router starts listening for popstate only once the page it started on
// is mounted, after the root layout has installed the controller. The
// controller's part of a landing must follow the router's: a write it releases
// while the router still holds the entry before would carry the router's old
// place, and the router's own handling would abort a navigation it released.
// So once the start has run to its end the controller listens again, behind
// the router, and only then steps off a layer entry a reload came back onto;
// history moves until then. A controller not installed has no part to follow.
function followRouterStart(): void {
	if (uninstall === null) return;
	routerStarting = true;
	setTimeout(() => {
		routerStarting = false;
		if (uninstall !== null) {
			window.removeEventListener('popstate', onPopstate);
			window.addEventListener('popstate', onPopstate);
			stepOffUnownedLayerEntry(standingEntry());
		}
		settleStillness();
	});
}

// The root layout installs the controller once for the whole app: from then
// on every landing is heard and every layer opened owns an entry. The
// returned function uninstalls it.
export function installHistoryController(): () => void {
	if (uninstall !== null) throw new Error('The history controller is already installed');
	window.addEventListener('popstate', onPopstate);
	window.addEventListener('pageshow', loadAfreshWhenRestored);
	keepLayerHistory(layerEntries);
	stepOffUnownedLayerEntry(standingEntry());
	const uninstallThis = (): void => {
		window.removeEventListener('popstate', onPopstate);
		window.removeEventListener('pageshow', loadAfreshWhenRestored);
		keepLayerHistory(null);
		releaseLayerEntries();
		uninstall = null;
	};
	uninstall = uninstallThis;
	return uninstallThis;
}

// The library attaches the one landing handler while its page shows: it hears
// each landing after the controller's own part, and on attach the landing it
// missed while detached. The returned function detaches it.
export function attachLandingHandler(onLanding: LandingHandler): () => void {
	if (landingHandler !== null) throw new Error('A landing handler is already attached');
	landingHandler = onLanding;
	hearLandingMissedWhileDetached(onLanding);
	return () => {
		if (landingHandler === onLanding) landingHandler = null;
	};
}

// A page load, as far as history goes: the state the page loaded onto, and
// where history stands, are read again, the way this module's own load reads
// them -- so the router's start over that entry is not taken for a push.
export function loadHistoryPageForTests(): void {
	stateOnLoad = readStateOnLoad();
	standsOnTop = standsOnTopOnLoad();
	lookAtStandingEntry();
}

export function resetHistoryControllerForTests(): void {
	uninstall?.();
	landingHandler = null;
	historyStorage = tabStorage(() => sessionStorage);
	stateOnLoad = readStateOnLoad();
	ledger = EMPTY_LEDGER;
	standsOnTop = true;
	lookAtStandingEntry();
	stepBackWaiters.clear();
	stillnessWaiters = [];
	navigationsUnderway = 0;
	routerStarting = false;
	loadingMount = null;
	addressMountedUnderKeptPage = null;
	navigationsStarted = 0;
	entryOfLayer.clear();
	layersAwaitingEntry = [];
	documentLoads = browserDocumentLoads;
	leftForFreshDocument = false;
}

export function standInForDocumentLoadsForTests(standIn: DocumentLoads): void {
	documentLoads = standIn;
}
