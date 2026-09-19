import { fetchHealth } from '$lib/api/client';
import type { HealthResponse } from '$lib/api/types';
import { createPollingStore } from './adminPolling';

const HEALTH_POLL_INTERVAL_MS = 15_000;

const store = createPollingStore<HealthResponse>(fetchHealth, HEALTH_POLL_INTERVAL_MS);

export const health = store.data;
export const startHealthPolling = store.start;
export const stopHealthPolling = store.stop;
