export { ApiError, type JobStatus } from './fetch';
export {
	fetchAlbums,
	createAlbum,
	renameAlbum,
	shareAlbum,
	unshareAlbum,
	deleteAlbum,
	restoreAlbum,
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
	restoreSong,
	moveSong,
	renameSong,
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
	unsharePlaylist
} from './playlists';
export { checkSetupRequired, setupAdmin, login, logout, fetchMe, changePassword } from './auth';
export { sendChatMessage, fetchChatHistory, clearChatHistory, fetchRecentChats } from './chat';
export {
	streamCoWriterTurn,
	fetchConversations,
	fetchConversationMessages,
	startNewConversation,
	deleteConversation
} from './conversations';
export type { CoWriterStreamEvent } from './conversations';
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
