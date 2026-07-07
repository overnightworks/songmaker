import type { QueueStreamManifest, QueueStreamTrackRequest } from './types';
import { apiFetch } from './fetch';

export async function createQueueStreamSnapshot(
	tracks: QueueStreamTrackRequest[]
): Promise<QueueStreamManifest> {
	return apiFetch<QueueStreamManifest>('/api/queue-streams', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ tracks })
	});
}

export async function createLibraryQueueStreamSnapshot(
	startGenerationId: string | null
): Promise<QueueStreamManifest> {
	return apiFetch<QueueStreamManifest>('/api/queue-streams/library', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ start_generation_id: startGenerationId })
	});
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
