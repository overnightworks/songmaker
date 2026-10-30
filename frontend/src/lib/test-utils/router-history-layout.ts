import { parse, stringify } from 'devalue';

// The router's side of SvelteKit's private history-entry layout: the record it
// writes into an entry and how it reads it back. Tests and the e2e helpers
// build and read router entries only through these, so the keys stay in this
// file; the app reads them in history/routerHistoryState.ts. It imports only
// devalue, so the e2e helpers run it on the Node side.

export interface RouterHistoryPlace {
	historyIndex?: number;
	navigationIndex?: number;
	pageUrl?: string;
	resetIndex?: number;
}

export interface RouterHistoryEntry extends RouterHistoryPlace {
	pageState?: Record<string, unknown>;
}

export function routerHistoryEntry(
	pageState: object,
	place: RouterHistoryPlace = {}
): Record<string, unknown> {
	return {
		'sveltekit:metadata': {
			historyIndex: place.historyIndex,
			navigationIndex: place.navigationIndex,
			pageUrl: place.pageUrl,
			state: stringify(pageState),
			persistState: false,
			resetIndex: place.resetIndex ?? 0
		}
	};
}

function numberOrUndefined(value: unknown): number | undefined {
	return typeof value === 'number' ? value : undefined;
}

export function routerHistoryEntryOf(state: unknown): RouterHistoryEntry | null {
	if (typeof state !== 'object' || state === null) return null;
	const record = (state as Record<string, unknown>)['sveltekit:metadata'];
	if (typeof record !== 'object' || record === null) return null;
	const metadata = record as Record<string, unknown>;
	const pageUrl = metadata['pageUrl'];
	const serialized = metadata['state'];
	return {
		historyIndex: numberOrUndefined(metadata['historyIndex']),
		navigationIndex: numberOrUndefined(metadata['navigationIndex']),
		pageUrl: typeof pageUrl === 'string' ? pageUrl : undefined,
		resetIndex: numberOrUndefined(metadata['resetIndex']),
		pageState:
			typeof serialized === 'string' ? (parse(serialized) as Record<string, unknown>) : undefined
	};
}
