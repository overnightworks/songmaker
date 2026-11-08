import { get } from 'svelte/store';
import { resourceSync, retryResourceSync, type ResourceSyncState } from './resourceSync.ts';

export function libraryLoadFailed(state: ResourceSyncState): boolean {
	return !state.ready && state.status === 'error';
}

/**
 * Runs `run` one microtask after each change of the sync's ready flag from
 * false to true, once the store's own bookkeeping is done. The flag at
 * subscribe time is the baseline, never an edge. The returned function stops
 * it, including a run already queued.
 */
export function onLibraryReady(run: () => void): () => void {
	let stopped = false;
	let wasReady = get(resourceSync).ready;
	const unsubscribe = resourceSync.subscribe(({ ready }) => {
		const becameReady = ready && !wasReady;
		wasReady = ready;
		if (!becameReady) return;
		queueMicrotask(() => {
			if (!stopped) run();
		});
	});
	return () => {
		stopped = true;
		unsubscribe();
	};
}

/**
 * What a Retry does: while the library load failed it retries the sync only,
 * and the library's return reaches every surface on the ready edge; otherwise
 * it runs the control's own retry.
 */
export async function retryLibraryOr(ownRetry: () => Promise<unknown>): Promise<boolean> {
	if (libraryLoadFailed(get(resourceSync))) return retryResourceSync();
	await ownRetry();
	return true;
}

interface LibraryReturnReload {
	loadStarted(): void;
	loadFailed(): void;
	loadSucceeded(): void;
	dispose(): void;
}

/**
 * Re-runs a failed address once the library is ready: when its last load
 * failed and none runs at the ready edge, or when a load that began before
 * the library was ready fails after it. Only the latest load counts; a
 * re-run starts with the library ready, so its failure triggers nothing more.
 */
export function reloadWhenLibraryReturns(reload: () => void): LibraryReturnReload {
	let disposed = false;
	let loading = false;
	let failed = false;
	let startedBeforeReady = false;

	const stopFollowing = onLibraryReady(() => {
		if (failed && !loading) rerun();
	});

	function rerun(): void {
		failed = false;
		reload();
	}

	return {
		loadStarted() {
			if (disposed) return;
			loading = true;
			failed = false;
			startedBeforeReady = !get(resourceSync).ready;
		},
		loadFailed() {
			if (disposed) return;
			loading = false;
			failed = true;
			// Queued so the caller's own failure handling returns before the re-run starts.
			if (startedBeforeReady && get(resourceSync).ready) {
				queueMicrotask(() => {
					if (!disposed && failed && !loading) rerun();
				});
			}
		},
		loadSucceeded() {
			if (disposed) return;
			loading = false;
			failed = false;
		},
		dispose() {
			disposed = true;
			stopFollowing();
		}
	};
}
