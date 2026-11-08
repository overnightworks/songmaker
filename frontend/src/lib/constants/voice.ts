export const VOICE_PICKER_LABEL = 'Your Voice';
export const VOICE_PICKER_NONE_LABEL = 'None';
export const VOICE_PICKER_CREATE_LABEL = 'Create a voice';
export const VOICE_PICKER_NOT_AVAILABLE_FOR_MODEL = 'not available for this model';
export const VOICE_PICKER_DELETED_LABEL = 'voice deleted';

export function voicePickerMobileLabel(modelMode: string): string {
	return `${VOICE_PICKER_LABEL} · ${modelMode} model`;
}

export const ADMIN_VOICES_TAB_LABEL = 'Voices';
export const ADMIN_VOICES_HEADING = 'Voice operations';
export const ADMIN_VOICES_LOADING = 'Loading voices...';
export const ADMIN_VOICES_EMPTY = 'No voices have been created.';
export const VOICES_LOAD_FAILED = 'Failed to load voices';
export const ADMIN_VOICES_NAME_LABEL = 'Voice';
export const ADMIN_VOICES_OWNER_LABEL = 'Owner';
export const ADMIN_VOICES_STATUS_LABEL = 'Status';
