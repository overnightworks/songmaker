import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import {
	accountInitial,
	activityTimeLabel,
	formatDecimal,
	formatList,
	formatRemainingTime,
	formatPercent,
	formatTime,
	localDayAndMonth,
	localWeekday,
	releaseDayLabel,
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

describe('accountInitial', () => {
	it.each([
		['felix', 'F'],
		['élodie', 'É'],
		['🎵beats', '🎵'],
		['', '']
	])('turns %j into %j', (username, expected) => {
		expect(accountInitial(username)).toBe(expected);
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

describe('a day label follows the page language', () => {
	beforeAll(() => vi.stubEnv('TZ', 'Europe/Berlin'));
	afterAll(() => vi.unstubAllEnvs());

	it.each([
		['weekday', localWeekday],
		['month', (moment: Date) => localDayAndMonth(moment, moment)]
	])('the same moment has a different %s under two page languages', (_part, label) => {
		const moment = new Date('2026-03-26T22:30:00Z');
		document.documentElement.lang = 'en';
		const english = label(moment);
		document.documentElement.lang = 'de';
		expect(label(moment)).not.toBe(english);
	});
});

describe('localDayAndMonth', () => {
	beforeAll(() => vi.stubEnv('TZ', 'Europe/Berlin'));
	afterAll(() => vi.unstubAllEnvs());

	it.each([
		{ moment: '2026-10-27T10:00:00Z', expected: '27 Oct' },
		{ moment: '2025-10-27T10:00:00Z', expected: '27 Oct 2025' }
	])('writes $moment as "$expected" in 2026', ({ moment, expected }) => {
		expect(localDayAndMonth(new Date(moment), new Date('2026-11-02T09:00:00Z'))).toBe(expected);
	});
});

describe('releaseDayLabel', () => {
	beforeAll(() => vi.stubEnv('TZ', 'America/Los_Angeles'));
	afterAll(() => vi.unstubAllEnvs());

	it.each([
		['v2026.10.28.4', '28 Oct 2026'],
		['v2026.01.01.12', '1 Jan 2026'],
		['v1.2.3', null],
		['v2026.13.01.1', null],
		['v2026.02.30.1', null],
		['unreleased', null]
	])('turns the tag %j into %j', (tag, expected) => {
		expect(releaseDayLabel(tag)).toBe(expected);
	});
});

describe('formatDecimal', () => {
	it.each([
		{ value: 7.25, digits: 1, expected: '7.3' },
		{ value: 24, digits: 1, expected: '24.0' },
		{ value: 23.6, digits: 0, expected: '24' },
		{ value: 1234.5, digits: 1, expected: '1,234.5' }
	])('writes $value with $digits decimals as "$expected"', ({ value, digits, expected }) => {
		expect(formatDecimal(value, digits)).toBe(expected);
	});
});

describe('formatPercent', () => {
	it.each([
		{ fraction: 0, expected: '0%' },
		{ fraction: 0.424, expected: '42%' },
		{ fraction: 1, expected: '100%' }
	])('writes $fraction as "$expected"', ({ fraction, expected }) => {
		expect(formatPercent(fraction)).toBe(expected);
	});
});

describe('formatList', () => {
	it.each([
		{ items: [], expected: '' },
		{ items: ['2 takes'], expected: '2 takes' },
		{ items: ['2 takes', '1 version'], expected: '2 takes, 1 version' },
		{ items: ['.wav', '.mp3', '.flac'], expected: '.wav, .mp3, .flac' }
	])('writes $items as "$expected"', ({ items, expected }) => {
		expect(formatList(items)).toBe(expected);
	});
});

describe('formatRemainingTime', () => {
	it.each([
		{ seconds: 1, expected: '~ 1m remaining' },
		{ seconds: 61, expected: '~ 2m remaining' },
		{ seconds: 540, expected: '~ 9m remaining' },
		{ seconds: 3600, expected: '~ 1h 0m remaining' },
		{ seconds: 7200, expected: '~ 2h 0m remaining' },
		{ seconds: 7260, expected: '~ 2h 1m remaining' }
	])('writes $seconds seconds as "$expected"', ({ seconds, expected }) => {
		expect(formatRemainingTime(seconds)).toBe(expected);
	});
});
