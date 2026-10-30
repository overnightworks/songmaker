import { parse } from 'devalue';

// The app's one reader of SvelteKit's private history-entry layout: the one
// record the router keeps in an entry, with the entry's page state and its
// place among the tab's entries. An entry without it was not written by the
// router.

interface RouterHistoryRecord {
	readonly historyIndex?: unknown;
	readonly pageUrl?: unknown;
	readonly state?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function routerRecordOf(state: unknown): RouterHistoryRecord | null {
	const record = isRecord(state) ? state['sveltekit:metadata'] : undefined;
	return isRecord(record) ? record : null;
}

export function pageStateOfHistoryState(state: unknown): Record<string, unknown> | null {
	const serialized = routerRecordOf(state)?.state;
	if (typeof serialized !== 'string') return null;
	const pageState: unknown = parse(serialized);
	return isRecord(pageState) ? pageState : null;
}

// SvelteKit's place for an entry among the tab's entries: one more than the
// entry it was pushed over, the same as the entry it was written over.
export function routerIndexOf(state: unknown): number | undefined {
	const index = routerRecordOf(state)?.historyIndex;
	return typeof index === 'number' ? index : undefined;
}

// The page the router loaded the entry's route for, which differs from the
// entry's address when shallow routing wrote the entry over another page.
export function pageUrlOfHistoryState(state: unknown): string | undefined {
	const url = routerRecordOf(state)?.pageUrl;
	return typeof url === 'string' ? url : undefined;
}
