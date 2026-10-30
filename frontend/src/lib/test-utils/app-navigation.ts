import type { AfterNavigate, BeforeNavigate, NavigationTarget } from '$app/navigation';
import { flushSync, onMount } from 'svelte';
import { vi } from 'vitest';
import { routerHistoryEntry, routerHistoryEntryOf } from '#lib/test-utils/router-history-layout.ts';
import { stateProxy } from '../../tests/reactive-fixtures.svelte';

// A stand-in for SvelteKit's router, shared by every test that mocks it:
//   vi.mock('$app/navigation', async () =>
//     (await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation());
//   vi.mock('$app/state', async () =>
//     (await import('#lib/test-utils/app-navigation.ts')).fakeAppState());
// It writes history the way SvelteKit does: `goto` adds (or, with
// `replace`, rewrites) a router entry once its route has loaded -- at
// once, unless a test holds route loads -- and tells every mounted
// `afterNavigate` callback; a Back or Forward that navigates tells every
// mounted `beforeNavigate` callback first, and a `goto` one of them starts
// supersedes it before it loads anything; `pushState` and `replaceState` are
// shallow routing, which keeps the page state in the entry and the address of
// the page it was written over beside it. Like SvelteKit 3, whose shallow
// writes are async, they land a microtask after the call -- the history entry
// and the page state change then, not before -- unless a test holds them. Like
// SvelteKit, it keeps its place in history in memory and reads it back from an
// entry only when it starts or a Back or Forward lands. A landing is shallow
// only on an entry of the navigation the page shows, once something has
// navigated or pushed since the start, and only when the entry's page is the
// address landed on (or the landing only changes the hash); any other landing
// is a navigation to the page the entry was written over, while the router
// reports the landed address as its target. An address a test declares
// unmatched (`renderNoRouteAddresses`) shows the error page, and a write or
// `goto` to it rejects.
//
// It also owns every raw write into the test browser's history, which tests
// reach through library-history.ts. It imports no store: the stores import
// `$app/navigation`, so a fake that imported them back would wait on itself.

type HistoryWriteMode = 'push' | 'replace';

interface GotoOptions {
	replace?: boolean;
	state?: App.PageState;
}

const FAKE_ROUTE_ID = '/fake-route';
const unmatchedPathnames = new Set<string>();

function routeShownAt(url: URL): { id: string | null } {
	return { id: unmatchedPathnames.has(url.pathname) ? null : FAKE_ROUTE_ID };
}

function refuseUnmatched(url: string | URL): void {
	const { pathname } = new URL(url, location.href);
	if (unmatchedPathnames.has(pathname)) throw new Error(`No route matches ${pathname}`);
}

export function writeHistoryEntry(entry: unknown, url: string | URL, mode: HistoryWriteMode): void {
	if (mode === 'push') history.pushState(entry, '', url);
	else history.replaceState(entry, '', url);
}

// The page the fake router shows, as `$app/state` hands it out: a navigation
// moves its url, shallow routing only its state.
export const fakePage = stateProxy<{
	url: URL;
	state: App.PageState;
	route: { id: string | null };
}>({
	url: new URL(location.href),
	state: {},
	route: { id: FAKE_ROUTE_ID }
});

// The navigation under way, as `$app/state` hands it out: kit 3 sets it for
// every navigation but the router's start, and clears it right after the
// `afterNavigate` callbacks ran.
const fakeNavigating = stateProxy<{ to: NavigationTarget | null }>({ to: null });

// Declares the addresses no route matches: the page at one shows the error
// page (no route ID), and a `goto` or shallow write to one rejects.
export function renderNoRouteAddresses(...pathnames: string[]): void {
	unmatchedPathnames.clear();
	for (const pathname of pathnames) unmatchedPathnames.add(pathname);
	fakePage.route = routeShownAt(fakePage.url);
}

let currentHistoryIndex = 0;
let currentNavigationIndex = 0;
let hasNavigated = false;
// SvelteKit starts counting on an entry that carries no place of its own from
// the clock, past every place it handed out before in this tab; the fake
// counts on from the highest place it handed out instead.
let highestHistoryIndex = 0;

const afterNavigateCallbacks = new Set<(navigation: AfterNavigate) => void>();
const beforeNavigateCallbacks = new Set<(navigation: BeforeNavigate) => void>();
// Every `goto` starts a navigation that supersedes the one still loading, the
// way SvelteKit's navigation token does.
let navigationsStarted = 0;
// The route a `goto` loads before it writes its entry, while a test holds it;
// otherwise the route is there at once.
let heldRouteLoad: Promise<void> | null = null;
// The same for the shallow writes: held, none lands until a test releases them.
let heldShallowWrites: Promise<void> | null = null;
let releaseShallowWrites: () => void = () => undefined;

