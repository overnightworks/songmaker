export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const LORA_OWN_TAKES_LABEL = 'Your takes';
export const LORA_OWN_TAKES_LOADING = 'Loading your takes...';
export const LORA_OWN_TAKES_EMPTY = 'No playable takes yet.';
export const LORA_OWN_TAKES_LOAD_FAILED = 'Could not load takes';
export const LORA_OWN_TAKES_USE = 'Use as sample';
export const LORA_OWN_TAKES_CLOSE = 'Close takes';
export const LORA_OWN_TAKES_OPEN = 'Use a take';
export const LORA_TAKE_LABEL_PREFIX = 'Take';
export const LORA_SAMPLE_ADDING = 'Adding...';
export const LORA_SAMPLE_COPY_FAILED = 'Could not add take';
export const LORA_SAMPLE_UPLOAD_FAILED = 'Upload failed';
export const LORA_CREATE_FAILED = 'Could not create voice';
export const LORA_TRAINING_QUEUED_TOAST = 'Training queued';
export const LORA_TRAINING_STARTING = 'Starting...';
export const LORA_TRAINING_FAILED_LABEL = 'Training failed';
export const LORA_TRAINING_RETRY_LABEL = 'Train again';
export const LORA_TRAINING_START_FAILED = 'Training failed to start';
export const LORA_TRAINING_CANCEL_LABEL = 'Cancel';
export const LORA_TRAINING_CANCELLED = 'Training cancelled';
export const LORA_TRAINING_CANCEL_FAILED = 'Could not cancel training';
export const LORA_TRAINING_PROGRESS_LOAD_FAILED = 'Could not load training progress';
export const LORA_TRAINING_PROGRESS_LABEL = 'Training progress';
export const LORA_TRAINING_STATUS_LABEL = 'Training';
export const LORA_TRAINING_WAITING_LABEL = 'Waiting';
export const LORA_TRAINING_WAITING_DEFAULT_REASON = 'Waiting for the worker.';
const LORA_TRAINING_QUEUE_POSITION_TEMPLATE = 'Position {position} in the queue';
const LORA_TRAINING_EPOCH_TEMPLATE = 'Epoch {current} of {total}';
export const LORA_TRAINING_REMAINING_CALCULATING = 'Calculating remaining time...';
const LORA_TRAINING_REMAINING_TEMPLATE = '~ {time} remaining';

export function loraTrainingQueuePositionLabel(position: number): string {
	return LORA_TRAINING_QUEUE_POSITION_TEMPLATE.replace('{position}', String(position));
}

export function loraTrainingEpochLabel(current: number, total: number): string {
	return LORA_TRAINING_EPOCH_TEMPLATE.replace('{current}', String(current)).replace(
		'{total}',
		String(total)
	);
}

export function loraTrainingRemainingLabel(seconds: number): string {
	const totalMinutes = Math.max(1, Math.ceil(seconds / 60));
	const hours = Math.floor(totalMinutes / 60);
	const minutes = totalMinutes % 60;
	const time = hours > 0 ? `${hours}h ${minutes}m` : `${Math.max(minutes, 1)}m`;
	return LORA_TRAINING_REMAINING_TEMPLATE.replace('{time}', time);
}
