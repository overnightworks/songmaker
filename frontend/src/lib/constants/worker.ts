export const WORKER_TRAINING_REMAINING_TEMPLATE = 'Training ({seconds}s remaining)';
export const WORKER_POOL_RESTART_LABEL = 'Restart worker…';
export const WORKER_POOL_RESTART_CONFIRM = 'Restart';
export const WORKER_POOL_RESTART_TITLE = 'Restart {id}?';
export const WORKER_POOL_RESTART_WARNING = 'Running takes will stop.';
export const WORKER_POOL_LAST_ERROR_LABEL = 'Last error';
export const WORKER_POOL_FULL_LOGS_LABEL = 'Full logs:';
export const WORKER_POOL_VRAM_OFFLINE = 'VRAM unavailable while the worker is offline.';
// Named when an admin panel's first read fails while no offline strip says why.
export const WORKER_POOL_LOAD_FAILED = 'Cannot reach the worker pool API.';
export const WORKER_POOL_REFRESH_FAILED = 'Worker pool not updating — retrying…';
export const WORKER_POOL_MODELS_LABEL = 'Models on this GPU';
export const WORKER_POOL_MODELS_LOADING_TEMPLATE = 'None yet — {mode} is loading.';
export const WORKER_POOL_MODELS_OFFLINE_LABEL = 'Unknown while the worker is offline.';
export const WORKER_POOL_NO_MODEL_LABEL = 'No model loaded';
export const WORKER_POOL_KEEP_LOADED_LABEL = 'Keep loaded';
export const WORKER_POOL_KEEP_LOADED_HINT = 'Keep loaded — never unloaded to make room';
export const WORKER_POOL_UNLOAD_LABEL = 'Unload';
export const WORKER_POOL_VRAM_LABEL = 'VRAM';
export const WORKER_POOL_VRAM_UNKNOWN = 'unknown';
export const WORKER_POOL_VRAM_ESTIMATE = 'est.';
export const WORKER_POOL_VRAM_FREE = 'GB free';
export const WORKER_POOL_VRAM_ESTIMATE_REASON =
	'No GPU reading — the sizes of the loaded models, not a measurement';
export const WORKER_POOL_VRAM_NO_HEARTBEAT = 'No heartbeat — nothing to read';
export const WORKER_POOL_VRAM_NO_TOTAL = 'Worker does not report total VRAM';
export const WORKER_POOL_VRAM_NO_FIELDS = 'Worker build does not report VRAM fields';
