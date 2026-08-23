// Transport only: the alignment itself lives in the pure `alignLyricsToCues`
// (#45/#142), which a 56-line take keeps busy for a few hundred milliseconds —
// long enough to freeze Now Playing when it runs on the main thread (#158).
// The protocol belongs to lyricsAlignment.ts, which owns this worker.
import type { AlignmentRequest, AlignmentResult } from '$lib/services/lyricsAlignment';
import { alignLyricsToCues } from './lyrics-align';

addEventListener('message', (event: MessageEvent<AlignmentRequest>) => {
	const { id, lyrics, cues } = event.data;
	postMessage({ id, lines: alignLyricsToCues(lyrics, cues) } satisfies AlignmentResult);
});
