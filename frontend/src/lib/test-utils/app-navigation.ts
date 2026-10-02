import type { AfterNavigate, BeforeNavigate, NavigationTarget } from '@sveltejs/kit';
import { flushSync, onMount } from 'svelte';
import { vi } from 'vitest';
import { stateProxy } from '../../tests/reactive-fixtures.svelte';

// A stand-in for SvelteKit's router, shared by every test that mocks it:
//   vi.mock('$app/navigation', async () =>
//     (await import('$lib/test-utils/app-navigation')).fakeAppNavigation());
//   vi.mock('$app/state', async () =>
//     (await import('$lib/test-utils/app-navigation')).fakeAppState());
// It writes history the way SvelteKit does: `goto` adds (or, with
// `replaceState`, rewrites) a router entry and tells every mounted
// `afterNavigate` callback; a Back or Forward that navigates tells every
// mounted `beforeNavigate` callback first, and a `goto` one of them starts
// supersedes it before it loads anything; `pushState` and `replaceState` are
// shallow routing, which keeps the page state under the entry's states key and
// the address of the page it was written over beside it. Like SvelteKit, it keeps
// its place in history in memory and reads it back from an entry only when it
// starts or a Back or Forward lands, and a landing on the entry of another
// navigation is a navigation of its own -- and so is a landing on an entry of
// the same navigation while nothing has navigated or pushed since the start,
// unless it only changes the hash: after a reload the router cannot tell that
// entry's page from the one it started on.
//
// It also owns every raw write into the test browser's history, which tests
// reach through library-history.ts. It imports no store: the stores import
// `$app/navigation`, so a fake that imported them back would wait on itself.
const ROUTER_HISTORY_INDEX = 'sveltekit:history';
const ROUTER_NAVIGATION_INDEX = 'sveltekit:navigation';
const ROUTER_PAGE_URL = 'sveltekit:pageurl';
const ROUTER_STATES = 'sveltekit:states';

type HistoryWriteMode = 'push' | 'replace';
type RouterEntry = Record<string, unknown>;

interface GotoOptions {
	replaceState?: boolean;
	state?: App.PageState;
}

export function writeHistoryEntry(entry: unknown, url: string | URL, mode: HistoryWriteMode): void {
	if (mode === 'push') history.pushState(entry, '', url);
	else history.replaceState(entry, '', url);
}

// The page the fake router shows, as `$app/state` hands it out: a navigation
// moves its url, shallow routing only its state.
export const fakePage = stateProxy<{ url: URL; state: App.PageState }>({
	url: new URL(location.href),
	state: {}
});

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

// Every navigation the fake router reported since it last started, in order,
// with the address of the page it navigated to.
export const reportedNavigations: { type: AfterNavigate['type']; pathname: string }[] = [];

function routerEntry(entry: unknown): RouterEntry | null {
	return typeof entry === 'object' && entry !== null ? (entry as RouterEntry) : null;
}

function routerIndex(entry: RouterEntry | null, key: string): number | undefined {
	const index = entry?.[key];
	return typeof index === 'number' ? index : undefined;
}

function navigationTarget(url: URL): NavigationTarget {
	return { params: {}, route: { id: null }, url, scroll: null };
}

function reportNavigation(type: 'enter' | 'goto' | 'popstate', from: URL | null): void {
	const navigation = {
		type,
		from: from && navigationTarget(from),
		to: navigationTarget(fakePage.url),
		willUnload: false,
		complete: Promise.resolve()
	} as AfterNavigate;
	reportedNavigations.push({ type, pathname: fakePage.url.pathname });
	for (const callback of afterNavigateCallbacks) callback(navigation);
}

// SvelteKit's single-page start: it takes its place from the entry the page
// loads onto (or starts counting), and writes its own entry over that one,
// keeping the place and dropping whatever state the entry carried.
export function startFakeRouter(): void {
	hasNavigated = false;
	reportedNavigations.length = 0;
	const loaded = routerEntry(history.state);
	currentHistoryIndex = routerIndex(loaded, ROUTER_HISTORY_INDEX) ?? highestHistoryIndex + 1;
	currentNavigationIndex = routerIndex(loaded, ROUTER_NAVIGATION_INDEX) ?? currentHistoryIndex;
	highestHistoryIndex = Math.max(highestHistoryIndex, currentHistoryIndex);
	writeHistoryEntry(
		{
			[ROUTER_HISTORY_INDEX]: currentHistoryIndex,
			[ROUTER_NAVIGATION_INDEX]: currentNavigationIndex,
			[ROUTER_STATES]: {}
		},
		location.href,
		'replace'
	);
	fakePage.url = new URL(location.href);
	fakePage.state = {};
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

async function fakeGoto(url: string | URL, options: GotoOptions = {}): Promise<void> {
	navigationsStarted += 1;
	if (!options.replaceState) {
		stepHistoryIndexUp();
		currentNavigationIndex += 1;
	}
	const state = options.state ?? {};
	writeHistoryEntry(
		{
			[ROUTER_HISTORY_INDEX]: currentHistoryIndex,
			[ROUTER_NAVIGATION_INDEX]: currentNavigationIndex,
			[ROUTER_STATES]: state
		},
		url,
		options.replaceState ? 'replace' : 'push'
	);
	const from = fakePage.url;
	fakePage.url = new URL(location.href);
	fakePage.state = state;
	hasNavigated = true;
	reportNavigation('goto', from);
}

function writeShallowEntry(url: string | URL, state: App.PageState, mode: HistoryWriteMode): void {
	if (mode === 'push') {
		stepHistoryIndexUp();
		hasNavigated = true;
	}
	writeHistoryEntry(
		{
			[ROUTER_HISTORY_INDEX]: currentHistoryIndex,
			[ROUTER_NAVIGATION_INDEX]: currentNavigationIndex,
			[ROUTER_PAGE_URL]: fakePage.url.href,
			[ROUTER_STATES]: state
		},
		url,
		mode
	);
	fakePage.state = state;
}

function withoutHash(url: URL | Location): string {
	return url.href.split('#')[0];
}

// A Back or Forward: onto an entry of the navigation the page shows, only the
// page state and address follow; onto another navigation's entry -- or onto
// any entry before anything has navigated since the start, see above -- the
// router navigates to the page that entry was written over.
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
	const landing = routerEntry(event.state);
	const historyIndex = routerIndex(landing, ROUTER_HISTORY_INDEX);
	if (landing === null || historyIndex === undefined) {
		fakePage.url = new URL(location.href);
		return;
	}
	const from = fakePage.url;
	const pageUrl = landing[ROUTER_PAGE_URL];
	const landedPage = new URL(typeof pageUrl === 'string' ? pageUrl : location.href);
	const landedState = (landing[ROUTER_STATES] ?? {}) as App.PageState;
	const navigationIndex = routerIndex(landing, ROUTER_NAVIGATION_INDEX);
	const onlyHashChanges = withoutHash(location) === withoutHash(from);
	const shallow = navigationIndex === currentNavigationIndex && (hasNavigated || onlyHashChanges);
	currentHistoryIndex = historyIndex;
	if (shallow || navigationIndex === undefined) {
		fakePage.url = landedPage;
		fakePage.state = landedState;
		return;
	}
	currentNavigationIndex = navigationIndex;
	hasNavigated = true;
	if (supersededBeforeLoading(from, landedPage)) return;
	fakePage.url = landedPage;
	fakePage.state = landedState;
	reportNavigation('popstate', from);
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
	return { page: fakePage };
}
