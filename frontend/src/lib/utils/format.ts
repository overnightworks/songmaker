import { ALBUM_ART_EMPTY_INITIALS, ALBUM_ART_INITIAL_COUNT } from '$lib/constants';

export function formatTime(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${String(s).padStart(2, '0')}`;
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

export function albumSummaryLabel(songCount: number, pickCount: number): string {
	return `${pluralize(songCount, 'song')} · ${pluralize(pickCount, 'pick')}`;
}

export function playlistSummaryLabel(entryCount: number): string {
	return pluralize(entryCount, 'track');
}

export function titleInitials(title: string): string {
	const trimmed = title.trim();
	if (!trimmed) return ALBUM_ART_EMPTY_INITIALS;
	const words = trimmed.split(/\s+/);
	if (words.length === 1) {
		const letters = Array.from(words[0]).slice(0, ALBUM_ART_INITIAL_COUNT).join('');
		return letters.toUpperCase() || ALBUM_ART_EMPTY_INITIALS;
	}
	const first = Array.from(words[0])[0];
	const second = Array.from(words[1])[0];
	if (!first) return ALBUM_ART_EMPTY_INITIALS;
	return `${first}${second ?? ''}`.toUpperCase();
}
