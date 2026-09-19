interface DiffIndex {
	type: 'same' | 'add' | 'remove';
	oldIndex: number | null;
	newIndex: number | null;
}

function trimTrailingEmpty(lines: string[]): string[] {
	while (lines.length > 0 && lines.at(-1) === '') {
		lines.pop();
	}
	return lines;
}

export function computeDiffByKey(oldTokens: string[], newTokens: string[]): DiffIndex[] {
	const oldLines = trimTrailingEmpty([...oldTokens]);
	const newLines = trimTrailingEmpty([...newTokens]);
	const dp = lcsMatrix(oldLines, newLines);
	return buildDiffIndex(oldLines, newLines, dp);
}

function lcsMatrix(a: string[], b: string[]): number[][] {
	const m = a.length;
	const n = b.length;
	const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

	for (let i = 1; i <= m; i++) {
		for (let j = 1; j <= n; j++) {
			dp[i][j] =
				a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
		}
	}
	return dp;
}

function buildDiffIndex(oldLines: string[], newLines: string[], dp: number[][]): DiffIndex[] {
	const result: DiffIndex[] = [];
	let i = oldLines.length;
	let j = newLines.length;

	while (i > 0 || j > 0) {
		if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
			result.push({ type: 'same', oldIndex: i - 1, newIndex: j - 1 });
			i--;
			j--;
		} else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
			result.push({ type: 'add', oldIndex: null, newIndex: j - 1 });
			j--;
		} else {
			result.push({ type: 'remove', oldIndex: i - 1, newIndex: null });
			i--;
		}
	}

	return result.reverse();
}
