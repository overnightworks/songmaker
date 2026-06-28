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
