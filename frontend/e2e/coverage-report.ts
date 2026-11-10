// Turns one Playwright project's raw coverage store, merged with the stores of
// any extra roots, into an LCOV file and an HTML report and prints the figures
// as a Markdown table for the run summary.
// Usage: node e2e/coverage-report.ts <project> [<root>...]

import { coverageStoreDir } from './coverage-options.ts';
import { summarizeCoverage } from './coverage-summary.ts';

const [project, ...extraRoots] = process.argv.slice(2);
if (!project) {
	throw new Error('Usage: node e2e/coverage-report.ts <project> [<root>...]');
}

const reportStarted = performance.now();
const { branches, lines, functions, collectionSeconds } = await summarizeCoverage(
	project,
	extraRoots
);
const reportSeconds = (performance.now() - reportStarted) / 1000;

console.log(`### E2E-only coverage (${project})`);
console.log('');
console.log('| Branches | Lines | Functions | Collection | Report |');
console.log('|---|---|---|---|---|');
console.log(
	`| ${branches.pct} % (${branches.covered}/${branches.total}) | ${lines.pct} % (${lines.covered}/${lines.total}) | ` +
		`${functions.pct} % (${functions.covered}/${functions.total}) | ${collectionSeconds.toFixed(1)} s | ${reportSeconds.toFixed(1)} s |`
);
console.log('');
console.log(`Reports in ${coverageStoreDir(project)}`);
