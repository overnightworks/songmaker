import { makeHealthResponse } from '$lib/test-utils/factories';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import type { HealthResponse } from '$lib/api/types';

const mockFetchHealth = vi.fn<() => Promise<HealthResponse>>();
vi.mock('$lib/api/client', () => ({
	fetchHealth: () => mockFetchHealth()
}));

beforeEach(() => {
	vi.useFakeTimers();
	mockFetchHealth.mockReset();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('health store', () => {
	it('start triggers a fetch and exposes the result', async () => {
		const response = makeHealthResponse();
		mockFetchHealth.mockResolvedValue(response);

		const { health, startHealthPolling, stopHealthPolling } = await import('./health');
		startHealthPolling();
		await vi.advanceTimersByTimeAsync(0);
		expect(get(health)).toEqual(response);
		stopHealthPolling();
	});
});
