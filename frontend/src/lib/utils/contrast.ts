export const WCAG_AA_NORMAL_TEXT_RATIO = 4.5;
export const WCAG_AA_NON_TEXT_RATIO = 3;

const SRGB_CHANNEL_MAX = 255;
const SRGB_LINEAR_CUTOFF = 0.04045;
const SRGB_LINEAR_DIVISOR = 12.92;
const SRGB_GAMMA = 2.4;
const SRGB_OFFSET = 0.055;
const SRGB_SCALE = 1.055;
const LUMINANCE_RED = 0.2126;
const LUMINANCE_GREEN = 0.7152;
const LUMINANCE_BLUE = 0.0722;
const CONTRAST_OFFSET = 0.05;
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

export function hexToRgb(hex: string): readonly [number, number, number] {
	const normalized = expandHex(hex);
	return [
		parseInt(normalized.slice(0, 2), 16),
		parseInt(normalized.slice(2, 4), 16),
		parseInt(normalized.slice(4, 6), 16)
	];
}

function channelToLinear(channel: number): number {
	const srgb = channel / SRGB_CHANNEL_MAX;
	if (srgb <= SRGB_LINEAR_CUTOFF) {
		return srgb / SRGB_LINEAR_DIVISOR;
	}
	return ((srgb + SRGB_OFFSET) / SRGB_SCALE) ** SRGB_GAMMA;
}

export function relativeLuminance(hex: string): number {
	const [r, g, b] = hexToRgb(hex);
	return (
		LUMINANCE_RED * channelToLinear(r) +
		LUMINANCE_GREEN * channelToLinear(g) +
		LUMINANCE_BLUE * channelToLinear(b)
	);
}

export function contrastRatio(foreground: string, background: string): number {
	const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
	const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
	return (lighter + CONTRAST_OFFSET) / (darker + CONTRAST_OFFSET);
}
