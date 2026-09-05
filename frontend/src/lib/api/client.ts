import { apiFetch } from './fetch';
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
	cleanupAlbum,
	createAlbumCoverSuggestions,
	fetchAlbumCoverSuggestions,
	selectAlbumCoverSuggestion,
	discardAlbumCoverSuggestions
} from './albums';
export {
	fetchLibraryPoolQueue,
	fetchShares,
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
	moveSong,
	renameSong,
	shareSong,
	unshareSong,
	cleanupSong,
	uploadSongCover,
	deleteSongCover
} from './songs';
export {
	generateSong,
	repaintGeneration,
	coverGeneration,
	type ReferenceAudioResult,
	uploadReferenceAudio,
	rateGeneration,
	scoreGeneration,
	deleteGeneration,
	type BulkDeleteResult,
	bulkDeleteGenerations,
	pickGeneration,
	unpickGeneration,
	keepGeneration,
	unkeepGeneration,
	unarchiveGeneration,
	shareGeneration,
	unshareGeneration,
	remasterGeneration
} from './generations';
export { fetchJob, cancelJob } from './jobs';
export { fetchHealth, type HealthSummary } from './health';
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
export {
	createQueueStreamSnapshot,
	createLibraryQueueStreamSnapshot,
	fetchSharedAlbumStream,
	fetchSharedPlaylistStream
} from './queue-streams';
export { checkSetupRequired, setupAdmin, login, logout, fetchMe, changePassword } from './auth';

export {
	streamCoWriterTurn,
	fetchConversations,
	fetchConversationMessages,
	startNewConversation,
	deleteConversation
} from './conversations';
export type { CoWriterStreamEvent, CoWriterTurnRequest } from './conversations';
export { fetchMemory, saveUserMemory, saveSongMemory, saveAlbumMemory } from './memory';
export {
	fetchCapabilities,
	fetchGenerationDefaults,
	updateGenerationDefaults,
	type ModelCapabilities,
	type AvailableModel,
	fetchActiveModels,
	fetchAllModels,
	toggleModel,
	fetchCowriterSettings,
	updateCowriterSettings,
	fetchJudgeSettings,
	updateJudgeSettings,
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
	updateRateLimits,
	fetchUserRateLimits,
	updateUserRateLimits,
	deleteUserRateLimits
} from './settings';
export {
	fetchUsers,
	fetchAdminVoices,
	createUser,
	updateUser,
	deactivateUser,
	hardDeleteUser,
	fetchSessions,
	forceLogout,
	fetchLoginAttempts,
	listWorkers,
	getRegistry,
	loadModelOnWorker,
	evictModelOnWorker,
	downloadModel,
	restartWorker,
	pinModelOnWorker,
	unpinModelOnWorker,
	previewGenerationRetention,
	runGenerationRetention,
	type GenerationRetentionReport
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
	listOwnPlayableTakes,
	type LoraSamplePatch
} from './loras';

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
