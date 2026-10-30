// The app's one reader of SvelteKit's private history-entry layout: its page
// state and its place among the tab's entries, which it keeps under its own
// keys beside each other. An entry without them was not written by the router.

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

export function pageStateOfHistoryState(state: unknown): Record<string, unknown> | null {
	if (!isRecord(state)) return null;
	const pageState = state['sveltekit:states'];
	return isRecord(pageState) ? pageState : null;
}

// SvelteKit's place for an entry among the tab's entries: one more than the
// entry it was pushed over, the same as the entry it was written over.
export function routerIndexOf(state: unknown): number | undefined {
	const index = isRecord(state) ? state['sveltekit:history'] : undefined;
	return typeof index === 'number' ? index : undefined;
}
