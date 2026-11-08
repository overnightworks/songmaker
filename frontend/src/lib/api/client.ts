import { apiFetch, type JobStatus } from './fetch';
import type { AlbumItem, LastFailedGenerationResult } from './types';

export { ApiError, type JobStatus } from './fetch';
export {
	fetchAlbums,
	createAlbum,
	updateAlbum,
	shareAlbum,
	unshareAlbum,
	deleteAlbum,
	restoreAlbum,
	archiveAlbum,
	unarchiveAlbum
} from './albums';
export { fetchLibraryPoolQueue } from './library';
export {
	fetchSongs,
	fetchSong,
	createSong,
	updateSong,
	fetchVersions,
	deleteVersion,
	deleteSong,
	restoreSong,
	renameSong,
	shareSong,
	unshareSong,
	uploadSongCover,
	deleteSongCover
} from './songs';
export {
	generateSong,
	repaintGeneration,
	coverGeneration,
	rateGeneration,
	scoreGeneration,
	deleteGeneration,
	bulkDeleteGenerations,
	pickGeneration,
	unpickGeneration,
	keepGeneration,
	unkeepGeneration,
	unarchiveGeneration,
	shareGeneration,
	unshareGeneration
} from './generations';
export { uploadReference } from './references';
export { fetchJob, cancelJob } from './jobs';
export {
	fetchPlaylists,
	createPlaylist,
	fetchPlaylist,
	updatePlaylist,
	deletePlaylistApi,
	addGenerationToPlaylist,
	addSongToPlaylist,
	addAlbumToPlaylist,
	removeFromPlaylist,
	reorderPlaylistEntry,
	sharePlaylist,
	unsharePlaylist,
	uploadPlaylistCover,
	deletePlaylistCover
} from './playlists';
export { fetchMe } from './auth';

export {
	streamCoWriterTurn,
	fetchConversations,
	fetchConversationMessages,
	startNewConversation,
	deleteConversation
} from './conversations';
export type { CoWriterStreamEvent } from './conversations';
export { fetchMemory, saveUserMemory, saveSongMemory, saveAlbumMemory } from './memory';
export {
	fetchGenerationDefaults,
	updateGenerationDefaults,
	fetchActiveModels,
	fetchAllModels,
	toggleModel,
	fetchCowriterSettings,
	updateCowriterSettings,
	fetchBuiltinDefaults,
	fetchDefaultConfig,
	updateDefaultConfig,
	fetchPresets,
	createPreset,
	updatePreset,
	deletePresetApi,
	setPresetDefault,
	fetchRateLimits,
	updateRateLimits
} from './settings';
export {
	fetchAdminVoices,
	listWorkers,
	getRegistry,
	loadModelOnWorker,
	evictModelOnWorker,
	downloadModel,
	restartWorker,
	pinModelOnWorker,
	unpinModelOnWorker,
	previewGenerationRetention,
	runGenerationRetention
} from './admin';
export { addLoraSample, patchLoraSample, deleteLoraSample } from './loras';
export type { AvailableModel, GenerationRetentionReport } from './types';

export async function uploadAlbumCover(albumId: string, file: File): Promise<AlbumItem> {
	const form = new FormData();
	form.append('file', file);
	return apiFetch<AlbumItem>(`/api/albums/${albumId}/cover`, { method: 'POST', body: form });
}

export async function deleteAlbumCover(albumId: string): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}/cover`, { method: 'DELETE' });
}

export async function fetchLastFailedGeneration(
	songId: string
): Promise<LastFailedGenerationResult> {
	return apiFetch<LastFailedGenerationResult>(`/api/songs/${songId}/last-failed-generation`);
}

export async function fetchActiveGeneration(songId: string): Promise<JobStatus | null> {
	return apiFetch<JobStatus | null>(`/api/songs/${songId}/active-generation`);
}
