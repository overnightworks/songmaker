import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

vi.mock('#lib/stores/resourceSync.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/resourceSync.ts')>()),
	retryResourceSync: vi.fn()
}));

import {
	resetResourceSyncForTests,
	resourceSync,
	retryResourceSync
} from '#lib/stores/resourceSync.ts';
import {
	libraryLoadFailed,
	onLibraryReady,
	reloadWhenLibraryReturns,
	retryLibraryOr
} from './libraryRecovery.ts';

type SyncPatch = Partial<ReturnType<typeof currentSync>>;

function currentSync() {
	let value!: Parameters<Parameters<typeof resourceSync.subscribe>[0]>[0];
	resourceSync.subscribe((state) => (value = state))();
	return value;
}

function setSync(patch: SyncPatch): void {
	resourceSync.update((state) => ({ ...state, ...patch }));
}

async function runQueuedMicrotasks(): Promise<void> {
	await Promise.resolve();
	await Promise.resolve();
}

beforeEach(() => {
	resetResourceSyncForTests();
	vi.mocked(retryResourceSync).mockReset();
});

afterEach(() => {
	resetResourceSyncForTests();
});

describe('libraryLoadFailed', () => {
	it.each([
		{ ready: false, status: 'error', failed: true },
		{ ready: false, status: 'connecting', failed: false },
		{ ready: true, status: 'error', failed: false },
		{ ready: true, status: 'live', failed: false }
	] as const)(
		'answers $failed for ready $ready and status $status',
		({ ready, status, failed }) => {
			setSync({ ready, status });
			expect(libraryLoadFailed(currentSync())).toBe(failed);
		}
	);
});

describe('onLibraryReady', () => {
	it('runs nothing for a flag already ready at subscribe time', async () => {
		setSync({ ready: true });
		const run = vi.fn();
		const stop = onLibraryReady(run);
		await runQueuedMicrotasks();
		expect(run).not.toHaveBeenCalled();
		stop();
	});

	it('runs once, one microtask after each change from not ready to ready', async () => {
		const run = vi.fn();
		const stop = onLibraryReady(run);

		setSync({ ready: true });
		expect(run).not.toHaveBeenCalled();
		await runQueuedMicrotasks();
		expect(run).toHaveBeenCalledTimes(1);

		setSync({ status: 'live' });
		await runQueuedMicrotasks();
		expect(run).toHaveBeenCalledTimes(1);

		setSync({ ready: false });
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(run).toHaveBeenCalledTimes(2);
		stop();
	});

	it('runs nothing when stopped between the edge and its microtask', async () => {
		const run = vi.fn();
		const stop = onLibraryReady(run);
		setSync({ ready: true });
		stop();
		await runQueuedMicrotasks();
		expect(run).not.toHaveBeenCalled();
	});

	it('runs nothing for an edge after the stop', async () => {
		const run = vi.fn();
		onLibraryReady(run)();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(run).not.toHaveBeenCalled();
	});
});

describe('retryLibraryOr', () => {
	it('retries only the sync for a failed load and answers its value', async () => {
		setSync({ ready: false, status: 'error' });
		vi.mocked(retryResourceSync).mockResolvedValue(false);
		const ownRetry = vi.fn().mockResolvedValue(undefined);

		await expect(retryLibraryOr(ownRetry)).resolves.toBe(false);

		expect(retryResourceSync).toHaveBeenCalledTimes(1);
		expect(ownRetry).not.toHaveBeenCalled();
	});

	it.each([
		{ label: 'a retry in flight', patch: { ready: false, status: 'connecting' } },
		{ label: 'a live library', patch: { ready: true, status: 'live' } }
	] as const)('runs its own retry at once for $label', async ({ patch }) => {
		setSync(patch);
		let settle!: () => void;
		const ownRetry = vi.fn(() => new Promise<void>((resolve) => (settle = resolve)));

		const pressed = retryLibraryOr(ownRetry);
		expect(ownRetry).toHaveBeenCalledTimes(1);
		let settled = false;
		void pressed.then(() => (settled = true));
		await runQueuedMicrotasks();
		expect(settled).toBe(false);

		settle();
		await expect(pressed).resolves.toBe(true);
		expect(retryResourceSync).not.toHaveBeenCalled();
	});
});

describe('reloadWhenLibraryReturns', () => {
	let reload: Mock<() => void>;
	let recovery: ReturnType<typeof reloadWhenLibraryReturns>;

	beforeEach(() => {
		reload = vi.fn<() => void>();
		recovery = reloadWhenLibraryReturns(reload);
	});

	afterEach(() => recovery.dispose());

	it('re-runs once at the ready edge after a load that failed before it', async () => {
		recovery.loadStarted();
		recovery.loadFailed();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('re-runs once when a load that began before the edge fails after it', async () => {
		recovery.loadStarted();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(reload).not.toHaveBeenCalled();

		recovery.loadFailed();
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('re-runs once when a load across the edge fails before the edge microtask runs', async () => {
		recovery.loadStarted();
		setSync({ ready: true });
		recovery.loadFailed();
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('triggers nothing more when the re-run fails again', async () => {
		recovery.loadStarted();
		recovery.loadFailed();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		recovery.loadStarted();
		recovery.loadFailed();
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('does not re-run for a load in flight at the edge that succeeds', async () => {
		recovery.loadStarted();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		recovery.loadSucceeded();
		await runQueuedMicrotasks();
		expect(reload).not.toHaveBeenCalled();
	});

	it('re-runs once for a failure and an edge that follow an earlier success', async () => {
		recovery.loadStarted();
		recovery.loadSucceeded();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		setSync({ ready: false });
		recovery.loadStarted();
		recovery.loadFailed();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('forgets a failure that a later load superseded', async () => {
		recovery.loadStarted();
		recovery.loadFailed();
		recovery.loadStarted();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(reload).not.toHaveBeenCalled();
	});

	it('re-runs a failure across the edge only after the failing caller returned', async () => {
		recovery.loadStarted();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		recovery.loadFailed();
		expect(reload).not.toHaveBeenCalled();
		await runQueuedMicrotasks();
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('re-runs nothing for a failure across the edge disposed before its re-run', async () => {
		recovery.loadStarted();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		recovery.loadFailed();
		recovery.dispose();
		await runQueuedMicrotasks();
		expect(reload).not.toHaveBeenCalled();
	});

	it('re-runs nothing after dispose', async () => {
		recovery.loadStarted();
		recovery.loadFailed();
		recovery.dispose();
		setSync({ ready: true });
		await runQueuedMicrotasks();
		expect(reload).not.toHaveBeenCalled();
	});
});