// Every navigation the fake router reported since it last started, in order,
// with the address of the page it navigated to.
export const reportedNavigations: { type: AfterNavigate['type']; pathname: string }[] = [];

function navigationTarget(url: URL): NavigationTarget {
	return { params: {}, route: { id: null }, url, scroll: null };
}

function reportNavigation(
	type: 'enter' | 'goto' | 'popstate',
	from: URL | null,
	to: URL = fakePage.url
): void {
	const navigation = {
		type,
		from: from && navigationTarget(from),
		to: navigationTarget(to),
		willUnload: false,
		complete: Promise.resolve()
	} as AfterNavigate;
	reportedNavigations.push({ type, pathname: to.pathname });
	for (const callback of afterNavigateCallbacks) callback(navigation);
	fakeNavigating.to = null;
}

// SvelteKit's single-page start: it takes its place from the entry the page
// loads onto (or starts counting), and writes its own entry over that one,
// keeping the place and dropping whatever state the entry carried.
export function startFakeRouter(): void {
	hasNavigated = false;
	unmatchedPathnames.clear();
	fakeNavigating.to = null;
	reportedNavigations.length = 0;
	const loaded = routerHistoryEntryOf(history.state);
	currentHistoryIndex = loaded?.historyIndex ?? highestHistoryIndex + 1;
	currentNavigationIndex = loaded?.navigationIndex ?? currentHistoryIndex;
	highestHistoryIndex = Math.max(highestHistoryIndex, currentHistoryIndex);
	writeHistoryEntry(
		routerHistoryEntry(
			{},
			{ historyIndex: currentHistoryIndex, navigationIndex: currentNavigationIndex }
		),
		location.href,
		'replace'
	);
	fakePage.url = new URL(location.href);
	fakePage.state = {};
	fakePage.route = routeShownAt(fakePage.url);
}

// The `enter` navigation SvelteKit reports once the page it started on is
// mounted.
export function reportFakeRouterEnter(): void {
	reportNavigation('enter', null);
}

function stepHistoryIndexUp(): void {
	currentHistoryIndex += 1;
	highestHistoryIndex = Math.max(highestHistoryIndex, currentHistoryIndex);
}

// Holds every route a `goto` loads until the returned function releases it.
// Meanwhile a navigation writes nothing: once its route has loaded, it writes
// its entry over whichever entry stands then, unless a newer one superseded it.
export function holdRouteLoads(): () => void {
	let release: () => void = () => undefined;
	heldRouteLoad = new Promise((resolve) => (release = resolve));
	return () => {
		heldRouteLoad = null;
		release();
	};
}

// Holds every shallow write until the returned function releases them, which
// then land in the order they were issued.
export function holdShallowWrites(): () => Promise<void> {
	heldShallowWrites = new Promise((resolve) => (releaseShallowWrites = resolve));
	return releaseHeldShallowWrites;
}

// Releases the held writes and waits until every one of them has landed.
async function releaseHeldShallowWrites(): Promise<void> {
	heldShallowWrites = null;
	releaseShallowWrites();
	await laterTask();
}

// A later task, where a person's Back or Forward starts.
export function laterTask(): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve));
}

// A write the controller issued, once the router has landed it: the browser's
// own entry and address answer for it from then on.
export async function landed<T>(write: T): Promise<T> {
	await laterTask();
	return write;
}

async function fakeGoto(url: string | URL, options: GotoOptions = {}): Promise<void> {
	refuseUnmatched(url);
	navigationsStarted += 1;
	fakeNavigating.to = navigationTarget(new URL(url, location.href));
	const navigation = navigationsStarted;
	if (heldRouteLoad !== null) {
		await heldRouteLoad;
		if (navigation !== navigationsStarted) return;
	}
	if (!options.replace) {
		stepHistoryIndexUp();
		currentNavigationIndex += 1;
	}
	const state = options.state ?? {};
	writeHistoryEntry(
		routerHistoryEntry(state, {
			historyIndex: currentHistoryIndex,
			navigationIndex: currentNavigationIndex
		}),
		url,
		options.replace ? 'replace' : 'push'
	);
	const from = fakePage.url;
	fakePage.url = new URL(location.href);
	fakePage.state = state;
	fakePage.route = routeShownAt(fakePage.url);
	hasNavigated = true;
	reportNavigation('goto', from);
}

