import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { browserReportsOnline } from '$lib/test-utils/network';
import {
	offline,
	reportResourceStreamReachable,
	resetConnectivityForTests,
	whenBackOnline
} from './connectivity';

afterEach(() => {
	resetConnectivityForTests();
	vi.restoreAllMocks();
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
