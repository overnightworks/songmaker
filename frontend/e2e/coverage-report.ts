// Turns one Playwright project's raw coverage store into an LCOV file and an
// HTML report and prints the figures as a Markdown table for the run summary.
// Usage: node e2e/coverage-report.ts <project>

import { readFileSync } from 'node:fs';
import { MCR } from 'monocart-coverage-reports';
import { collectionTimeFile, coverageOptions, coverageStoreDir } from './coverage-options.ts';

const project = process.argv[2];
if (!project) {
	throw new Error('Usage: node e2e/coverage-report.ts <project>');
}

function collectionSeconds(): number {
	const milliseconds = readFileSync(collectionTimeFile(project), 'utf8')
		.split('\n')
		.filter(Boolean)
		.reduce((total, line) => total + Number(line), 0);
	return milliseconds / 1000;
}

const reportStarted = performance.now();
const results = await MCR(coverageOptions(project)).generate();
if (!results) {
	throw new Error(`No coverage was collected for project ${project}`);
}
const reportSeconds = (performance.now() - reportStarted) / 1000;
const { branches, lines, functions } = results.summary;

console.log(`### E2E-only coverage (${project})`);
console.log('');
console.log('| Branches | Lines | Functions | Collection | Report |');
console.log('|---|---|---|---|---|');
console.log(
	`| ${branches.pct} % (${branches.covered}/${branches.total}) | ${lines.pct} % (${lines.covered}/${lines.total}) | ` +
		`${functions.pct} % (${functions.covered}/${functions.total}) | ${collectionSeconds().toFixed(1)} s | ${reportSeconds.toFixed(1)} s |`
);
console.log('');
console.log(`Reports in ${coverageStoreDir(project)}`);
