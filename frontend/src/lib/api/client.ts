export { ApiError, type JobStatus } from './fetch';
export {
	fetchAlbums,
	createAlbum,
	shareAlbum,
	unshareAlbum,
	deleteAlbum,
	cleanupAlbum
} from './albums';
export {
	fetchSongs,
	fetchSong,
	createSong,
	updateSong,
	fetchVersions,
	deleteVersion,
	deleteSong,
	moveSong,
	shareSong,
	unshareSong,
	cleanupSong
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
	shareGeneration,
	unshareGeneration
} from './generations';
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
	unsharePlaylist
} from './playlists';
export { checkSetupRequired, setupAdmin, login, logout, fetchMe, changePassword } from './auth';
export { sendChatMessage, fetchChatHistory, clearChatHistory, fetchRecentChats } from './chat';
export {
	fetchCapabilities,
	fetchGenerationDefaults,
	updateGenerationDefaults,
	type ModelCapabilities,
	type AvailableModel,
	fetchActiveModels,
	fetchAllModels,
	toggleModel,
	type ClaudeModelsResponse,
	fetchClaudeModels,
	updateClaudeModels,
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
	createUser,
	updateUser,
	deactivateUser,
	hardDeleteUser,
	fetchSessions,
	forceLogout,
	fetchLoginAttempts,
	getAceStepStatus,
	reinitializeAceStep
} from './admin';
