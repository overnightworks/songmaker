// Faithful TypeScript port of Python's difflib.SequenceMatcher(None, a, b),
// restricted to string sequences (character-level comparison) since that is
// the only use this codebase has (issue #45's lyric/cue similarity ratio).
// Ports find_longest_match, get_matching_blocks, and ratio() line for line
// against cpython's Lib/difflib.py, including the autojunk popular-element
// filter (elements covering more than 1% of a >=200-length b). isjunk is
// never used in this codebase, so the junk-callback branches from cpython
// (which are no-ops when isjunk is None) are omitted.

export interface Match {
	a: number;
	b: number;
	size: number;
}

const AUTOJUNK_MIN_LENGTH = 200;

export class SequenceMatcher {
	private readonly a: string;
	private readonly b: string;
	private readonly b2j: Map<string, number[]>;
	private matchingBlocks: Match[] | null = null;

	constructor(a: string, b: string) {
		this.a = a;
		this.b = b;
		this.b2j = buildB2J(b);
	}

	findLongestMatch(alo = 0, ahi = this.a.length, blo = 0, bhi = this.b.length): Match {
		const { a, b, b2j } = this;
		const best = { a: alo, b: blo, size: 0 };
		let j2len = new Map<number, number>();

		for (let i = alo; i < ahi; i++) {
			j2len = findMatchesEndingAt(a[i], i, b2j, blo, bhi, j2len, best);
		}

		extendMatchBackwards(a, b, alo, blo, best);
		extendMatchForwards(a, b, ahi, bhi, best);
		return best;
	}

	getMatchingBlocks(): Match[] {
		if (this.matchingBlocks) return this.matchingBlocks;

		const matches = findMatchingBlocks(this.a.length, this.b.length, (alo, ahi, blo, bhi) =>
			this.findLongestMatch(alo, ahi, blo, bhi)
		);
		this.matchingBlocks = mergeMatchingBlocks(matches, this.a.length, this.b.length);
		return this.matchingBlocks;
	}

	ratio(): number {
		const matches = this.getMatchingBlocks().reduce((sum, block) => sum + block.size, 0);
		const length = this.a.length + this.b.length;
		return length ? (2.0 * matches) / length : 1.0;
	}
}

function findMatchesEndingAt(
	character: string,
	index: number,
	b2j: Map<string, number[]>,
	blo: number,
	bhi: number,
	previousLengths: Map<number, number>,
	best: Match
): Map<number, number> {
	const lengths = new Map<number, number>();
	const indices = b2j.get(character);
	if (!indices) return lengths;

	for (const otherIndex of indices) {
		if (otherIndex < blo) continue;
		if (otherIndex >= bhi) break;
		const length = (previousLengths.get(otherIndex - 1) ?? 0) + 1;
		lengths.set(otherIndex, length);
		if (length > best.size) {
			best.a = index - length + 1;
			best.b = otherIndex - length + 1;
			best.size = length;
		}
	}
	return lengths;
}

function extendMatchBackwards(
	a: string,
	b: string,
	alo: number,
	blo: number,
	match: Match
): void {
	while (match.a > alo && match.b > blo && a[match.a - 1] === b[match.b - 1]) {
		match.a -= 1;
		match.b -= 1;
		match.size += 1;
	}
}

function extendMatchForwards(
	a: string,
	b: string,
	ahi: number,
	bhi: number,
	match: Match
): void {
	while (
		match.a + match.size < ahi &&
		match.b + match.size < bhi &&
		a[match.a + match.size] === b[match.b + match.size]
	) {
		match.size += 1;
	}
}

function findMatchingBlocks(
	aLength: number,
	bLength: number,
	findLongestMatch: (alo: number, ahi: number, blo: number, bhi: number) => Match
): Match[] {
	const queue: [number, number, number, number][] = [[0, aLength, 0, bLength]];
	const found: Match[] = [];

	while (queue.length > 0) {
		const next = queue.pop();
		if (!next) break;
		const [alo, ahi, blo, bhi] = next;
		const match = findLongestMatch(alo, ahi, blo, bhi);
		if (!match.size) continue;
		found.push(match);
		enqueueMatchGaps(queue, match, alo, ahi, blo, bhi);
	}
	return found.sort((left, right) => left.a - right.a || left.b - right.b || left.size - right.size);
}

function enqueueMatchGaps(
	queue: [number, number, number, number][],
	match: Match,
	alo: number,
	ahi: number,
	blo: number,
	bhi: number
): void {
	if (alo < match.a && blo < match.b) queue.push([alo, match.a, blo, match.b]);
	if (match.a + match.size < ahi && match.b + match.size < bhi) {
		queue.push([match.a + match.size, ahi, match.b + match.size, bhi]);
	}
}

function mergeMatchingBlocks(matches: Match[], aLength: number, bLength: number): Match[] {
	const merged: Match[] = [];
	let current = { a: 0, b: 0, size: 0 };
	for (const match of matches) {
		if (isAdjacentMatch(current, match)) {
			current.size += match.size;
			continue;
		}
		if (current.size) merged.push(current);
		current = match;
	}
	if (current.size) merged.push(current);
	merged.push({ a: aLength, b: bLength, size: 0 });
	return merged;
}

function isAdjacentMatch(first: Match, second: Match): boolean {
	return first.a + first.size === second.a && first.b + first.size === second.b;
}

function buildB2J(b: string): Map<string, number[]> {
	const b2j = new Map<string, number[]>();
	for (let i = 0; i < b.length; i++) {
		const elt = b[i];
		const indices = b2j.get(elt);
		if (indices) indices.push(i);
		else b2j.set(elt, [i]);
	}

	if (b.length >= AUTOJUNK_MIN_LENGTH) {
		const ntest = Math.floor(b.length / 100) + 1;
		for (const [elt, indices] of b2j) {
			if (indices.length > ntest) b2j.delete(elt);
		}
	}

	return b2j;
}
