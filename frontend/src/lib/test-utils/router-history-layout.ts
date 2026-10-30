// The router's side of SvelteKit's private history-entry layout: what it
// writes beside an entry's page state and how it reads it back. Tests and the
// e2e helpers build and read router entries only through these, so the keys
// stay in this file; the app reads them in history/routerHistoryState.ts.
// It imports nothing, so the e2e helpers run it on the Node side.

export interface RouterHistoryPlace {
	historyIndex?: number;
	navigationIndex?: number;
	pageUrl?: string;
}

export interface RouterHistoryEntry extends RouterHistoryPlace {
	pageState?: Record<string, unknown>;
}

export function routerHistoryEntry(
	pageState: object,
	place: RouterHistoryPlace = {}
): Record<string, unknown> {
	return {
		'sveltekit:history': place.historyIndex,
		'sveltekit:navigation': place.navigationIndex,
		'sveltekit:pageurl': place.pageUrl,
		'sveltekit:states': pageState
	};
}

function numberOrUndefined(value: unknown): number | undefined {
	return typeof value === 'number' ? value : undefined;
}

export function routerHistoryEntryOf(state: unknown): RouterHistoryEntry | null {
	if (typeof state !== 'object' || state === null) return null;
	const entry = state as Record<string, unknown>;
	const pageUrl = entry['sveltekit:pageurl'];
	const pageState = entry['sveltekit:states'];
	return {
		historyIndex: numberOrUndefined(entry['sveltekit:history']),
		navigationIndex: numberOrUndefined(entry['sveltekit:navigation']),
		pageUrl: typeof pageUrl === 'string' ? pageUrl : undefined,
		pageState:
			typeof pageState === 'object' && pageState !== null
				? (pageState as Record<string, unknown>)
				: undefined
	};
}
