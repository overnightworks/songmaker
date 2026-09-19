import { describe, expect, it } from 'vitest';
import { usableAlbumPrimary } from './contrast.ts';

describe('usableAlbumPrimary', () => {
	it('returns a trimmed, parseable hex primary', () => {
		expect(usableAlbumPrimary({ primary: ' #112233 ' })).toBe('#112233');
	});

	it('returns null when there is no primary color', () => {
		expect(usableAlbumPrimary({})).toBeNull();
	});

	it('returns null for a blank primary', () => {
		expect(usableAlbumPrimary({ primary: '   ' })).toBeNull();
	});

	it('returns null for an unparseable primary', () => {
		expect(usableAlbumPrimary({ primary: 'not-a-color' })).toBeNull();
	});
});
