import { describe, expect, it } from 'vitest';
import {
	albumSummaryLabel,
	formatTime,
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

describe('songCountLabel', () => {
	it.each([
		[0, '0 songs'],
		[1, '1 song'],
		[2, '2 songs']
	])('songCount=%i -> %j', (songCount, expected) => {
		expect(songCountLabel(songCount)).toBe(expected);
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
