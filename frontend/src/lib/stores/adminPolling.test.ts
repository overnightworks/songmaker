import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { createPollingStore } from './adminPolling';
import { reportResourceStreamReachable, resetConnectivityForTests } from './connectivity';

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	resetConnectivityForTests();
	vi.useRealTimers();
});

describe('createPollingStore', () => {
	it('fires fetcher immediately on start, then on interval', async () => {
		const fetcher = vi.fn().mockResolvedValue({ value: 1 });
		const store = createPollingStore(fetcher, 1000, { isHidden: () => false });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
		expect(get(store.data)).toEqual({ value: 1 });

		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(2);

		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(3);
		store.stop();
	});

	it('skips fetch when isHidden returns true', async () => {
		let hidden = false;
		const fetcher = vi.fn().mockResolvedValue('ok');
		const store = createPollingStore(fetcher, 1000, { isHidden: () => hidden });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);

		hidden = true;
		await vi.advanceTimersByTimeAsync(3000);
		expect(fetcher).toHaveBeenCalledTimes(1);

		hidden = false;
		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(2);
		store.stop();
	});

	it('stop clears interval and stops further fetches', async () => {
		const fetcher = vi.fn().mockResolvedValue('x');
		const store = createPollingStore(fetcher, 500, { isHidden: () => false });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
		store.stop();
		await vi.advanceTimersByTimeAsync(5000);
		expect(fetcher).toHaveBeenCalledTimes(1);
	});

	it('records error and stops after maxErrors consecutive failures', async () => {
		const fetcher = vi.fn().mockRejectedValue(new Error('boom'));
		const store = createPollingStore(fetcher, 100, { isHidden: () => false, maxErrors: 3 });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(100);
		await vi.advanceTimersByTimeAsync(100);
		expect(fetcher).toHaveBeenCalledTimes(3);
		expect(get(store.error)?.message).toBe('boom');

		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(3);
	});

	it('resets consecutive error counter on success', async () => {
		const fetcher = vi
			.fn()
			.mockRejectedValueOnce(new Error('e1'))
			.mockRejectedValueOnce(new Error('e2'))
			.mockResolvedValueOnce('ok')
			.mockRejectedValue(new Error('e3'));
		const store = createPollingStore(fetcher, 100, { isHidden: () => false, maxErrors: 3 });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(100);
		await vi.advanceTimersByTimeAsync(100);
		expect(get(store.data)).toBe('ok');
		expect(get(store.error)).toBeNull();

		await vi.advanceTimersByTimeAsync(100);
		await vi.advanceTimersByTimeAsync(100);
		expect(fetcher).toHaveBeenCalledTimes(5);
		expect(get(store.error)?.message).toBe('e3');
		store.stop();
	});

	it('refresh triggers an immediate fetch', async () => {
		const fetcher = vi.fn().mockResolvedValue('x');
		const store = createPollingStore(fetcher, 10000, { isHidden: () => false });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
		await store.refresh();
		expect(fetcher).toHaveBeenCalledTimes(2);
		store.stop();
	});

	it('start is idempotent — calling twice does not double fetches', async () => {
		const fetcher = vi.fn().mockResolvedValue('x');
		const store = createPollingStore(fetcher, 1000, { isHidden: () => false });
		store.start();
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(2);
		store.stop();
	});

	it('visibilitychange listener triggers immediate fetch on regain', async () => {
		let hidden = true;
		const fetcher = vi.fn().mockResolvedValue('x');
		const store = createPollingStore(fetcher, 10000, { isHidden: () => hidden });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(0);

		const originalDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden');
		Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
		hidden = false;
		document.dispatchEvent(new Event('visibilitychange'));
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);

		if (originalDescriptor) {
			Object.defineProperty(Document.prototype, 'hidden', originalDescriptor);
		}
		store.stop();
	});

	it('stop removes visibilitychange listener', async () => {
		const fetcher = vi.fn().mockResolvedValue('x');
		const store = createPollingStore(fetcher, 10000, { isHidden: () => false });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
		store.stop();

		document.dispatchEvent(new Event('visibilitychange'));
		await vi.advanceTimersByTimeAsync(0);
		expect(fetcher).toHaveBeenCalledTimes(1);
	});

	it('polls again by itself once the connection is back after its failures stopped it', async () => {
		const fetcher = vi.fn().mockRejectedValue(new Error('offline'));
		const store = createPollingStore(fetcher, 1000, { isHidden: () => false, maxErrors: 2 });
		store.start();
		reportResourceStreamReachable(false);
		await vi.advanceTimersByTimeAsync(5000);
		expect(fetcher).toHaveBeenCalledTimes(2);

		fetcher.mockResolvedValue('back');
		reportResourceStreamReachable(true);
		await vi.advanceTimersByTimeAsync(1000);

		expect(get(store.data)).toBe('back');
		expect(fetcher).toHaveBeenCalledTimes(4);
		store.stop();
	});

	it('once stopped by its caller, stays stopped when the connection comes back', async () => {
		const fetcher = vi.fn().mockResolvedValue('ok');
		const store = createPollingStore(fetcher, 1000, { isHidden: () => false });
		store.start();
		await vi.advanceTimersByTimeAsync(0);
		store.stop();

		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		await vi.advanceTimersByTimeAsync(3000);

		expect(fetcher).toHaveBeenCalledTimes(1);
	});
});
