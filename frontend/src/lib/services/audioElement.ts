import { pageText } from '#lib/utils/page-words.ts';

// A deck whose playhead is this close to the end of what it holds, with
// nothing more on its way, has played its last take.
const END_OF_DECK_SLACK_SECONDS = 0.5;

export function bufferedUntil(el: HTMLAudioElement): number {
	const ranges = el.buffered;
	return ranges.length === 0 ? 0 : ranges.end(ranges.length - 1);
}

// The playhead stands at the end of what the element holds.
export function ranOutOfAudio(el: HTMLAudioElement): boolean {
	return bufferedUntil(el) - el.currentTime <= END_OF_DECK_SLACK_SECONDS;
}

// A lost network is never decoded here: where the owner's strip names it
// (#1039), the player adds no network wording of its own.
export function decodeMediaError(err: MediaError): string {
	switch (err.code) {
		case MediaError.MEDIA_ERR_ABORTED:
			return pageText('transport.aborted');
		case MediaError.MEDIA_ERR_DECODE:
			return pageText('transport.fileCorrupted');
		case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
			return pageText('transport.formatUnsupported');
		default:
			return pageText('transport.playbackFailed');
	}
}
