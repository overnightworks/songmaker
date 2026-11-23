import { get } from 'svelte/store';
import { ApiError, describeFailure } from '#lib/api/fetch.ts';
import { libraryTakePool, type LibraryTakePool } from '#lib/stores/playbackSettings.ts';
import { pageText, type TextKey } from '#lib/utils/page-words.ts';
import type { Key } from '#lib/words/en.ts';

const POOL_QUEUE_FAILED_KEYS = {
	picks: 'player.picksQueueFailed',
	mix: 'player.keepsQueueFailed',
	all: 'player.allTakesQueueFailed'
} as const satisfies Record<LibraryTakePool, TextKey>;

const EMPTY_POOL_REFUSAL: Key = 'libraryQueueRefusal.emptyPool';
const UNPLAYABLE_START_REFUSAL: Key = 'libraryQueueRefusal.startUnplayable';

export function isEmptyPoolError(err: unknown): boolean {
	return err instanceof ApiError && err.refusal?.key === EMPTY_POOL_REFUSAL;
}

function isUnplayableStartError(err: unknown): boolean {
	return err instanceof ApiError && err.refusal?.key === UNPLAYABLE_START_REFUSAL;
}

// What a failed library queue start tells the listener.
export function libraryStreamFailureToast(err: unknown): string {
	if (isEmptyPoolError(err)) return pageText('player.nothingToPlay');
	const queueFailed = pageText(POOL_QUEUE_FAILED_KEYS[get(libraryTakePool)]);
	return isUnplayableStartError(err) ? describeFailure(err, queueFailed) : queueFailed;
}
