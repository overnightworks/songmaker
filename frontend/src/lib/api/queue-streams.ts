import type {
	LibraryQueueStreamRequest,
	QueueStreamManifest,
	QueueStreamTrackRequest
} from './types';
import { apiFetch } from './fetch';

// A cold queue-stream build concatenates every track server-side and can take
// well over the default API timeout while generation workers hold the box; a
// patient budget here is the difference between one slow success and five
// user-facing failures.
const STREAM_BUILD_TIMEOUT_MS = 120_000;

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

export async function createLibraryQueueStreamSnapshot(
	startGenerationId: string | null,
	opts: { shuffle?: boolean; pool?: LibraryQueueStreamRequest['pool'] } = {}
): Promise<QueueStreamManifest> {
	const body: LibraryQueueStreamRequest = {
		start_generation_id: startGenerationId,
		shuffle: opts.shuffle ?? false,
		pool: opts.pool ?? 'mix'
	};
	return apiFetch<QueueStreamManifest>(
		'/api/queue-streams/library',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		},
		STREAM_BUILD_TIMEOUT_MS
	);
}

export async function fetchSharedPlaylistStream(slug: string): Promise<QueueStreamManifest> {
	const resp = await fetch(`/shared/playlist/${slug}/stream`, { method: 'POST' });
	if (!resp.ok) throw new Error('Failed to create shared playlist stream');
	return resp.json() as Promise<QueueStreamManifest>;
}

export async function fetchSharedAlbumStream(slug: string): Promise<QueueStreamManifest> {
	const resp = await fetch(`/shared/${slug}/stream`, { method: 'POST' });
	if (!resp.ok) throw new Error('Failed to create shared album stream');
	return resp.json() as Promise<QueueStreamManifest>;
}

export interface QueueStreamPinState {
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
