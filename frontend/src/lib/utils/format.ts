import { ALBUM_ART_EMPTY_INITIALS, ALBUM_ART_INITIAL_COUNT } from '$lib/constants';

const DAY_MS = 86_400_000;
const ACTIVITY_DAYS_NAMED_BY_WEEKDAY = 7;
const ACTIVITY_LOCALE = 'en-US';
const ACTIVITY_TODAY = 'today';
const ACTIVITY_YESTERDAY = 'yesterday';

export function formatTime(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${String(s).padStart(2, '0')}`;
}

function pluralize(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function songCountLabel(songCount: number): string {
	return pluralize(songCount, 'song');
}

export function albumSummaryLabel(songCount: number, pickCount: number): string {
	return `${songCountLabel(songCount)} · ${pluralize(pickCount, 'pick')}`;
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

/** When a place was last worked in: "today 05:47", "yesterday 23:40", "Thu 20:31", "21 Sep". */
export function activityTimeLabel(activityAt: string, now: Date): string {
	const moment = new Date(activityAt);
	const daysAgo = localDaysBetween(moment, now);
	const clock = moment.toLocaleTimeString(ACTIVITY_LOCALE, {
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23'
	});
	if (daysAgo <= 0) return `${ACTIVITY_TODAY} ${clock}`;
	if (daysAgo === 1) return `${ACTIVITY_YESTERDAY} ${clock}`;
	if (daysAgo < ACTIVITY_DAYS_NAMED_BY_WEEKDAY) {
		return `${moment.toLocaleDateString(ACTIVITY_LOCALE, { weekday: 'short' })} ${clock}`;
	}
	// Day before month ("21 Sep") is composed by hand: the one locale that orders
	// it so, en-GB, abbreviates September as "Sept".
	const dayAndMonth = `${moment.getDate()} ${moment.toLocaleDateString(ACTIVITY_LOCALE, { month: 'short' })}`;
	return moment.getFullYear() === now.getFullYear()
		? dayAndMonth
		: `${dayAndMonth} ${moment.getFullYear()}`;
}
