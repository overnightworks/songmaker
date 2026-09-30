import {
	ALBUM_ART_EMPTY_INITIALS,
	ALBUM_ART_INITIAL_COUNT,
	DAY_LABEL_ADDED,
	DAY_LABEL_TODAY,
	DAY_LABEL_YESTERDAY,
	PLACE_KIND_PLAYLIST_LABEL,
	PLACE_LINE_SEPARATOR
} from '$lib/constants';

const DAY_MS = 86_400_000;
export const DAYS_NAMED_BY_WEEKDAY = 7;
export const DAY_LABEL_LOCALE = 'en-US';

export function formatTime(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${String(s).padStart(2, '0')}`;
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

export function songCountLabel(songCount: number): string {
	return pluralize(songCount, 'song');
}

/** A place tile's second line: a playlist says so first ("Playlist · 14 songs"), an album is just the detail. */
export function placeLine(kind: 'album' | 'playlist', detail: string): string {
	return kind === 'playlist'
		? `${PLACE_KIND_PLAYLIST_LABEL}${PLACE_LINE_SEPARATOR}${detail}`
		: detail;
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

/** The one letter that stands for a person: the first character of their name, by code point, upper-cased. */
export function accountInitial(username: string): string {
	return Array.from(username)[0]?.toUpperCase() ?? '';
}

function startOfLocalDay(moment: Date): number {
	return new Date(moment.getFullYear(), moment.getMonth(), moment.getDate()).getTime();
}

/**
 * Calendar days from `earlier` to `later` in the device's own time zone: 0 on
 * the same day, 1 for the day before. Rounding absorbs a daylight-saving day.
 */
export function localDaysBetween(earlier: Date, later: Date): number {
	return Math.round((startOfLocalDay(later) - startOfLocalDay(earlier)) / DAY_MS);
}

/** The 24-hour local clock every day label adds: "09:12". */
export function localClockTime(moment: Date): string {
	return moment.toLocaleTimeString(DAY_LABEL_LOCALE, {
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23'
	});
}

/** The short local weekday every day label names: "Thu". */
export function localWeekday(moment: Date): string {
	return moment.toLocaleDateString(DAY_LABEL_LOCALE, { weekday: 'short' });
}

// Day before month ("21 Sep") is composed by hand: the one locale that orders
// it so, en-GB, abbreviates September as "Sept".
function localDayAndMonth(moment: Date, now: Date): string {
	const dayAndMonth = `${moment.getDate()} ${moment.toLocaleDateString(DAY_LABEL_LOCALE, { month: 'short' })}`;
	return moment.getFullYear() === now.getFullYear()
		? dayAndMonth
		: `${dayAndMonth} ${moment.getFullYear()}`;
}

/** When a place was last worked in: "today 05:47", "yesterday 23:40", "Thu 20:31", "21 Sep". */
export function activityTimeLabel(activityAt: string, now: Date): string {
	const moment = new Date(activityAt);
	const daysAgo = localDaysBetween(moment, now);
	const clock = localClockTime(moment);
	if (daysAgo <= 0) return `${DAY_LABEL_TODAY} ${clock}`;
	if (daysAgo === 1) return `${DAY_LABEL_YESTERDAY} ${clock}`;
	if (daysAgo < DAYS_NAMED_BY_WEEKDAY) return `${localWeekday(moment)} ${clock}`;
	return localDayAndMonth(moment, now);
}

/** The day a place was made: "added 3 Aug", "added 3 Aug 2025". */
export function addedDayLabel(createdAt: string, now: Date): string {
	return `${DAY_LABEL_ADDED} ${localDayAndMonth(new Date(createdAt), now)}`;
}
