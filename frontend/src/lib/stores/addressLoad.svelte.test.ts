import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import { NetworkError } from '#lib/api/fetch.ts';
import { reportResourceStreamReachable } from './connectivity.ts';
import { resetResourceSyncForTests, resourceSync } from './resourceSync.ts';
import { createAddressLoad } from './addressLoad.svelte.ts';

type Answer = 'found' | 'unknown';

function mountOwner(load: () => Promise<Answer>) {
	let owner!: ReturnType<typeof createAddressLoad<'unknown'>>;
	const dispose = $effect.root(() => {
		owner = createAddressLoad<'unknown'>({ load, fallbackMessage: 'Could not load.' });
	});
	flushSync();
	return { owner, dispose };
}

beforeEach(() => {
	resetResourceSyncForTests();
	reportResourceStreamReachable(true);
});

afterEach(() => {
	reportResourceStreamReachable(true);
	resetResourceSyncForTests();
});

it('shows the answer of the load', async () => {
	const { owner, dispose } = mountOwner(() => Promise.resolve('unknown'));

	expect(owner.state).toBe('resolving');
	await tick();

	expect(owner.state).toBe('unknown');
	dispose();
});

it('drops a slower answer that settles after a newer load answered', async () => {
	const slow = Promise.withResolvers<Answer>();
	const load = vi
		.fn<() => Promise<Answer>>()
		.mockReturnValueOnce(slow.promise)
		.mockResolvedValueOnce('unknown');
	const { owner, dispose } = mountOwner(load);

	void owner.tryAgain();
	await tick();
	slow.resolve('found');
	await tick();

	expect(owner.state).toBe('unknown');
	dispose();
});

it('names the fallback when the load fails without a reason', async () => {
	const { owner, dispose } = mountOwner(() => Promise.reject(new Error()));
	await tick();

	expect(owner.state).toBe('unreachable');
	expect(owner.failure).toBe('Could not load.');
	dispose();
});

it('does not load again on the online edge after disposal', async () => {
	reportResourceStreamReachable(false);
	const load = vi.fn<() => Promise<Answer>>(() =>
		Promise.reject(new NetworkError('/api', new TypeError('offline')))
	);
	const { dispose } = mountOwner(load);
	await tick();
	dispose();
	load.mockClear();

	reportResourceStreamReachable(true);
	await tick();

	expect(load).not.toHaveBeenCalled();
});

it('does not load again on the library ready edge after disposal', async () => {
	const load = vi.fn<() => Promise<Answer>>(() => Promise.reject(new Error('refused')));
	const { dispose } = mountOwner(load);
	await tick();
	dispose();
	load.mockClear();

	resourceSync.update((state) => ({ ...state, ready: true }));
	await tick();
	await tick();

	expect(load).not.toHaveBeenCalled();
});
