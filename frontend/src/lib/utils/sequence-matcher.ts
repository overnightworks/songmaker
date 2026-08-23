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

	constructor(a: string, b: string, autojunk = true) {
		this.a = a;
		this.b = b;
		this.b2j = buildB2J(b, autojunk);
	}

	findLongestMatch(alo = 0, ahi = this.a.length, blo = 0, bhi = this.b.length): Match {
		const { a, b, b2j } = this;
		let besti = alo;
		let bestj = blo;
		let bestsize = 0;
		let j2len = new Map<number, number>();

		for (let i = alo; i < ahi; i++) {
			const newj2len = new Map<number, number>();
			const indices = b2j.get(a[i]);
			if (indices) {
				for (const j of indices) {
					if (j < blo) continue;
					if (j >= bhi) break;
					const k = (j2len.get(j - 1) ?? 0) + 1;
					newj2len.set(j, k);
					if (k > bestsize) {
						besti = i - k + 1;
						bestj = j - k + 1;
						bestsize = k;
					}
				}
			}
			j2len = newj2len;
		}

		while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) {
			besti -= 1;
			bestj -= 1;
			bestsize += 1;
		}
		while (
			besti + bestsize < ahi &&
			bestj + bestsize < bhi &&
			a[besti + bestsize] === b[bestj + bestsize]
		) {
			bestsize += 1;
		}

		return { a: besti, b: bestj, size: bestsize };
	}

	getMatchingBlocks(): Match[] {
		if (this.matchingBlocks) return this.matchingBlocks;

		const la = this.a.length;
		const lb = this.b.length;
		const queue: [number, number, number, number][] = [[0, la, 0, lb]];
		const found: Match[] = [];

		while (queue.length > 0) {
			const next = queue.pop();
			if (!next) break;
			const [alo, ahi, blo, bhi] = next;
			const match = this.findLongestMatch(alo, ahi, blo, bhi);
			const { a: i, b: j, size: k } = match;
			if (k) {
				found.push(match);
				if (alo < i && blo < j) queue.push([alo, i, blo, j]);
				if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
			}
		}
		found.sort((x, y) => x.a - y.a || x.b - y.b || x.size - y.size);

		const merged: Match[] = [];
		let i1 = 0;
		let j1 = 0;
		let k1 = 0;
		for (const { a: i2, b: j2, size: k2 } of found) {
			if (i1 + k1 === i2 && j1 + k1 === j2) {
				k1 += k2;
			} else {
				if (k1) merged.push({ a: i1, b: j1, size: k1 });
				i1 = i2;
				j1 = j2;
				k1 = k2;
			}
		}
		if (k1) merged.push({ a: i1, b: j1, size: k1 });
		merged.push({ a: la, b: lb, size: 0 });

		this.matchingBlocks = merged;
		return merged;
	}

	ratio(): number {
		const matches = this.getMatchingBlocks().reduce((sum, block) => sum + block.size, 0);
		const length = this.a.length + this.b.length;
		return length ? (2.0 * matches) / length : 1.0;
	}
}

function buildB2J(b: string, autojunk: boolean): Map<string, number[]> {
	const b2j = new Map<string, number[]>();
	for (let i = 0; i < b.length; i++) {
		const elt = b[i];
		const indices = b2j.get(elt);
		if (indices) indices.push(i);
		else b2j.set(elt, [i]);
	}

	if (autojunk && b.length >= AUTOJUNK_MIN_LENGTH) {
		const ntest = Math.floor(b.length / 100) + 1;
		for (const [elt, indices] of b2j) {
			if (indices.length > ntest) b2j.delete(elt);
		}
	}

	return b2j;
}
