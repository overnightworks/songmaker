/** Inclusive byte range as returned by {@link parseRangeHeader}. */
export interface ByteRange {
	start: number;
	/** Inclusive end offset. */
	end: number;
}

/**
 * Parses an HTTP Range header value against a known total content length.
 *
 * Supported forms:
 *   bytes=start-end   — explicit range (end clamped to totalLength - 1)
 *   bytes=start-      — open range (start to last byte)
 *   bytes=-N          — suffix range (last N bytes)
 *
 * Returns null when the header is malformed or unsatisfiable (caller maps
 * null to a 416 response).
 */
export function parseRangeHeader(rangeHeader: string, totalLength: number): ByteRange | null {
	const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader);
	if (!match) return null;

	const startStr = match[1];
	const endStr = match[2];

	if (!startStr && !endStr) return null;

	let start: number;
	let end: number;

	if (!startStr) {
		// Suffix range: bytes=-N → last N bytes
		const suffixLength = Number.parseInt(endStr, 10);
		if (Number.isNaN(suffixLength) || suffixLength <= 0) return null;
		start = Math.max(0, totalLength - suffixLength);
		end = totalLength - 1;
	} else if (!endStr) {
		// Open range: bytes=N-
		start = Number.parseInt(startStr, 10);
		if (Number.isNaN(start)) return null;
		end = totalLength - 1;
	} else {
		start = Number.parseInt(startStr, 10);
		end = Number.parseInt(endStr, 10);
		if (Number.isNaN(start) || Number.isNaN(end)) return null;
		if (start > end) return null;
		end = Math.min(end, totalLength - 1);
	}

	if (start >= totalLength) return null;

	return { start, end };
}
