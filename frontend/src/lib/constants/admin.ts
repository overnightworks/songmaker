import type { AdminUserLoraItem } from '#lib/api/types.ts';
import type { TextKey } from '#lib/utils/page-words.ts';

export const ADMIN_WORKER_POOL_HREF = '/settings/users?tab=acestep';

/** The words of each voice status the admin Voices tab shows. */
export const ADMIN_VOICE_STATUS_TEXT_KEYS = {
	draft: 'adminPage.voiceStatusDraft',
	queued: 'adminPage.voiceStatusQueued',
	preprocessing: 'adminPage.voiceStatusPreprocessing',
	training: 'adminPage.voiceStatusTraining',
	exporting: 'adminPage.voiceStatusExporting',
	ready: 'adminPage.voiceStatusReady',
	failed: 'adminPage.voiceStatusFailed'
} as const satisfies Record<AdminUserLoraItem['status'], TextKey>;
