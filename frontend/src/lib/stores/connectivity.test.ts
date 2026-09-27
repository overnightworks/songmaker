import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '$lib/api/fetch';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '$lib/constants';
import { browserReportsOnline, lostNetwork, serverRefusal } from '$lib/test-utils/network';
import {
	offline,
	reloadWhileUnreachable,
	reportResourceStreamReachable,
	resetConnectivityForTests,
	whenBackOnline
} from './connectivity';

afterEach(() => {
	resetConnectivityForTests();
	vi.restoreAllMocks();
	vi.useRealTimers();
});

describe('connectivity', () => {
	it('is online while the browser and the live stream both reach the server', () => {
		expect(get(offline)).toBe(false);
	});

	it('is offline from the first read when the page opens without a network', () => {
		vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);

		expect(get(offline)).toBe(true);
	});

	it('follows the browser losing the network and getting it back', () => {
		const seen: boolean[] = [];
		const stop = offline.subscribe((value) => seen.push(value));

		browserReportsOnline(false);
		browserReportsOnline(true);
		stop();

		expect(seen).toEqual([false, true, false]);
	});

	it('is offline while the live stream cannot reach the server even though the browser is online', () => {
		const stop = offline.subscribe(() => {});

		reportResourceStreamReachable(false);
		expect(get(offline)).toBe(true);

		reportResourceStreamReachable(true);
		expect(get(offline)).toBe(false);
		stop();
	});

	it('stays offline until the network and the stream are both back', () => {
		const stop = offline.subscribe(() => {});
		browserReportsOnline(false);
		reportResourceStreamReachable(false);

		browserReportsOnline(true);
		expect(get(offline)).toBe(true);

		reportResourceStreamReachable(true);
		expect(get(offline)).toBe(false);
		stop();
	});

	it('calls back each time the connection comes back, not while it stays up', () => {
		const comeBack = vi.fn();
		const stop = whenBackOnline(comeBack);

		reportResourceStreamReachable(true);
		expect(comeBack).not.toHaveBeenCalled();

		browserReportsOnline(false);
		browserReportsOnline(true);
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		stop();
		browserReportsOnline(false);
		browserReportsOnline(true);

		expect(comeBack).toHaveBeenCalledTimes(2);
	});

	it('calls back when a page opened offline gets its connection', () => {
		reportResourceStreamReachable(false);
		const comeBack = vi.fn();
		const stop = whenBackOnline(comeBack);

		reportResourceStreamReachable(true);
		stop();

		expect(comeBack).toHaveBeenCalledOnce();
	});
});

describe('reloadWhileUnreachable', () => {
	it('while offline, reloads once when the connection is back', () => {
		reportResourceStreamReachable(false);
		const reload = vi.fn();
		const reloads = reloadWhileUnreachable(reload);

		expect(reloads.afterNetworkFailure()).toBe('on-reconnect');
		reportResourceStreamReachable(true);
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);

		expect(reload).toHaveBeenCalledOnce();
	});

	it('once its backoff is spent, still reloads when a dropped connection comes back', () => {
		vi.useFakeTimers();
		const reload = vi.fn();
		const reloads = reloadWhileUnreachable(reload);

		const outcomes = UNREACHABLE_RELOAD_DELAYS_MS.map(() => reloads.afterNetworkFailure());
		expect(outcomes).toEqual(UNREACHABLE_RELOAD_DELAYS_MS.map(() => 'scheduled'));
		expect(reloads.afterNetworkFailure()).toBe('exhausted');
		expect(reload).not.toHaveBeenCalled();

		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		reloads.stop();

		expect(reload).toHaveBeenCalledOnce();
	});

	describe('nameLoadFailure', () => {
		const FALLBACK = 'Failed to load users';

		it('names nothing for a lost network while a reload is still coming', () => {
			vi.useFakeTimers();
			const reloads = reloadWhileUnreachable(vi.fn());

			expect(reloads.nameLoadFailure(lostNetwork(), FALLBACK)).toBeNull();
			reportResourceStreamReachable(false);
			expect(reloads.nameLoadFailure(lostNetwork(), FALLBACK)).toBeNull();
		});

		it('names the fallback, never the browser text, once the backoff is spent', () => {
			vi.useFakeTimers();
			const reloads = reloadWhileUnreachable(vi.fn());
			UNREACHABLE_RELOAD_DELAYS_MS.forEach(() => reloads.afterNetworkFailure());

			expect(reloads.nameLoadFailure(lostNetwork(), FALLBACK)).toBe(FALLBACK);
		});

		it('hides a spent backoff while the strip shows and forgets it once the load runs again', () => {
			vi.useFakeTimers();
			const reload = vi.fn();
			const reloads = reloadWhileUnreachable(reload);
			UNREACHABLE_RELOAD_DELAYS_MS.forEach(() => reloads.afterNetworkFailure());
			reloads.nameLoadFailure(lostNetwork(), FALLBACK);
			expect(get(reloads.loadFailure)).toBe(FALLBACK);

			reportResourceStreamReachable(false);
			expect(get(reloads.loadFailure)).toBeNull();

			reportResourceStreamReachable(true);
			expect(reload).toHaveBeenCalledOnce();
			expect(get(reloads.loadFailure)).toBeNull();
		});

		it('keeps a server answer named while the strip shows', () => {
			const reloads = reloadWhileUnreachable(vi.fn());
			reloads.nameLoadFailure(serverRefusal('Database is migrating'), FALLBACK);

			reportResourceStreamReachable(false);

			expect(get(reloads.loadFailure)).toBe('Database is migrating');
		});

		it.each([
			{ answer: 'its reason', err: new ApiError(503, 'Database is migrating', '/api/users') },
			{ answer: 'no reason', err: new ApiError(500, '', '/api/users') }
		])('names a server answer with $answer and stops a pending reload', ({ err }) => {
			vi.useFakeTimers();
			const reload = vi.fn();
			const reloads = reloadWhileUnreachable(reload);
			reloads.afterNetworkFailure();

			expect(reloads.nameLoadFailure(err, FALLBACK)).toBe(err.detail || FALLBACK);
			vi.runAllTimers();
			expect(reload).not.toHaveBeenCalled();
		});
	});
});
