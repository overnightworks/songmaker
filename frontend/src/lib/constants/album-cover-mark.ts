// What the album's closed cover says about its cover suggestions.

/** What the closed cover shows for suggestions waiting to be used or discarded. */
export function albumCoverWaitingText(count: number): string {
	return `${count} waiting`;
}

const ALBUM_COVER_RUNNING_NAME_SUFFIX = 'making a suggestion';

/**
 * The closed cover's accessible name: the opening label plus what it carries.
 * The running time is left out so the name does not change every second.
 */
export function albumCoverMarkedLabel(
	label: string,
	mark: { running: boolean; waiting: number } | undefined
): string {
	if (mark?.running) return `${label} · ${ALBUM_COVER_RUNNING_NAME_SUFFIX}`;
	if (mark && mark.waiting > 0) return `${label} · ${albumCoverWaitingText(mark.waiting)}`;
	return label;
}
