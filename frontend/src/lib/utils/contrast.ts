const SHORT_HEX_LENGTH = 3;
const LONG_HEX_LENGTH = 6;

function expandHex(hex: string): string {
	const trimmed = hex.trim().replace(/^#/, '');
	if (trimmed.length === SHORT_HEX_LENGTH && /^[0-9a-fA-F]{3}$/.test(trimmed)) {
		return trimmed
			.split('')
			.map((ch) => `${ch}${ch}`)
			.join('');
	}
	if (trimmed.length === LONG_HEX_LENGTH && /^[0-9a-fA-F]{6}$/.test(trimmed)) {
		return trimmed;
	}
	throw new Error(`Invalid hex color: ${hex}`);
}

function hexToRgb(hex: string): readonly [number, number, number] {
	const normalized = expandHex(hex);
	return [
		Number.parseInt(normalized.slice(0, 2), 16),
		Number.parseInt(normalized.slice(2, 4), 16),
		Number.parseInt(normalized.slice(4, 6), 16)
	];
}

// An album's stored `colors.primary` swatch, usable as a CSS fill only when
// it is a non-empty, parseable hex color. Shared by every surface that falls
// back to this swatch when an album has no cover image (library wall tiles,
// album detail art, song detail art).
export function usableAlbumPrimary(colors: Record<string, string>): string | null {
	const primary = colors.primary;
	if (typeof primary !== 'string') return null;
	const value = primary.trim();
	if (!value) return null;
	try {
		hexToRgb(value);
	} catch {
		return null;
	}
	return value;
}
