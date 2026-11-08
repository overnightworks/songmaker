export const MODELS_TASK_COWRITER_LABEL = 'Co-Writer';
export const MODELS_TASK_COVER_LABEL = 'Cover';
export const MODELS_COLUMN_TASK_LABEL = 'Task';
export const MODELS_COLUMN_PROVIDER_LABEL = 'Provider';
export const MODELS_COLUMN_ROUTE_LABEL = 'Route';
export const MODELS_COLUMN_MODEL_LABEL = 'Model';
export const MODELS_COLUMN_STATUS_LABEL = 'Status';
export const MODELS_SET_BY_AGENT_FILE_LABEL = 'Set by the agent file';
export const MODELS_ROUTE_GATEWAY_LABEL = 'Gateway';
export const MODELS_SAVED_LABEL = 'Saved.';
export const MODELS_RETRY_LABEL = 'Retry';
export const MODELS_ADVANCED_LABEL = 'Advanced';
export const MODELS_HISTORY_TAIL_LABEL = 'History tail (tokens)';
export const MODELS_SAVE_FAILED_FALLBACK = 'The server rejected the change.';
export const MODELS_LOAD_ERROR = 'Failed to load models';

const MODELS_LOADING_LABEL = 'Loading…';
const MODELS_UNAVAILABLE_LABEL = 'Unavailable';
export const modelsRowStatus = (loadFailure: string | null): string =>
	loadFailure ? MODELS_UNAVAILABLE_LABEL : MODELS_LOADING_LABEL;

export const MODELS_HEADING = 'Models';
