import { describe, expect, it } from 'vitest';
import { formatTime, titleInitials } from './format.ts';

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
