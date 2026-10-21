import type { QueueStreamManifest, QueueStreamTrackRequest } from './types';
import { apiFetch } from './fetch';

// A cold queue-stream build concatenates every track server-side and can take
// well over the default API timeout while generation workers hold the box; a
// patient budget here is the difference between one slow success and five
// user-facing failures.
export const STREAM_BUILD_TIMEOUT_MS = 120_000;

export async function createQueueStreamSnapshot(
	tracks: QueueStreamTrackRequest[]
): Promise<QueueStreamManifest> {
	return apiFetch<QueueStreamManifest>(
		'/api/queue-streams',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ tracks })
		},
		STREAM_BUILD_TIMEOUT_MS
	);
}

interface QueueStreamPinState {
	snapshot_id: string;
	pinned: boolean;
	pinned_at: string | null;
}

export async function pinQueueStream(snapshotId: string): Promise<QueueStreamPinState> {
	return apiFetch<QueueStreamPinState>(`/api/queue-streams/${snapshotId}/pin`, {
		method: 'POST'
	});
}

export async function unpinQueueStream(snapshotId: string): Promise<QueueStreamPinState> {
	return apiFetch<QueueStreamPinState>(`/api/queue-streams/${snapshotId}/pin`, {
		method: 'DELETE'
	});
}
