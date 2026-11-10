// Proves by identity that the shards of one Playwright project together ran
// every test the project lists, each exactly once: the ids in the shards'
// JSON reports, retries collapsed, equal the ids of `--list --reporter=json`.
// Usage: node e2e/report-identity.ts <project> <listing.json> <report.json>...

import { readFileSync } from 'node:fs';
import type { JSONReport, JSONReportSpec, JSONReportSuite } from '@playwright/test/reporter';

type TestEntry = {
	id: string;
	titlePath: string;
	projectName: string;
	attempts: number;
	expectedStatus: string;
};

type ShardPosition = { current: number; total: number };

const TITLE_SEPARATOR = ' › ';

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describeTest(entry: TestEntry): string {
	return `${entry.titlePath} (${entry.id})`;
}

// What is read from disk is external input: every field used is checked here.
function entriesOfSpec(spec: JSONReportSpec, parentTitles: string[]): TestEntry[] {
	if (typeof spec.id !== 'string' || typeof spec.title !== 'string' || !Array.isArray(spec.tests)) {
		throw new Error('a spec lacks its id, title or tests');
	}
	const titlePath = [...parentTitles, spec.title].join(TITLE_SEPARATOR);
	return spec.tests.map((test) => {
		if (
			typeof test.projectName !== 'string' ||
			typeof test.expectedStatus !== 'string' ||
			!Array.isArray(test.results)
		) {
			throw new Error(`the test ${titlePath} lacks its project, expected status or results`);
		}
		return {
			id: spec.id,
			titlePath,
			projectName: test.projectName,
			attempts: test.results.length,
			expectedStatus: test.expectedStatus
		};
	});
}

function entriesOfSuite(suite: JSONReportSuite, parentTitles: string[]): TestEntry[] {
	if (!isRecord(suite) || typeof suite.title !== 'string' || !Array.isArray(suite.specs)) {
		throw new Error('a suite lacks its title or specs');
	}
	const titles = [...parentTitles, suite.title];
	return [
		...suite.specs.flatMap((spec) => entriesOfSpec(spec, titles)),
		...(suite.suites ?? []).flatMap((child) => entriesOfSuite(child, titles))
	];
}

function entriesOf(document: Record<string, unknown>): TestEntry[] {
	return (document.suites as JSONReportSuite[]).flatMap((suite) => entriesOfSuite(suite, []));
}

function hasSuites(document: unknown): document is Record<string, unknown> {
	return isRecord(document) && Array.isArray(document.suites);
}

function shardOf(report: Record<string, unknown>): ShardPosition | undefined {
	const config = report.config;
	const shard = isRecord(config) ? config.shard : undefined;
	if (
		isRecord(shard) &&
		Number.isInteger(shard.current) &&
		Number.isInteger(shard.total) &&
		(shard.current as number) >= 1 &&
		(shard.current as number) <= (shard.total as number)
	) {
		return { current: shard.current as number, total: shard.total as number };
	}
	return undefined;
}

type ReadReport = { label: string; entries: TestEntry[]; shard: ShardPosition | undefined };

// A report that errored or has no suites is refused and contributes no tests.
function readReport(report: unknown, label: string, problems: string[]): ReadReport | undefined {
	if (!hasSuites(report)) {
		problems.push(`${label} has no suites`);
		return undefined;
	}
	const errors = Array.isArray(report.errors) ? (report.errors as JSONReport['errors']) : [];
	if (errors.length > 0) {
		problems.push(`${label} has errors: ${errors.map((error) => error.message).join('; ')}`);
	}
	const shard = shardOf(report);
	if (!shard) {
		problems.push(`${label} has no shard`);
	}
	try {
		return { label, entries: entriesOf(report), shard };
	} catch (failure) {
		problems.push(`${label} is malformed: ${(failure as Error).message}`);
		return undefined;
	}
}

