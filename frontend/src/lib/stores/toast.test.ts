import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NEW_PLACE_OFFLINE } from '#lib/constants.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { get, writable } from 'svelte/store';
import { toasts, addToast, addUndoToast, dismissToast } from './toast';
import { reportResourceStreamReachable, resetConnectivityForTests } from './connectivity';

beforeEach(() => {
	for (const toast of get(toasts)) dismissToast(toast.id);
	vi.useFakeTimers();
});

afterEach(() => {
	resetConnectivityForTests();
});

describe('toast store', () => {
	it('addToast creates a toast with correct fields', () => {
		addToast('test message', 'error');
		const all = get(toasts);
		expect(all).toHaveLength(1);
		expect(all[0].message).toBe('test message');
		expect(all[0].type).toBe('error');
		expect(typeof all[0].id).toBe('number');
	});

	it('addToast defaults to info type', () => {
		addToast('info message');
		expect(get(toasts)[0].type).toBe('info');
	});

	it('toasts auto-dismiss after 5 seconds', () => {
		addToast('temporary', 'success');
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(5000);
		expect(get(toasts)).toHaveLength(0);
	});

	it.each([
		{ length: 'brief' as const, lastsMs: 5000 },
		{ length: 'long' as const, lastsMs: 30000 }
	])('a $length undo toast lasts $lastsMs ms, then ends its offer', ({ length, lastsMs }) => {
		const expire = vi.fn();
		addUndoToast('v1 loaded', { label: 'Undo', handler: () => {}, expire }, length);
		vi.advanceTimersByTime(lastsMs - 1);
		expect(get(toasts)).toHaveLength(1);
		expect(expire).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(get(toasts)).toHaveLength(0);
		expect(expire).toHaveBeenCalledOnce();
	});

	it('an undo toast closes as soon as its undo stops holding, so a shown Undo always restores', () => {
		const holds = writable(true);
		addUndoToast('v1 loaded', { label: 'Undo', handler: () => {}, holds }, 'brief');
		expect(get(toasts)).toHaveLength(1);
		holds.set(false);
		expect(get(toasts)).toHaveLength(0);
	});

	it('an undo toast set aside leaves the screen and keeps its remaining time until it comes back', () => {
		const setAside = writable(false);
		const expire = vi.fn();
		addUndoToast('v1 loaded', { label: 'Undo', handler: () => {}, setAside, expire }, 'brief');
		vi.advanceTimersByTime(1000);

		setAside.set(true);
		expect(get(toasts)).toEqual([]);
		vi.advanceTimersByTime(10000);
		expect(expire).not.toHaveBeenCalled();

		setAside.set(false);
		expect(get(toasts).map((toast) => toast.message)).toEqual(['v1 loaded']);
		vi.advanceTimersByTime(3999);
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(1);
		expect(get(toasts)).toEqual([]);
		expect(expire).toHaveBeenCalledOnce();
	});

	it('an undo toast that stops holding while set aside never comes back', () => {
		const setAside = writable(false);
		const holds = writable(true);
		addUndoToast('v1 loaded', { label: 'Undo', handler: () => {}, holds, setAside }, 'brief');
		setAside.set(true);
		holds.set(false);
		setAside.set(false);
		expect(get(toasts)).toEqual([]);
	});

	it('error toasts persist until manually dismissed', () => {
		addToast('boom', 'error');
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(60000);
		expect(get(toasts)).toHaveLength(1);
		dismissToast(get(toasts)[0].id);
		expect(get(toasts)).toHaveLength(0);
	});

	it('dismissToast removes a specific toast', () => {
		addToast('first', 'info');
		addToast('second', 'error');
		const all = get(toasts);
		expect(all).toHaveLength(2);
		dismissToast(all[0].id);
		expect(get(toasts)).toHaveLength(1);
		expect(get(toasts)[0].message).toBe('second');
	});

	it('multiple toasts stack', () => {
		addToast('one', 'info');
		addToast('two', 'error');
		addToast('three', 'success');
		expect(get(toasts)).toHaveLength(3);
	});

	it('each toast gets a unique id', () => {
		addToast('a', 'info');
		addToast('b', 'info');
		const all = get(toasts);
		expect(all[0].id).not.toBe(all[1].id);
	});

	it('auto-dismiss only removes the specific toast', () => {
		addToast('early', 'info');
		vi.advanceTimersByTime(3000);
		addToast('late', 'info');
		vi.advanceTimersByTime(2000);
		const remaining = get(toasts);
		expect(remaining).toHaveLength(1);
		expect(remaining[0].message).toBe('late');
	});

	it.each(
		[
			{
				name: 'network',
				cause: new NetworkError('/api/test', new TypeError('fetch')),
				clears: true
			},
			{
				name: 'timeout',
				cause: new NetworkError('/api/test', new DOMException('timeout'), 'timeout'),
				clears: true
			},
			{ name: 'refusal', cause: new ApiError(503, 'Unavailable', '/api/test'), clears: false },
			{ name: 'unknown', cause: new TypeError('bug'), clears: false },
			{ name: 'absent', cause: undefined, clears: false }
		].flatMap((entry) => [true, false].map((offlineFirst) => ({ ...entry, offlineFirst })))
	)('1160-F36-cause: $name with offline first=$offlineFirst', ({ cause, clears, offlineFirst }) => {
		if (offlineFirst) reportResourceStreamReachable(false);
		const id = addToast('Failure', 'error', cause);
		expect(get(toasts)).toEqual([{ id, message: 'Failure', type: 'error' }]);
		if (!offlineFirst) reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		expect(get(toasts).map((toast) => toast.id)).toEqual(clears ? [] : [id]);
	});

	it.each([true, false])(
		'1160-F36-cause: unmigrated new-album toast retains offline-first=%s clearing',
		(offlineFirst) => {
			if (offlineFirst) reportResourceStreamReachable(false);
			const id = addToast(NEW_PLACE_OFFLINE, 'error');
			expect(get(toasts).map((toast) => toast.id)).toEqual([id]);
			if (!offlineFirst) reportResourceStreamReachable(false);
			reportResourceStreamReachable(true);
			expect(get(toasts).map((toast) => toast.id)).toEqual(offlineFirst ? [] : [id]);
		}
	);

	it('1160-F36-lifetime: each outage clears its network failures and leaves unrelated notices', () => {
		const refusal = addToast('Refused', 'error');
		for (let outage = 0; outage < 3; outage++) {
			const cause = new NetworkError('/api/test', new TypeError('fetch'));
			const dismissed = addToast('Dismissed', 'error', cause);
			dismissToast(dismissed);
			reportResourceStreamReachable(false);
			addToast('Pick failed', 'error', cause);
			reportResourceStreamReachable(true);
			expect(get(toasts).map((toast) => toast.id)).toEqual([refusal]);
		}
	});
});
