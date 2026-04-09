import { fetchHealth, type HealthSummary } from '$lib/api/client';
import { createPollingStore } from './adminPolling';

const HEALTH_POLL_INTERVAL_MS = 15_000;

const store = createPollingStore<HealthSummary>(fetchHealth, HEALTH_POLL_INTERVAL_MS);

export const health = store.data;
export const startHealthPolling = store.start;
export const stopHealthPolling = store.stop;
export const refreshHealth = store.refresh;
