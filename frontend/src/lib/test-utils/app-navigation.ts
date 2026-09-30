import type { AfterNavigate, NavigationTarget } from '@sveltejs/kit';
import { onMount } from 'svelte';
import { vi } from 'vitest';

// A stand-in for `$app/navigation` that writes history the way SvelteKit's
// router does, shared by every test that mocks the module:
//   vi.mock('$app/navigation', async () =>
//     (await import('$lib/test-utils/app-navigation')).fakeAppNavigation());
// `goto` adds (or, with `replaceState`, rewrites) a router entry and tells
// every mounted `afterNavigate` callback; `pushState` and `replaceState` are
// shallow routing, which keeps the page state under the entry's states key.
//
// It also owns every raw write into the test browser's history, which tests
// reach through library-history.ts. It imports no store: the stores import
// `$app/navigation`, so a fake that imported them back would wait on itself.
const ROUTER_HISTORY_INDEX = 'sveltekit:history';
const ROUTER_NAVIGATION_INDEX = 'sveltekit:navigation';
const ROUTER_PAGE_URL = 'sveltekit:pageurl';
const ROUTER_STATES = 'sveltekit:states';

type HistoryWriteMode = 'push' | 'replace';

interface GotoOptions {
	replaceState?: boolean;
	state?: App.PageState;
}

export function writeHistoryEntry(entry: unknown, url: string | URL, mode: HistoryWriteMode): void {
	if (mode === 'push') history.pushState(entry, '', url);
	else history.replaceState(entry, '', url);
}

// The page the fake router shows: `goto` moves it, shallow routing only
// changes its state.
export const fakePage: { url: URL; state: App.PageState } = {
	url: new URL(location.href),
	state: {}
};

const afterNavigateCallbacks = new Set<(navigation: AfterNavigate) => void>();

function routerIndex(key: string): number {
	const entry: unknown = history.state;
	if (typeof entry !== 'object' || entry === null) return 0;
	const index: unknown = (entry as Record<string, unknown>)[key];
	return typeof index === 'number' ? index : 0;
}

function navigationTarget(url: URL): NavigationTarget {
	return { params: {}, route: { id: null }, url, scroll: null };
}

async function fakeGoto(url: string | URL, options: GotoOptions = {}): Promise<void> {
	const mode: HistoryWriteMode = options.replaceState ? 'replace' : 'push';
	const step = mode === 'push' ? 1 : 0;
	const state = options.state ?? {};
	const from = fakePage.url;
	writeHistoryEntry(
		{
			[ROUTER_HISTORY_INDEX]: routerIndex(ROUTER_HISTORY_INDEX) + step,
			[ROUTER_NAVIGATION_INDEX]: routerIndex(ROUTER_NAVIGATION_INDEX) + step,
			[ROUTER_STATES]: state
		},
		url,
		mode
	);
	fakePage.url = new URL(location.href);
	fakePage.state = state;
	const navigation: AfterNavigate = {
		type: 'goto',
		from: navigationTarget(from),
		to: navigationTarget(fakePage.url),
		willUnload: false,
		complete: Promise.resolve()
	};
	for (const callback of afterNavigateCallbacks) callback(navigation);
}

function writeShallowEntry(url: string | URL, state: App.PageState, mode: HistoryWriteMode): void {
	const step = mode === 'push' ? 1 : 0;
	writeHistoryEntry(
		{
			[ROUTER_HISTORY_INDEX]: routerIndex(ROUTER_HISTORY_INDEX) + step,
			[ROUTER_NAVIGATION_INDEX]: routerIndex(ROUTER_NAVIGATION_INDEX),
			[ROUTER_PAGE_URL]: fakePage.url.href,
			[ROUTER_STATES]: state
		},
		url,
		mode
	);
	fakePage.state = state;
}

function fakeAfterNavigate(callback: (navigation: AfterNavigate) => void): void {
	onMount(() => {
		afterNavigateCallbacks.add(callback);
		return () => afterNavigateCallbacks.delete(callback);
	});
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
		afterNavigate: vi.fn(fakeAfterNavigate)
	};
}
