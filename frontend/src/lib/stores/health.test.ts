import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

const mockFetchHealth = vi.fn();
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
		mockFetchHealth.mockResolvedValue({
			status: 'ok',
			queue_depth_cap_reached: false,
			music_queue_depth: 0,
			scoring_queue_depth: 0,
			acestep_workers_online: 1,
			acestep_workers_total: 1
		});

		const { health, startHealthPolling, stopHealthPolling } = await import('./health');
		startHealthPolling();
		await vi.advanceTimersByTimeAsync(0);
		expect(mockFetchHealth).toHaveBeenCalled();
		expect(get(health)?.queue_depth_cap_reached).toBe(false);
		stopHealthPolling();
	});
});
