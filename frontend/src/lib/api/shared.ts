import { apiFetch, isNotFound, PUBLIC_SHARE_PATH_PREFIX } from './fetch';
import type {
	SharedAlbumPayload,
	SharedGenerationPayload,
	SharedPlaylistPayload,
	SharedSongPayload
} from './types';

export type SharedCollectionKind = 'album' | 'playlist' | 'song' | 'take';

interface SharedPayloads {
	album: SharedAlbumPayload;
	playlist: SharedPlaylistPayload;
	song: SharedSongPayload;
	take: SharedGenerationPayload;
}

// Where each kind sits under /shared/ (sharing_api.py); an album sits at its root.
const KIND_SEGMENT: Record<SharedCollectionKind, string> = {
	album: '',
	playlist: 'playlist/',
	song: 'song/',
	take: 'gen/'
};

function sharedAddress(kind: SharedCollectionKind, slug: string): string {
	return `${PUBLIC_SHARE_PATH_PREFIX}${KIND_SEGMENT[kind]}${slug}`;
}

export function fetchSharedCollection<K extends SharedCollectionKind>(
	kind: K,
	slug: string
): Promise<SharedPayloads[K]> {
	return apiFetch<SharedPayloads[K]>(sharedAddress(kind, slug));
}

export type SharedCollectionFailure = 'missing' | 'error';

export function sharedCollectionFailure(err: unknown): SharedCollectionFailure {
	return isNotFound(err) ? 'missing' : 'error';
}
