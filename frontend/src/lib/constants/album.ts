export const ALBUM_NO_SONGS = 'No songs yet.';
export const ALBUM_ART_EMPTY_INITIALS = '?';
export const ALBUM_ART_INITIAL_COUNT = 2;
export const ALBUM_COVER_ACCEPT = 'image/jpeg,image/png';
export const ALBUM_COVER_ALT_TYPE = 'Album';
export const ALBUM_COVER_UPLOAD_LABEL = 'Upload…';
export const ALBUM_COVER_ADD_LABEL = 'Add cover';
export const ALBUM_COVER_EDIT_LABEL = 'Edit cover';
export const ALBUM_COVER_EDITING_LABEL = 'Cover editing';
export const ALBUM_COVER_EDITING_CLOSE_LABEL = 'Close cover editing';
export const ALBUM_COVER_EDITING_UPLOAD_LABEL = 'Upload';
export const ALBUM_COVER_SUGGEST_LABEL = 'Suggest';
export const ALBUM_COVER_SUGGEST_ANOTHER_LABEL = 'Suggest another';
export const ALBUM_COVER_SUGGESTION_USE_LABEL = 'Use';
export const ALBUM_COVER_EDITING_REMOVE_LABEL = 'Remove';
export const ALBUM_COVER_PREVIOUS_SUGGESTION_LABEL = 'Previous suggestion';
export const ALBUM_COVER_NEXT_SUGGESTION_LABEL = 'Next suggestion';
export const ALBUM_COVER_SUGGESTIONS_LOADING = 'Loading cover suggestion…';
export const ALBUM_COVER_SUGGESTING_LABEL = 'Making a cover';
export const ALBUM_COVER_SUGGESTION_FAILED_TITLE = 'Couldn’t make a cover suggestion';
export const ALBUM_COVER_SUGGESTION_FAILED_FALLBACK = 'The cover suggestion failed. Try again.';
// Nothing retries a throttled Suggest, so the fallback asks the person to.
export const ALBUM_COVER_THROTTLED_FALLBACK =
	'Too many requests right now. Press Suggest again in a moment.';
export const ALBUM_COVER_SUGGESTIONS_RETRY_LABEL = 'Try again';
// A sideways drag on the cover this far, and more sideways than up or down,
// shows the neighbouring suggestion; anything less is a tap or a scroll.
export const ALBUM_COVER_SWIPE_TRAVEL_PX = 40;
export const ALBUM_DETAILS_CLOSE_LABEL = 'Close edit details';
export const ALBUM_DETAILS_SAVE_LABEL = 'Save';
export const ALBUM_DETAILS_TITLE_REQUIRED = 'Title cannot be empty';
export const ALBUM_DETAILS_SAVED = 'Details saved';
export const ALBUM_DETAILS_SAVE_FAILED = 'Saving the details failed';
export const ALBUM_SUBTITLE_LABEL = 'Subtitle';
export const ALBUM_SUBTITLE_MAX_LENGTH = 400;
export const ALBUM_YEAR_LABEL = 'Year';
export const ALBUM_YEAR_MIN = 1900;
export const ALBUM_YEAR_MAX = 2100;
export const ALBUM_YEAR_MAX_LENGTH = String(ALBUM_YEAR_MAX).length;
export const PLACE_LINE_SEPARATOR = ' · ';

export function albumCoverSuggestionAlt(title: string): string {
	return `Cover suggestion for ${title}`;
}

export function albumCoverSuggestionPosition(shown: number, count: number): string {
	return `${shown} / ${count}`;
}

export function albumCoverStageLabel(shown: number, count: number): string {
	return `Cover suggestion ${shown} of ${count}`;
}
