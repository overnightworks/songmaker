// The transport's play button is named after the state its click leaves:
// "Pause" while the listener asked for sound — playing, a take loading or a
// stalled one recovering, or one waiting for the network — "Retry" once it
// failed, otherwise "Play". A flow reads the name to tell a sounding take from a dead one.
export const TRANSPORT_PLAY_LABEL = 'Play';
export const TRANSPORT_PAUSE_LABEL = 'Pause';
export const TRANSPORT_RETRY_LABEL = 'Retry';

export type TransportLabel =
	typeof TRANSPORT_PLAY_LABEL | typeof TRANSPORT_PAUSE_LABEL | typeof TRANSPORT_RETRY_LABEL;

// A collection header's play circle names what it does to it by its kind:
// "Play album", "Pause playlist", "Retry album". Its action is the transport's
// own label, so the header tells the bar's story. Every surface that renders
// the header, and every flow that finds it by name, builds the label here.
export type CollectionPlayKind = 'album' | 'playlist' | 'song' | 'take';

export function collectionActionLabel(action: TransportLabel, kind: CollectionPlayKind): string {
	return `${action} ${kind}`;
}

// What the transport says once it gave up on a take while the network was
// gone: its return retries the take by itself, so no Retry press is asked for.
export const PLAYER_WAITING_FOR_NETWORK = 'Waiting for the network.';

// The seek line's accessible name, and the position it reads out as words
// rather than as a bare count of seconds.
export const SEEK_PLAYBACK_LABEL = 'Seek playback';
export function seekPositionLabel(position: string, length: string): string {
	return `${position} of ${length}`;
}
