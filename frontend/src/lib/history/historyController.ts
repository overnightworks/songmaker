import { pushState, replaceState } from '$app/navigation';

// The one owner of the tab's history (issue #1006, ruling of 01.10.2026): only
// this module writes or traverses history. Every entry it writes carries an
// id, so a landing -- a Back, a Forward, a jump of several entries, or one of
// the controller's own step-backs -- says by itself where history now stands,
// and which open layers and pending step-backs it has left behind. Nothing
// installs it yet; #1006 H1 does.

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

const SVELTEKIT_HISTORY_STATES_KEY = 'sveltekit:states';
const ENTRY_ID_COUNTER_KEY = 'songmaker:history-entry-id';
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
	const stored = storage.getItem(ENTRY_ID_COUNTER_KEY) ?? '0';
	if (!/^\d+$/.test(stored)) {
		throw new Error(`The history entry counter holds ${JSON.stringify(stored)}, not a count`);
	}
	const id = Number(stored) + 1;
	storage.setItem(ENTRY_ID_COUNTER_KEY, String(id));
	return id;
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

// SvelteKit keeps the page state of an entry under its own key beside its
// router bookkeeping; anything else in a history entry is foreign.
function entryOfHistoryState(state: unknown): HistoryEntry | null {
	if (!isRecord(state)) return null;
	const pageState = state[SVELTEKIT_HISTORY_STATES_KEY];
	if (!isRecord(pageState)) return null;
	return isHistoryEntry(pageState.entry) ? pageState.entry : null;
}

export function landedEntry(event: PopStateEvent): HistoryEntry | null {
	return entryOfHistoryState(event.state);
}

let ledger: HistoryLedger = EMPTY_LEDGER;
const stepBackWaiters = new Map<number, (() => void)[]>();

function newEntry(layer?: string): HistoryEntry {
	const id = allocateEntryId(sessionStorage);
	return layer === undefined ? { id } : { id, layer };
}

// A push allocates an id; an entry pushed for a layer belongs to that layer
// until a landing leaves it.
export function pushEntry(url: string, state: App.PageState, layer?: string): HistoryEntry {
	const entry = newEntry(layer);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	pushState(url, { ...state, entry });
	ledger =
		layer === undefined
			? { ...ledger, current: entry }
			: { ...ledger, layers: [...ledger.layers, { layer, entry: entry.id }] };
	return entry;
}

// A replace rewrites what an entry shows, never which entry it is: it keeps
// the id and the layer mark. An entry the controller has not stamped yet gets
// its first id here.
export function replaceEntry(url: string, state: App.PageState): HistoryEntry {
	const entry = entryOfHistoryState(history.state) ?? newEntry();
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path; callers pass resolved addresses
	replaceState(url, { ...state, entry });
	if (entry.layer === undefined) ledger = { ...ledger, current: entry };
	return entry;
}

// Steps back once and resolves when a landing at or below `target` settles the
// step, whichever Back or Forward that landing came from.
export function stepBackTo(target: number): Promise<void> {
	ledger = { ...ledger, stepBacks: [...ledger.stepBacks, target] };
	const settled = new Promise<void>((resolve) => {
		stepBackWaiters.set(target, [...(stepBackWaiters.get(target) ?? []), resolve]);
	});
	history.back();
	return settled;
}

function settleStepBack(target: number): void {
	const [settle, ...waiting] = stepBackWaiters.get(target) ?? [];
	if (waiting.length > 0) stepBackWaiters.set(target, waiting);
	else stepBackWaiters.delete(target);
	settle?.();
}

// The landing handler hears each landing once the controller has settled its
// step-backs and, on a layer entry no open layer owns, started stepping off it.
export function listenForLandings(onLanding: (landing: Landing) => void): () => void {
	function onPopstate(event: PopStateEvent): void {
		const landed = landedEntry(event);
		const landing = land(ledger, landed);
		ledger = landing.ledger;
		for (const target of landing.settled) settleStepBack(target);
		if (landing.stepOff) void stepBackTo(rankOf(landed) - 1);
		onLanding(landing);
	}
	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export function resetHistoryControllerForTests(): void {
	ledger = EMPTY_LEDGER;
	stepBackWaiters.clear();
}
