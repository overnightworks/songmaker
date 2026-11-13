import { makePlaylistEntry as entry } from '#lib/test-utils/factories.ts';
import type { PlaylistDetailItem } from '#lib/api/types.ts';
import { setOpenCollection } from '#lib/stores/collection.ts';
import { playlistDetailLoad, playlistList, selectedPlaylistDetail } from '#lib/stores/playlists.ts';

export function populatedPlaylistDefaults(): Partial<PlaylistDetailItem> {
	return {
		share_slug: null,
		entries: [entry({ song_title: 'Tide', album_title: 'Night Drive', mp3_path: 'tide.mp3' })]
	};
}

// The header prefers the lightweight playlist in playlistList and falls
// back to the detail once it matches the open id (see PlaylistDetailView.
// svelte) — this seeds both, the way navigation.openPlaylist does, so tests
// exercise the common (list populated) path. Tests for the fallback path
// seed only the detail.
export function openPlaylistDetail(d: PlaylistDetailItem): void {
	playlistList.set([
		{
			id: d.id,
			title: d.title,
			slug: d.slug,
			entry_count: d.entry_count,
			is_shared: d.is_shared,
			share_slug: d.share_slug,
			cover: d.cover,
			album_covers: d.album_covers,
			created_at: d.created_at
		}
	]);
	setOpenCollection({ kind: 'playlist', id: d.id });
	selectedPlaylistDetail.set(d);
	playlistDetailLoad.set({ status: 'ready', error: null });
}
