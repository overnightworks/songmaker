import { deleteSong, renameSong, restoreSong, shareSong, unshareSong } from '#lib/api/client.ts';
import { describeFailure } from '#lib/api/fetch.ts';
import type { ShareResult } from '#lib/api/types.ts';
import { addSongsToList, removeSongFromList, updateSongInList } from '#lib/stores/libraryData.ts';
import { addSongToPlaylist } from '#lib/stores/playlists.ts';
import { addToast, addUndoToast } from '#lib/stores/toast.ts';
import { pageText } from '#lib/utils/page-words.ts';

// The one owner of what a song's menu does to the song (rename, share, add to a playlist, delete
// with undo), shared by the editor and the album's song rows. Each action names its song, so the
// open song is never assumed.

const SONG_UNSHARED = { is_shared: false, share_slug: null, share_url: null };

/** Renames the song and says so; a refusal toasts and throws, so the title field stays open. */
export async function renameSongTo(songId: string, title: string): Promise<void> {
	try {
		const updated = await renameSong(songId, title);
		updateSongInList(songId, () => updated);
		addToast(pageText('songPage.renamed'), 'success');
	} catch (err) {
		addToast(describeFailure(err, pageText('songPage.renameFailed')), 'error');
		throw err;
	}
}

export async function enableSongSharing(songId: string): Promise<ShareResult> {
	const result = await shareSong(songId);
	const { share_slug, share_url } = result;
	updateSongInList(songId, (song) => ({ ...song, is_shared: true, share_slug, share_url }));
	return result;
}

export async function disableSongSharing(songId: string): Promise<void> {
	await unshareSong(songId);
	updateSongInList(songId, (song) => ({ ...song, ...SONG_UNSHARED }));
}

export async function addSongToPlaylistWithToast(
	songId: string,
	playlistId: string
): Promise<void> {
	try {
		await addSongToPlaylist(playlistId, songId);
		addToast(pageText('songPage.addedToPlaylist'), 'success');
	} catch (err) {
		addToast(describeFailure(err, pageText('songPage.addToPlaylistFailed')), 'error');
	}
}

/** Deletes the song and offers an undo; `ondeleted` runs once it is gone, before the offer. */
export async function deleteSongWithUndo(songId: string, ondeleted?: () => void): Promise<void> {
	try {
		await deleteSong(songId);
		removeSongFromList(songId);
		ondeleted?.();
		addUndoToast(pageText('songPage.deleted'), {
			label: pageText('songPage.undo'),
			handler: () => restoreDeletedSong(songId)
		});
	} catch (err) {
		addToast(describeFailure(err, pageText('songPage.deleteFailed')), 'error');
	}
}

async function restoreDeletedSong(songId: string): Promise<void> {
	try {
		const restored = await restoreSong(songId);
		addSongsToList([restored]);
		addToast(pageText('songPage.restored'), 'success');
	} catch (err) {
		addToast(describeFailure(err, pageText('songPage.restoreFailed')), 'error');
	}
}