async function writeShallowEntry(
	url: string | URL,
	state: App.PageState,
	mode: HistoryWriteMode
): Promise<void> {
	await heldShallowWrites;
	refuseUnmatched(url);
	if (mode === 'push') {
		stepHistoryIndexUp();
		hasNavigated = true;
	}
	writeHistoryEntry(
		routerHistoryEntry(state, {
			historyIndex: currentHistoryIndex,
			navigationIndex: currentNavigationIndex,
			pageUrl: fakePage.url.href
		}),
		url,
		mode
	);
	fakePage.state = state;
}

function withoutHash(url: URL | Location): string {
	return url.href.split('#')[0];
}

// A Back or Forward: onto an entry of the navigation the page shows, written
// over the address it lands on, only the page state and address follow; onto
// any other entry -- another navigation's, one before anything has navigated
// since the start, or one written over another address -- the router
// navigates to the page that entry was written over, and reports the address
// it landed on as the target.
//
// A browser drains its microtasks between the listeners of a real popstate,
// so Svelte runs the effects that read the page this listener moved before
// the app's own popstate listener hears the step; flushing here keeps that
// order, which jsdom's single call stack would otherwise hide.
function followTraversal(event: PopStateEvent): void {
	moveWithTraversal(event);
	flushSync();
}

function moveWithTraversal(event: PopStateEvent): void {
	const landing = routerHistoryEntryOf(event.state);
	const historyIndex = landing?.historyIndex;
	if (landing === null || historyIndex === undefined) {
		fakePage.url = new URL(location.href);
		return;
	}
	const from = fakePage.url;
	const landedAddress = new URL(location.href);
	const entryPage = new URL(landing.pageUrl ?? location.href);
	const landedState = (landing.pageState ?? {}) as App.PageState;
	const navigationIndex = landing.navigationIndex;
	const hashChanges =
		(location.href + from.href).includes('#') && withoutHash(location) === withoutHash(from);
	const shallow =
		navigationIndex === currentNavigationIndex &&
		((hasNavigated && entryPage.href === landedAddress.href) || hashChanges);
	currentHistoryIndex = historyIndex;
	if (shallow || navigationIndex === undefined) {
		fakePage.url = entryPage;
		fakePage.state = landedState;
		return;
	}
	currentNavigationIndex = navigationIndex;
	hasNavigated = true;
	if (supersededBeforeLoading(from, landedAddress)) return;
	fakePage.url = entryPage;
	fakePage.state = landedState;
	fakePage.route = routeShownAt(entryPage);
	reportNavigation('popstate', from, landedAddress);
}

function supersededBeforeLoading(from: URL, to: URL): boolean {
	const started = navigationsStarted;
	const navigation = {
		type: 'popstate',
		from: navigationTarget(from),
		to: navigationTarget(to),
		willUnload: false,
		cancel: () => undefined,
		complete: Promise.resolve()
	} as BeforeNavigate;
	for (const callback of beforeNavigateCallbacks) callback(navigation);
	return navigationsStarted !== started;
}

window.addEventListener('popstate', followTraversal);

function fakeAfterNavigate(callback: (navigation: AfterNavigate) => void): void {
	onMount(() => {
		afterNavigateCallbacks.add(callback);
		return () => afterNavigateCallbacks.delete(callback);
	});
}

// What the app layout's `beforeNavigate` hears, for a test that mounts no
// layout; the returned function stops it.
export function followBeforeNavigate(callback: (navigation: BeforeNavigate) => void): () => void {
	beforeNavigateCallbacks.add(callback);
	return () => beforeNavigateCallbacks.delete(callback);
}

function fakeBeforeNavigate(callback: (navigation: BeforeNavigate) => void): void {
	onMount(() => followBeforeNavigate(callback));
}

export function fakeAppNavigation() {
	return {
		goto: vi.fn(fakeGoto),
		pushState: vi.fn((url: string | URL, state: App.PageState) =>
			writeShallowEntry(url, state, 'push')
		),
		replaceState: vi.fn((url: string | URL, state: App.PageState) =>
			writeShallowEntry(url, state, 'replace')
		),
		afterNavigate: vi.fn(fakeAfterNavigate),
		beforeNavigate: vi.fn(fakeBeforeNavigate)
	};
}

export function fakeAppState() {
	return { page: fakePage, navigating: fakeNavigating };
}
