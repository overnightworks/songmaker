import { writable, type Writable } from 'svelte/store';

// The one stack of open layers (issue #1182): every open overlay -- a menu,
// picker, sheet, dialog, the phone drawer, full Now Playing, the cover editor,
// Edit details -- holds one place here while it shows, and Escape and Back
// both close the topmost one. Only with nothing open does Escape move a page
// level up (utils/escape-level-up.ts).
//
// On a library page a layer also owns one history entry, which Back closes it
// through; stores/navigation keeps those entries while the library history
// runs. The stack itself depends on nothing app-only, so a logged-out share
// page holds its overlays here too.
export interface Layer {
	readonly id: string;
	readonly close: () => void;
}

// What the library history does as layers come and go: `held` may give a new
// layer its own entry, `left` steps back off the entry a layer leaves behind.
export interface LayerHistory {
	held: (layer: Layer) => void;
	left: (layer: Layer) => void;
}

const openLayers: Layer[] = [];
const layersHeldOpen = new WeakSet<Layer>();
let layerHistory: LayerHistory | null = null;

export function keepLayerHistory(history: LayerHistory | null): void {
	layerHistory = history;
}

export function stackedLayers(): readonly Layer[] {
	return openLayers;
}

// Holds a layer until the returned leave runs. `close` is how Escape and Back
// close the overlay; the overlay leaves when it has closed.
export function holdLayer(id: string, close: () => void): () => void {
	const layer: Layer = { id, close };
	openLayers.push(layer);
	layerHistory?.held(layer);
	return () => leaveLayer(layer);
}

// Closes the topmost open layer the way its own close would, leaving it first
// so a navigation the close starts lands after its history entry is gone.
// Says whether there was one to close.
export function closeTopLayer(): boolean {
	const top = openLayers.at(-1);
	if (!top) return false;
	if (layersHeldOpen.has(top)) return true;
	leaveLayer(top);
	top.close();
	return true;
}

// A layer closed from below the top takes the layers above it along; one held
// open goes without holding itself again, its overlay having closed under it.
function leaveLayer(layer: Layer): void {
	const depth = openLayers.indexOf(layer);
	if (depth === -1) return;
	for (const leaving of openLayers.splice(depth).reverse()) {
		if (leaving !== layer && !layersHeldOpen.has(leaving)) leaving.close();
		layerHistory?.left(leaving);
	}
}

// Back has already stepped off the entries of the layers from `depth` up, so
// they close, topmost first, without stepping back again; one held open holds
// itself again, with a fresh entry. Returns them, lowest first.
export function dropLayersFrom(depth: number): Layer[] {
	const dropped = openLayers.splice(depth);
	for (const leaving of [...dropped].reverse()) leaving.close();
	return dropped;
}

// Holds and leaves one overlay's layer as its shown value changes. Escape and
// Back close it through `close`, which lands here again with `false` after the
// stack has already let go of the layer.
export function layerSwitch(id: string, close: () => void): (isShown: boolean) => void {
	let leave: (() => void) | null = null;
	return (isShown) => {
		if (isShown === (leave !== null)) return;
		if (isShown) {
			leave = holdLayer(id, close);
			return;
		}
		const leaving = leave;
		leave = null;
		leaving?.();
	};
}

// A menu, list or sheet a component owns (issue #1119) keeps what it shows in
// this store rather than in local state, `closed` meaning nothing is open.
// Every write holds or leaves its layer synchronously -- a close path that
// navigates straight afterwards has its step back queued ahead of the push,
// which an effect running after that push could not promise -- and Escape and
// Back close it by writing `closed`. The owner unmounting while open drops the
// last subscriber, which leaves the layer too.
export function historyLayerState<T>(id: string, closed: T): Writable<T> {
	let value = closed;
	const show = layerSwitch(id, () => set(closed));
	const shown = writable(closed, () => () => show(false));
	function set(next: T): void {
		value = next;
		show(next !== closed);
		shown.set(next);
	}
	return { subscribe: shown.subscribe, set, update: (change) => set(change(value)) };
}

// While `work` runs, Escape and Back close nothing (issue #1184): an overlay
// saving what the person typed holds this layer on top of its own, so the
// close waits for the save -- which closes the overlay on success, or leaves it
// open with the typed text and the reason on failure. Back has already stepped
// off the layer's entry when it reaches the stack, so the layer holds itself
// again, with a new entry for the next Back -- unless that Back jumped past the
// overlay too, which then has closed and needs no holding. Settling lets go of
// this layer alone: a layer opened above it during the save stays open.
export async function holdOpenWhile<T>(id: string, work: Promise<T>): Promise<T> {
	const guarded = openLayers.at(-1);
	function holdOpen(): Layer {
		const layer: Layer = {
			id,
			close: () => {
				if (guarded && openLayers.includes(guarded)) held = holdOpen();
			}
		};
		layersHeldOpen.add(layer);
		openLayers.push(layer);
		layerHistory?.held(layer);
		return layer;
	}
	let held = holdOpen();
	try {
		return await work;
	} finally {
		letGoOf(held);
	}
}

function letGoOf(layer: Layer): void {
	const depth = openLayers.indexOf(layer);
	if (depth === -1) return;
	openLayers.splice(depth, 1);
	layerHistory?.left(layer);
}

export function resetLayersForTests(): void {
	openLayers.length = 0;
	layerHistory = null;
}
