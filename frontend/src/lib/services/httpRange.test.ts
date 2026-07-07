import { describe, it, expect } from 'vitest';
import { parseRangeHeader } from './httpRange';

const TOTAL = 1000;

describe('parseRangeHeader', () => {
	it('parses an explicit range', () => {
		expect(parseRangeHeader('bytes=0-499', TOTAL)).toEqual({ start: 0, end: 499 });
	});

	it('parses a range starting at 0', () => {
		expect(parseRangeHeader('bytes=0-999', TOTAL)).toEqual({ start: 0, end: 999 });
	});

	it('clamps end to totalLength - 1', () => {
		expect(parseRangeHeader('bytes=0-9999', TOTAL)).toEqual({ start: 0, end: 999 });
	});

	it('parses an open range (bytes=N-)', () => {
		expect(parseRangeHeader('bytes=500-', TOTAL)).toEqual({ start: 500, end: 999 });
	});

	it('parses a suffix range (bytes=-N)', () => {
		expect(parseRangeHeader('bytes=-100', TOTAL)).toEqual({ start: 900, end: 999 });
	});

	it('clamps suffix range when N exceeds totalLength', () => {
		expect(parseRangeHeader('bytes=-2000', TOTAL)).toEqual({ start: 0, end: 999 });
	});

	it('returns null when start > end', () => {
		expect(parseRangeHeader('bytes=999-0', TOTAL)).toBeNull();
	});

	it('returns null when start equals totalLength', () => {
		expect(parseRangeHeader('bytes=1000-', TOTAL)).toBeNull();
	});

	it('returns null when start exceeds totalLength', () => {
		expect(parseRangeHeader('bytes=1001-1010', TOTAL)).toBeNull();
	});

	it('returns null for unrecognised unit', () => {
		expect(parseRangeHeader('other=0-10', TOTAL)).toBeNull();
	});

	it('returns null for bare "bytes=-"', () => {
		expect(parseRangeHeader('bytes=-', TOTAL)).toBeNull();
	});

	it('returns null for missing both bounds', () => {
		expect(parseRangeHeader('bytes=-', TOTAL)).toBeNull();
	});

	it('parses a mid-file range correctly', () => {
		expect(parseRangeHeader('bytes=200-299', TOTAL)).toEqual({ start: 200, end: 299 });
	});
});
