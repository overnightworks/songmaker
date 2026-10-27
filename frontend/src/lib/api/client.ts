import { apiFetch, type JobStatus } from './fetch';
import type { AlbumItem, LastFailedGenerationResult } from './types';

export { ApiError, type JobStatus } from './fetch';
export {
	fetchAlbum,
	fetchAlbums,
	createAlbum,
	updateAlbum,
	shareAlbum,
	unshareAlbum,
	deleteAlbum,
	restoreAlbum,
	archiveAlbum,
	unarchiveAlbum,
	createAlbumCoverSuggestions,
	fetchAlbumCoverSuggestions,
	selectAlbumCoverSuggestion,
	discardAlbumCoverSuggestions
} from './albums';
export {
	fetchLibraryPoolQueue,
	searchLibrary,
	type LibrarySearchHit,
	type LibrarySearchResponse,
	type LibrarySort
} from './library';
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
	uploadReferenceAudio,
	rateGeneration,
	scoreGeneration,
	deleteGeneration,
	bulkDeleteGenerations,
	pickGeneration,
	unpickGeneration,
	keepGeneration,
	unkeepGeneration,
	shareGeneration,
	unshareGeneration
} from './generations';
export { fetchJob, cancelJob } from './jobs';
export { fetchHealth } from './health';
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
	fetchCapabilities,
	fetchGenerationDefaults,
	updateGenerationDefaults,
	fetchActiveModels,
	fetchAllModels,
	toggleModel,
	fetchCowriterOffer,
	fetchCowriterSettings,
	updateCowriterSettings,
	fetchJudgeSettings,
	updateJudgeSettings,
	fetchCoverSettings,
	updateCoverSettings,
	fetchProviderStatus,
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
export {
	listLoras,
	getLora,
	createLora,
	softDeleteLora,
	addLoraSample,
	addLoraSampleFromGeneration,
	patchLoraSample,
	deleteLoraSample,
	trainLora,
	listOwnPlayableTakes
} from './loras';
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
