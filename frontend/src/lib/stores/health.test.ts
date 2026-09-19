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
		const response: HealthResponse = {
			status: 'ok',
			music_worker: 'running',
			scoring_worker: 'running',
			db: 'ok',
			redis: 'ok',
			redis_session_cache_failures: 0,
			acestep: 'healthy',
			uptime_seconds: 60,
			claude_cli_tool_surface: 'ok',
			codex_image_sandbox_runtime: 'ready',
			background_loops: {
				cover_runner: { state: 'ok', consecutive_failures: 0, last_error: null },
				session_sync: { state: 'ok', consecutive_failures: 0, last_error: null },
				resource_event_cleanup: { state: 'ok', consecutive_failures: 0, last_error: null },
				score_backfill: { state: 'ok', consecutive_failures: 0, last_error: null },
				stale_job_reaper: { state: 'ok', consecutive_failures: 0, last_error: null },
				provider_status_refresh: { state: 'ok', consecutive_failures: 0, last_error: null }
			},
			queue_depth_cap_reached: false,
			music_queue_depth: 0,
			scoring_queue_depth: 0,
			acestep_workers_online: 1,
			acestep_workers_total: 1
		};
		mockFetchHealth.mockResolvedValue(response);

		const { health, startHealthPolling, stopHealthPolling } = await import('./health');
		startHealthPolling();
		await vi.advanceTimersByTimeAsync(0);
		expect(get(health)).toEqual(response);
		stopHealthPolling();
	});
});
