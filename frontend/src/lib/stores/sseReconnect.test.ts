import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	SSE_IMMEDIATE_REOPEN_MIN_GAP_MS,
	SSE_RECONNECT_BACKOFF_FACTOR,
	SSE_RECONNECT_BASE_DELAY_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '$lib/constants';
import {
	ImmediateReopenGap,
	nextReconnectDelayMs,
	watchReconnectOpportunities
} from './sseReconnect';

function expectedRange(attempt: number): { min: number; max: number } {
	const exponential = SSE_RECONNECT_BASE_DELAY_MS * SSE_RECONNECT_BACKOFF_FACTOR ** (attempt - 1);
	const min = Math.min(exponential, SSE_RECONNECT_MAX_DELAY_MS);
	return { min, max: min * (1 + SSE_RECONNECT_JITTER_RATIO) };
}

describe('nextReconnectDelayMs', () => {
	it('never returns a delay shorter than the un-jittered value', () => {
		for (let attempt = 1; attempt <= 10; attempt++) {
			const { min } = expectedRange(attempt);
			expect(nextReconnectDelayMs(attempt)).toBeGreaterThanOrEqual(min);
		}
	});

	it('caps the delay once attempts exceed the ceiling', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const farAttempt = nextReconnectDelayMs(20);
		vi.restoreAllMocks();
		expect(farAttempt).toBe(SSE_RECONNECT_MAX_DELAY_MS);
	});

	it('never waits longer than 10 seconds, jitter included, at any attempt', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0.9999);
		const longest = Math.max(...[1, 2, 3, 4, 5, 10, 20].map(nextReconnectDelayMs));
		vi.restoreAllMocks();
		expect(longest).toBeLessThanOrEqual(10_000);
	});

	it('is monotonically non-decreasing at the jitter floor as attempts grow', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const delays = [1, 2, 3, 4, 5, 6].map((attempt) => nextReconnectDelayMs(attempt));
		vi.restoreAllMocks();
		for (let i = 1; i < delays.length; i++) {
			expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]);
		}
	});
});

function setVisibility(state: DocumentVisibilityState): void {
	Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
}

describe('watchReconnectOpportunities', () => {
	afterEach(() => setVisibility('visible'));

	it.each([
		{
			opportunity: 'the window regains focus',
			dispatch: () => window.dispatchEvent(new Event('focus'))
		},
		{
			opportunity: 'the network comes back',
			dispatch: () => window.dispatchEvent(new Event('online'))
		},
		{
			opportunity: 'the page becomes visible',
			dispatch: () => {
				setVisibility('visible');
				document.dispatchEvent(new Event('visibilitychange'));
			}
		}
	])('reconnects at once when $opportunity', ({ dispatch }) => {
		const reconnectNow = vi.fn();
		const stop = watchReconnectOpportunities(reconnectNow);
		dispatch();
		stop();
		expect(reconnectNow).toHaveBeenCalledOnce();
	});

	it('reopens at most once per minimum gap however often the musician switches back', () => {
		vi.useFakeTimers();
		const reconnectNow = vi.fn();
		const stop = watchReconnectOpportunities(reconnectNow);
		const switchesBack = 20;
		const switchInterval = 150;
		for (let i = 0; i < switchesBack; i++) {
			window.dispatchEvent(new Event('focus'));
			vi.advanceTimersByTime(switchInterval);
		}
		stop();
		vi.useRealTimers();

		const window3s = switchesBack * switchInterval;
		expect(reconnectNow).toHaveBeenCalledTimes(
			Math.ceil(window3s / SSE_IMMEDIATE_REOPEN_MIN_GAP_MS)
		);
	});

	it('shares one gap between the watcher and a stream reopening on its own', () => {
		vi.useFakeTimers();
		const gap = new ImmediateReopenGap();
		const reconnectNow = vi.fn();
		const stop = watchReconnectOpportunities(reconnectNow, gap);
		gap.run(reconnectNow);
		window.dispatchEvent(new Event('online'));
		vi.advanceTimersByTime(SSE_IMMEDIATE_REOPEN_MIN_GAP_MS);
		window.dispatchEvent(new Event('online'));
		stop();
		vi.useRealTimers();

		expect(reconnectNow).toHaveBeenCalledTimes(2);
	});

	it('waits while the page is hidden and after watching stopped', () => {
		const reconnectNow = vi.fn();
		const stop = watchReconnectOpportunities(reconnectNow);
		setVisibility('hidden');
		document.dispatchEvent(new Event('visibilitychange'));
		stop();
		window.dispatchEvent(new Event('online'));
		window.dispatchEvent(new Event('focus'));
		expect(reconnectNow).not.toHaveBeenCalled();
	});
});
