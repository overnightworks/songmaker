import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import {
	activityTimeLabel,
	addedDayLabel,
	albumSummaryLabel,
	formatTime,
	localWeekday,
	placeLine,
	playlistSummaryLabel,
	songCountLabel,
	titleInitials
} from './format.ts';

describe('formatTime', () => {
	it('formats zero seconds', () => {
		expect(formatTime(0)).toBe('0:00');
	});

	it('formats seconds under a minute', () => {
		expect(formatTime(45)).toBe('0:45');
	});

	it('formats full minutes', () => {
		expect(formatTime(120)).toBe('2:00');
	});

	it('formats minutes and seconds', () => {
		expect(formatTime(195)).toBe('3:15');
	});

	it('floors fractional seconds', () => {
		expect(formatTime(61.7)).toBe('1:01');
	});
});

describe('albumSummaryLabel', () => {
	it.each([
		[0, 0, '0 songs · 0 picks'],
		[1, 0, '1 song · 0 picks'],
		[3, 1, '3 songs · 1 pick'],
		[3, 2, '3 songs · 2 picks']
	])('songCount=%i pickCount=%i -> %j', (songCount, pickCount, expected) => {
		expect(albumSummaryLabel(songCount, pickCount)).toBe(expected);
	});
});

describe('playlistSummaryLabel', () => {
	it.each([
		[0, '0 tracks'],
		[1, '1 track'],
		[5, '5 tracks']
	])('entryCount=%i -> %j', (entryCount, expected) => {
		expect(playlistSummaryLabel(entryCount)).toBe(expected);
	});
});

describe('songCountLabel', () => {
	it.each([
		[0, '0 songs'],
		[1, '1 song'],
		[6, '6 songs']
	])('count=%i -> %j', (count, expected) => {
		expect(songCountLabel(count)).toBe(expected);
	});
});

describe('placeLine', () => {
	it('says a playlist is one before its detail', () => {
		expect(placeLine('playlist', '14 songs')).toBe('Playlist · 14 songs');
	});

	it('leaves an album line as its detail', () => {
		expect(placeLine('album', '6 songs')).toBe('6 songs');
	});
});

describe('titleInitials', () => {
	it.each([
		['Nachtstrom', 'NA'],
		['Night Drive', 'ND'],
		['  after   the rain  ', 'AT'],
		['x', 'X'],
		['', '?'],
		['   ', '?'],
		['🎵 Song', '🎵S']
	])('turns %j into %j', (title, expected) => {
		expect(titleInitials(title)).toBe(expected);
	});
});

describe('activityTimeLabel', () => {
	beforeAll(() => vi.stubEnv('TZ', 'Europe/Berlin'));
	afterAll(() => vi.unstubAllEnvs());

	const sundayNoonInBerlin = '2026-09-27T10:00:00Z';

	it.each([
		['earlier today', '2026-09-27T03:47:00Z', sundayNoonInBerlin, 'today 05:47'],
		[
			'after local midnight, while UTC still dates it the day before',
			'2026-09-26T22:30:00Z',
			sundayNoonInBerlin,
			'today 00:30'
		],
		['yesterday', '2026-09-26T21:40:00Z', sundayNoonInBerlin, 'yesterday 23:40'],
		['this week by weekday', '2026-09-24T18:31:00Z', sundayNoonInBerlin, 'Thu 20:31'],
		['a week or more ago by day and month', '2026-09-20T10:00:00Z', sundayNoonInBerlin, '20 Sep'],
		['in another year with the year', '2025-09-21T10:00:00Z', sundayNoonInBerlin, '21 Sep 2025'],
		[
			'across the night the clocks go back',
			'2026-10-25T09:00:00Z',
			'2026-10-26T10:00:00Z',
			'yesterday 10:00'
		]
	])('reads a moment %s', (_case, activityAt, now, label) => {
		expect(activityTimeLabel(activityAt, new Date(now))).toBe(label);
	});
});

describe('localWeekday', () => {
	beforeAll(() => vi.stubEnv('TZ', 'Europe/Berlin'));
	afterAll(() => vi.unstubAllEnvs());

	it('names the local weekday, not the UTC one', () => {
		expect(localWeekday(new Date('2026-09-26T22:30:00Z'))).toBe('Sun');
	});
});

describe('addedDayLabel', () => {
	beforeAll(() => vi.stubEnv('TZ', 'Europe/Berlin'));
	afterAll(() => vi.unstubAllEnvs());

	const sundayNoonInBerlin = new Date('2026-09-27T10:00:00Z');

	it.each([
		['this year by day and month', '2026-08-03T10:00:00Z', 'added 3 Aug'],
		['on the local day, not the UTC one', '2026-08-02T22:30:00Z', 'added 3 Aug'],
		['in another year with the year', '2025-08-03T10:00:00Z', 'added 3 Aug 2025']
	])('reads a creation %s', (_case, createdAt, label) => {
		expect(addedDayLabel(createdAt, sundayNoonInBerlin)).toBe(label);
	});
});
