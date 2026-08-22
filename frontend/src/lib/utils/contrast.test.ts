import { describe, expect, it } from 'vitest';
import {
	contrastRatio,
	hexToRgb,
	relativeLuminance,
	usableAlbumPrimary,
	WCAG_AA_NON_TEXT_RATIO,
	WCAG_AA_NORMAL_TEXT_RATIO
} from './contrast.ts';

type ThemeName = 'dark' | 'light';

const THEME_COLORS: Record<ThemeName, Record<string, string>> = {
	dark: {
		'--bg': '#0d0d0d',
		'--surface': '#111',
		'--text': '#e0e0e0',
		'--text-subtle': '#888',
		'--text-disabled': '#555',
		'--text-decoration': '#444',
		'--text-dim': '#444',
		'--accent': '#a020f0'
	},
	light: {
		'--bg': '#f4f4f6',
		'--surface': '#ffffff',
		'--text': '#1a1a1e',
		'--text-subtle': '#555',
		'--text-disabled': '#9a9a9a',
		'--text-decoration': '#999',
		'--text-dim': '#999',
		'--accent': '#7a18c0'
	}
};

function themeColor(theme: ThemeName, name: string): string {
	const value = THEME_COLORS[theme][name];
	if (!value) {
		throw new Error(`Missing token ${name}`);
	}
	return value;
}

describe('contrastRatio', () => {
	it('is 21 for black on white', () => {
		expect(contrastRatio('#000000', '#ffffff')).toBe(21);
	});

	it('is 1 for identical colors', () => {
		expect(contrastRatio('#444', '#444444')).toBe(1);
	});

	it('matches the measured --text-dim failures', () => {
		expect(contrastRatio('#444', '#0d0d0d')).toBeCloseTo(2.0, 2);
		expect(contrastRatio('#999', '#f4f4f6')).toBeCloseTo(2.59, 2);
	});

	it('rejects invalid hex', () => {
		expect(() => hexToRgb('#12')).toThrow(/Invalid hex color/);
		expect(() => relativeLuminance('blue')).toThrow(/Invalid hex color/);
	});
});

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

describe('semantic text tokens', () => {
	const themes: ThemeName[] = ['dark', 'light'];
	const surfaces = ['--bg', '--surface'] as const;
	const readableTokens = ['--text', '--text-subtle'] as const;

	it('defines subtle, disabled, and decoration in dark and light', () => {
		expect(themeColor('dark', '--text-subtle')).toBe('#888');
		expect(themeColor('dark', '--text-disabled')).toBe('#555');
		expect(themeColor('dark', '--text-decoration')).toBe('#444');
		expect(themeColor('light', '--text-subtle')).toBe('#555');
		expect(themeColor('light', '--text-disabled')).toBe('#9a9a9a');
		expect(themeColor('light', '--text-decoration')).toBe('#999');
		for (const theme of themes) {
			expect(themeColor(theme, '--text-dim')).toBe(themeColor(theme, '--text-decoration'));
		}
	});

	it('documents contrast of subtle, disabled, and decoration against --bg and --surface', () => {
		const documented: Array<[ThemeName, string, string, number]> = [
			['dark', '--text-subtle', '--bg', 5.48],
			['dark', '--text-subtle', '--surface', 5.33],
			['dark', '--text-disabled', '--bg', 2.61],
			['dark', '--text-disabled', '--surface', 2.53],
			['dark', '--text-decoration', '--bg', 2.0],
			['dark', '--text-decoration', '--surface', 1.94],
			['light', '--text-subtle', '--bg', 6.79],
			['light', '--text-subtle', '--surface', 7.46],
			['light', '--text-disabled', '--bg', 2.56],
			['light', '--text-disabled', '--surface', 2.81],
			['light', '--text-decoration', '--bg', 2.59],
			['light', '--text-decoration', '--surface', 2.85]
		];
		for (const [theme, token, surface, expected] of documented) {
			expect(
				contrastRatio(themeColor(theme, token), themeColor(theme, surface)),
				`${theme} ${token} on ${surface}`
			).toBeCloseTo(expected, 2);
		}
	});

	it('gives readable text tokens at least 4.5:1 on --bg and --surface', () => {
		for (const theme of themes) {
			for (const token of readableTokens) {
				for (const surface of surfaces) {
					const ratio = contrastRatio(themeColor(theme, token), themeColor(theme, surface));
					expect(ratio, `${theme} ${token} on ${surface}`).toBeGreaterThanOrEqual(
						WCAG_AA_NORMAL_TEXT_RATIO
					);
				}
			}
		}
	});

	it('keeps --text-disabled distinguishable from body text without requiring 4.5:1 on --bg', () => {
		for (const theme of themes) {
			const disabled = themeColor(theme, '--text-disabled');
			const text = themeColor(theme, '--text');
			const bg = themeColor(theme, '--bg');
			const surface = themeColor(theme, '--surface');
			expect(contrastRatio(disabled, bg)).toBeLessThan(WCAG_AA_NORMAL_TEXT_RATIO);
			expect(contrastRatio(disabled, surface)).toBeLessThan(WCAG_AA_NORMAL_TEXT_RATIO);
			expect(contrastRatio(disabled, text)).toBeGreaterThanOrEqual(WCAG_AA_NON_TEXT_RATIO);
		}
	});

	it('keeps --text-decoration weaker than readable text tokens', () => {
		for (const theme of themes) {
			const decoration = themeColor(theme, '--text-decoration');
			const subtle = themeColor(theme, '--text-subtle');
			const bg = themeColor(theme, '--bg');
			expect(decoration).not.toBe(subtle);
			expect(contrastRatio(decoration, bg)).toBeLessThan(contrastRatio(subtle, bg));
		}
	});

	it('keeps --accent at least 3:1 on --bg for focus outlines', () => {
		for (const theme of themes) {
			const ratio = contrastRatio(themeColor(theme, '--accent'), themeColor(theme, '--bg'));
			expect(ratio, `${theme} --accent on --bg`).toBeGreaterThanOrEqual(WCAG_AA_NON_TEXT_RATIO);
		}
	});
});