function checkShards(reads: ReadReport[], problems: string[]): void {
	const positions = reads.flatMap((read) =>
		read.shard ? [{ label: read.label, ...read.shard }] : []
	);
	const totals = [...new Set(positions.map((position) => position.total))];
	if (totals.length > 1) {
		problems.push(`the reports disagree on the number of shards: ${totals.join(', ')}`);
		return;
	}
	if (totals.length === 0) {
		return;
	}
	const [total] = totals;
	for (let current = 1; current <= total; current++) {
		const holders = positions.filter((position) => position.current === current);
		if (holders.length === 0) {
			problems.push(`shard ${current}/${total} is missing`);
		} else if (holders.length > 1) {
			problems.push(
				`shard ${current}/${total} appears twice: ${holders.map((holder) => holder.label).join(', ')}`
			);
		}
	}
}

function listedTests(
	listing: unknown,
	project: string,
	problems: string[]
): Map<string, TestEntry> {
	const listed = new Map<string, TestEntry>();
	if (!hasSuites(listing)) {
		problems.push('the listing has no suites');
		return listed;
	}
	try {
		for (const entry of entriesOf(listing)) {
			if (entry.projectName === project) {
				listed.set(entry.id, entry);
			}
		}
	} catch (failure) {
		problems.push(`the listing is malformed: ${(failure as Error).message}`);
		return listed;
	}
	if (listed.size === 0) {
		problems.push(`the listing has no test of project ${project}`);
	}
	return listed;
}

function checkTests(
	project: string,
	listed: Map<string, TestEntry>,
	reads: ReadReport[],
	problems: string[]
): void {
	const seen = new Map<string, { entry: TestEntry; labels: string[] }>();
	for (const read of reads) {
		for (const entry of read.entries) {
			if (entry.projectName !== project) {
				problems.push(
					`${read.label}: ${describeTest(entry)} belongs to project ${entry.projectName}, not ${project}`
				);
				continue;
			}
			const known = seen.get(entry.id);
			if (known) {
				known.labels.push(read.label);
			} else {
				seen.set(entry.id, { entry, labels: [read.label] });
			}
		}
	}
	for (const [id, { entry, labels }] of seen) {
		const listedEntry = listed.get(id);
		if (!listedEntry) {
			problems.push(`${describeTest(entry)} is in ${labels.join(', ')} but not in the listing`);
		} else if (labels.length > 1) {
			problems.push(`${describeTest(entry)} is in ${labels.length} reports: ${labels.join(', ')}`);
		} else if (entry.attempts === 0 && listedEntry.expectedStatus !== 'skipped') {
			problems.push(`${describeTest(entry)} has no attempt in ${labels[0]}`);
		}
	}
	for (const [id, entry] of listed) {
		if (!seen.has(id)) {
			problems.push(`${describeTest(entry)} is listed but in no report`);
		}
	}
}

// Returns every problem found; an empty list means the shards ran exactly the
// project's listed tests.
export function compareReportIdentity(
	project: string,
	listing: unknown,
	reports: readonly unknown[]
): string[] {
	const problems: string[] = [];
	const listed = listedTests(listing, project, problems);
	if (reports.length === 0) {
		problems.push('no report was given');
		return problems;
	}
	const reads = reports.flatMap(
		(report, index) => readReport(report, `report ${index + 1}`, problems) ?? []
	);
	checkShards(reads, problems);
	checkTests(project, listed, reads, problems);
	return problems;
}

function parseFile(file: string, failures: string[]): unknown {
	try {
		return JSON.parse(readFileSync(file, 'utf8'));
	} catch (failure) {
		failures.push(`${file} cannot be read as JSON: ${(failure as Error).message}`);
		return undefined;
	}
}

function main(): void {
	const [project, listingFile, ...reportFiles] = process.argv.slice(2);
	if (!project || !listingFile) {
		console.error('Usage: node e2e/report-identity.ts <project> <listing.json> <report.json>...');
		process.exit(2);
	}
	const failures: string[] = [];
	const listing = parseFile(listingFile, failures);
	const reports = reportFiles.map((file) => parseFile(file, failures));
	const problems =
		failures.length > 0 ? failures : compareReportIdentity(project, listing, reports);
	for (const problem of problems) {
		console.error(problem);
	}
	if (problems.length > 0) {
		process.exit(1);
	}
	console.log(`Project ${project}: ${reportFiles.length} reports hold exactly the listed tests.`);
}

if (import.meta.main) {
	main();
}
