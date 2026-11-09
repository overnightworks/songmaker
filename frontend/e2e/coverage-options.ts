// What the raw coverage store and its report share, so the fixture that fills
// the store and the script that reads it agree on where it is and how paths read.

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { CoverageReportOptions } from 'monocart-coverage-reports';

const COVERAGE_DIR = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	'.artifacts',
	'coverage'
);
const APP_SOURCE = /(?:^|\/)(src\/.*)$/;

export function coverageStoreDir(project: string): string {
	return path.join(COVERAGE_DIR, project);
}

// One line per test: the milliseconds its coverage took to stop and store.
// Beside the store, because generating a report cleans the store's directory.
export function collectionTimeFile(project: string): string {
	return path.join(COVERAGE_DIR, `${project}.collection-ms`);
}

// The build's source maps name each source relative to the bundle, which
// resolves to a path ending in `src/...`; the report names it from the repository root.
function repositoryPath(sourcePath: string): string {
	const match = APP_SOURCE.exec(sourcePath);
	return match ? `frontend/${match[1]}` : sourcePath;
}

export function coverageOptions(project: string): CoverageReportOptions {
	return {
		name: `E2E coverage (${project})`,
		outputDir: coverageStoreDir(project),
		reports: ['lcovonly', 'html'],
		logging: 'error',
		entryFilter: (entry) => new URL(entry.url).pathname.startsWith('/_app/'),
		sourceFilter: (sourcePath) =>
			!sourcePath.includes('node_modules') && APP_SOURCE.test(sourcePath),
		sourcePath: repositoryPath
	};
}
