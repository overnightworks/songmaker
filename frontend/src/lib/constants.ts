export const APP_NAME = 'Hallucinai';

export const EXPIRY_WARN_DAYS = 3;

export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const QUEUE_STREAM_EMPTY_POOL_PREFIX = 'No playable takes in pool';

export const QUEUE_STREAM_UNPLAYABLE_START_DETAIL = 'Requested take is not playable';

export const QUEUE_TAKE_MISSING_TOAST = 'This take is not in the queue';

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const LIBRARY_SEARCH_PLACEHOLDER = 'Search albums and songs';
export const LIBRARY_SEARCH_EMPTY = 'No albums or songs match';
export const LIBRARY_BROWSE_EMPTY = 'No songs yet';
export const LIBRARY_SEARCH_LOADING = 'Searching…';
export const LIBRARY_SEARCH_ERROR = 'Search failed';
export const LIBRARY_RETRY_LABEL = 'Retry';
export const LIBRARY_LOAD_MORE = 'Load more';
export const LIBRARY_SEARCH_DEBOUNCE_MS = 200;
export const LIBRARY_ALBUM_PAGE_SIZE = 50;
export const LIBRARY_SONG_PAGE_SIZE = 200;
export const LIBRARY_SEARCH_PAGE_SIZE = 50;
