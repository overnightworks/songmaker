import type { RepaintMode } from '$lib/stores/recipe';
import { formatTime } from '$lib/utils/format';

// The task card under a take (Repaint, Cover): copy not shared with the recipe.
export const TAKE_TASK_CLOSE_LABEL = 'Close';
export const TAKE_TASK_CLOSE_TITLE = 'Close — nothing changes';
export const TAKE_TASK_RANGE_LABEL = 'Range';
export const TAKE_TASK_REPAINT_STRENGTH_LABEL = 'Repaint strength';
export const TAKE_TASK_COVER_STRENGTH_LABEL = 'Cover strength';
export const TAKE_TASK_NOISE_LABEL = 'Noise';
export const TAKE_TASK_NOISE_CAPTION = 'more noise, more surprise';
export const TAKE_TASK_REPAINT_MODES: { value: RepaintMode; label: string }[] = [
	{ value: 'conservative', label: 'Conservative' },
	{ value: 'balanced', label: 'Balanced' },
	{ value: 'aggressive', label: 'Aggressive' }
];
export const TAKE_TASK_PROMPT_HINT =
	"Paints using the lyrics and style currently in the editor — not the source take's own.";
export const TAKE_TASK_HEADER_GENERATE_NOTE = '· the header Generate stays what it is';
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
