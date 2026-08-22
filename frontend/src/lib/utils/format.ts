import { ALBUM_ART_EMPTY_INITIALS, ALBUM_ART_INITIAL_COUNT } from '$lib/constants';

export function formatTime(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${String(s).padStart(2, '0')}`;
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
