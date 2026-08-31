import { describe, expect, it, vi } from 'vitest';

import {
	SSE_RECONNECT_BACKOFF_FACTOR,
	SSE_RECONNECT_BASE_DELAY_MS,
	SSE_RECONNECT_JITTER_RATIO,
	SSE_RECONNECT_MAX_DELAY_MS
} from '$lib/constants';
import { nextReconnectDelayMs } from './sseReconnect';

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

	it('is monotonically non-decreasing at the jitter floor as attempts grow', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0);
		const delays = [1, 2, 3, 4, 5, 6].map((attempt) => nextReconnectDelayMs(attempt));
		vi.restoreAllMocks();
		for (let i = 1; i < delays.length; i++) {
			expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]);
		}
	});
});
