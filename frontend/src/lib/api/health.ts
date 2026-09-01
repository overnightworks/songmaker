import { apiFetch } from './fetch';

export interface HealthSummary {
	status: string;
	queue_depth_cap_reached: boolean;
	music_queue_depth: number;
	scoring_queue_depth: number;
	acestep_workers_online: number;
	acestep_workers_total: number;
}

export async function fetchHealth(): Promise<HealthSummary> {
	return apiFetch<HealthSummary>('/health');
}
