import { DAY_LABEL_TODAY, DAY_LABEL_YESTERDAY } from '#lib/constants/day-label.ts';
import { ALBUM_ART_EMPTY_INITIALS, ALBUM_ART_INITIAL_COUNT } from '#lib/constants/album.ts';
import { pageLanguage } from './page-language.ts';
import { pageText } from './page-words.ts';

const DAY_MS = 86_400_000;
export const DAYS_NAMED_BY_WEEKDAY = 7;

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
	return moment.toLocaleTimeString(pageLanguage(), {
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23'
	});
}

/** The short local weekday every day label names: "Thu". */
export function localWeekday(moment: Date): string {
	return moment.toLocaleDateString(pageLanguage(), { weekday: 'short' });
}

// Day before month ("21 Sep") is composed by hand: the one locale that orders
// it so, en-GB, abbreviates September as "Sept".
function dayAndMonth(moment: Date): string {
	return `${moment.getDate()} ${moment.toLocaleDateString(pageLanguage(), { month: 'short' })}`;
}

export function localDayAndMonth(moment: Date, now: Date): string {
	return moment.getFullYear() === now.getFullYear()
		? dayAndMonth(moment)
		: `${dayAndMonth(moment)} ${moment.getFullYear()}`;
}

const RELEASE_TAG_DAY = /^v(\d{4})\.(\d{2})\.(\d{2})\.\d+$/;

/**
 * The calendar day a release tag names, "28 Oct 2026" for "v2026.10.28.4", or
 * null when the tag has no such day. The day is read as written, with no time
 * zone conversion.
 */
export function releaseDayLabel(tag: string): string | null {
	const match = RELEASE_TAG_DAY.exec(tag);
	if (!match) return null;
	const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
	const moment = new Date(year, month - 1, day);
	const isRealDay =
		moment.getFullYear() === year && moment.getMonth() === month - 1 && moment.getDate() === day;
	return isRealDay ? `${dayAndMonth(moment)} ${year}` : null;
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

/** A number with a fixed count of decimals and the page language's separators: "1,234.5". */
export function formatDecimal(value: number, fractionDigits: number): string {
	return value.toLocaleString(pageLanguage(), {
		minimumFractionDigits: fractionDigits,
		maximumFractionDigits: fractionDigits
	});
}

/** A fraction as a whole percent in the page language: 0.42 reads "42%". */
export function formatPercent(fraction: number): string {
	return fraction.toLocaleString(pageLanguage(), { style: 'percent', maximumFractionDigits: 0 });
}

/** Items as a unit list in the page language: English reads "2 takes, 1 version". */
export function formatList(items: readonly string[]): string {
	return new Intl.ListFormat(pageLanguage(), { type: 'unit', style: 'long' }).format(items);
}

/** Seconds as whole minutes rounded up, at least one: "~ 9m remaining" or "~ 2h 0m remaining". */
export function formatRemainingTime(seconds: number): string {
	const totalMinutes = Math.max(1, Math.ceil(seconds / 60));
	const hours = formatDecimal(Math.floor(totalMinutes / 60), 0);
	const minutes = formatDecimal(totalMinutes % 60, 0);
	return totalMinutes >= 60
		? pageText('voiceDetail.remainingHours', { hours, minutes })
		: pageText('voiceDetail.remainingMinutes', { minutes });
}
