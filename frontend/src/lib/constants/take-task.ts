import { formatTime } from '$lib/utils/format';

// The task card under a take (Repaint, Cover): copy not shared with the recipe.
export const TAKE_TASK_CLOSE_LABEL = 'Close';
export const TAKE_TASK_CLOSE_TITLE = 'Close — nothing changes';
export const TAKE_TASK_REPAINT_AMOUNT_LABEL = 'How much changes';
export const TAKE_TASK_COVER_FREE_LABEL = 'Free';
export const TAKE_TASK_COVER_STRICT_LABEL = 'Strict';

export function takeTaskCoverClosenessLabel(generationNumber: number): string {
	return `How close to take ${generationNumber}`;
}

export function takeTaskLandingLabel(versionNumber: number): string {
	return `New take in v${versionNumber}`;
}

export function takeTaskRepaintButtonLabel(
	label: string,
	startSeconds: number,
	endSeconds: number
): string {
	return `${label} ${formatTime(startSeconds)} – ${formatTime(endSeconds)}`;
}
