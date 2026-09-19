import { apiFetch } from './fetch';
import type { HealthResponse } from './types';

export async function fetchHealth(): Promise<HealthResponse> {
	return apiFetch<HealthResponse>('/health');
}
