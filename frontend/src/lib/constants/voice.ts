export const VOICE_PICKER_LABEL = 'Your Voice';
export const VOICE_PICKER_NONE_LABEL = 'None';
export const VOICE_PICKER_CREATE_LABEL = 'Create a voice';
export const VOICE_PICKER_NOT_AVAILABLE_FOR_MODEL = 'not available for this model';
export const VOICE_PICKER_DELETED_LABEL = 'voice deleted';

export function voicePickerMobileLabel(modelMode: string): string {
	return `${VOICE_PICKER_LABEL} · ${modelMode} model`;
}
