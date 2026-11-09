// The figures of one Playwright project's coverage report: its own store
// merged with the stores of any extra roots, and the seconds spent collecting.

import { existsSync, readFileSync } from 'node:fs';
import { MCR } from 'monocart-coverage-reports';
import { collectionTimeFile, coverageOptions } from './coverage-options.ts';

type Figures = NonNullable<Awaited<ReturnType<ReturnType<typeof MCR>['generate']>>>['summary'];

export type CoverageSummary = Pick<Figures, 'branches' | 'lines' | 'functions'> & {
	collectionSeconds: number;
};

function secondsIn(timeFile: string): number {
	const milliseconds = readFileSync(timeFile, 'utf8')
		.split('\n')
		.filter(Boolean)
		.reduce((total, line) => total + Number(line), 0);
	return milliseconds / 1000;
}

// Generates the report into the project's own store. Without extra roots the
// own time file must exist; with them a job that only merges has none.
export async function summarizeCoverage(
	project: string,
	extraRoots: readonly string[] = [],
	ownRoot?: string
): Promise<CoverageSummary> {
	const results = await MCR(coverageOptions(project, extraRoots, ownRoot)).generate();
	if (!results) {
		throw new Error(`No coverage was collected for project ${project}`);
	}
	const ownTimeFile = collectionTimeFile(project, ownRoot);
	const timeFiles = [
		...(extraRoots.length > 0 && !existsSync(ownTimeFile) ? [] : [ownTimeFile]),
		...extraRoots.map((extraRoot) => collectionTimeFile(project, extraRoot))
	];
	const { branches, lines, functions } = results.summary;
	return {
		branches,
		lines,
		functions,
		collectionSeconds: timeFiles.reduce((total, timeFile) => total + secondsIn(timeFile), 0)
	};
}
