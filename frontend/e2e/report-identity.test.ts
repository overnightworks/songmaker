// @vitest-environment node
import { execFile } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import type { JSONReport, JSONReportSpec, JSONReportSuite } from '@playwright/test/reporter';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { compareReportIdentity } from './report-identity.ts';

const run = promisify(execFile);
const FRONTEND = fileURLToPath(new URL('..', import.meta.url));
const PLAYWRIGHT_CLI = path.join(FRONTEND, 'node_modules/@playwright/test/cli.js');
const SCRIPT = path.join(FRONTEND, 'e2e/report-identity.ts');
const SHARDS = 4;
const OWN = 'alpha';
const OTHER = 'beta';

// Two projects over four spec files; no test uses a browser fixture.
const SPEC_FILES: Record<string, string> = {
	'a.spec.ts': `import { test, expect } from '@playwright/test';
test('steady', () => {});
test('fails once', ({}, info) => { expect(info.retry).toBe(1); });`,
	'b.spec.ts': `import { test } from '@playwright/test';
test.skip('never runs', () => {});
test('second file', () => {});`,
	'c.spec.ts': `import { test } from '@playwright/test';
test('third file', () => {});`,
	'd.spec.ts': `import { test } from '@playwright/test';
test.describe('group', () => { test('nested', () => {}); });`
};
const CONFIG = `export default {
	testDir: '.', retries: 1, workers: 1, fullyParallel: false,
	projects: [{ name: '${OWN}' }, { name: '${OTHER}' }]
};`;

let scratch: string;
let listing: JSONReport;
let ownReports: JSONReport[];
let otherShardTwo: JSONReport;
let ownReportFiles: string[];
let listingFile: string;

async function playwright(args: string[], reportFile?: string): Promise<string> {
	const { stdout } = await run(process.execPath, [PLAYWRIGHT_CLI, 'test', ...args], {
		cwd: scratch,
		env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_FILE: reportFile ?? '' },
		maxBuffer: 64 * 1024 * 1024
	});
	return stdout;
}

async function runShard(project: string, shard: number): Promise<string> {
	const reportFile = path.join(scratch, `${project}-${shard}.json`);
	await playwright(
		[
			`--project=${project}`,
			`--shard=${shard}/${SHARDS}`,
			'--reporter=json',
			`--output=${path.join(scratch, `${project}-${shard}-results`)}`
		],
		reportFile
	);
	return reportFile;
}

function readReport(file: string): JSONReport {
	return JSON.parse(readFileSync(file, 'utf8')) as JSONReport;
}

beforeAll(async () => {
	scratch = mkdtempSync(path.join(tmpdir(), 'report-identity-'));
	symlinkSync(path.join(FRONTEND, 'node_modules'), path.join(scratch, 'node_modules'));
	writeFileSync(path.join(scratch, 'package.json'), '{"type":"module"}');
	writeFileSync(path.join(scratch, 'playwright.config.ts'), CONFIG);
	for (const [name, source] of Object.entries(SPEC_FILES)) {
		writeFileSync(path.join(scratch, name), source);
	}
	listingFile = path.join(scratch, 'listing.json');
	writeFileSync(listingFile, await playwright(['--list', '--reporter=json']));
	const shards = Array.from({ length: SHARDS }, (_, index) => index + 1);
	ownReportFiles = await Promise.all(shards.map((shard) => runShard(OWN, shard)));
	const otherFile = await runShard(OTHER, 2);
	listing = readReport(listingFile);
	ownReports = ownReportFiles.map(readReport);
	otherShardTwo = readReport(otherFile);
}, 120_000);

afterAll(() => rmSync(scratch, { recursive: true, force: true }));

function specsOf(suite: JSONReportSuite): JSONReportSpec[] {
	return [...suite.specs, ...(suite.suites ?? []).flatMap(specsOf)];
}

function specNamed(report: JSONReport, title: string): JSONReportSpec {
	const spec = report.suites.flatMap(specsOf).find((candidate) => candidate.title === title);
	if (!spec) {
		throw new Error(`The fixture report has no test titled ${title}`);
	}
	return spec;
}

function reportHolding(title: string): JSONReport {
	const holder = ownReports.find((report) =>
		report.suites.flatMap(specsOf).some((spec) => spec.title === title)
	);
	if (!holder) {
		throw new Error(`No shard of the fixture ran ${title}`);
	}
	return holder;
}

function cloneOfEach(): { listing: JSONReport; reports: JSONReport[] } {
	return { listing: structuredClone(listing), reports: structuredClone(ownReports) };
}

describe('the fixtures Playwright wrote', () => {
	it('hold one retry under one id and a skipped test with the listing expecting it', () => {
		expect(specNamed(reportHolding('fails once'), 'fails once').tests[0].results).toHaveLength(2);
		expect(specNamed(listing, 'never runs').tests[0].expectedStatus).toBe('skipped');
	});
});

describe('compareReportIdentity', () => {
	it('passes when the four shards together ran every listed test once, a retried test counting once', () => {
		expect(compareReportIdentity(OWN, listing, ownReports)).toEqual([]);
	});

	it('passes whatever the order of the reports', () => {
		expect(compareReportIdentity(OWN, listing, [...ownReports].reverse())).toEqual([]);
	});

	it('accepts a listed test without an attempt only because the listing expects it skipped', () => {
		const { reports } = cloneOfEach();
		specNamed(
			reports[ownReports.indexOf(reportHolding('never runs'))],
			'never runs'
		).tests[0].results = [];
		expect(compareReportIdentity(OWN, listing, reports)).toEqual([]);
	});

	type Case = {
		title: string;
		damage: (input: { listing: JSONReport; reports: JSONReport[] }) => void;
		cause: RegExp;
	};
	const refusals: Case[] = [
		{
			title: 'no report at all',
			damage: (input) => (input.reports = []),
			cause: /^no report was given$/m
		},
		{
			title: 'a report with errors',
			damage: ({ reports }) => (reports[0].errors = [{ message: 'worker crashed' }]),
			cause: /report 1.*errors.*worker crashed/is
		},
		{
			title: 'a report without suites',
			damage: ({ reports }) => delete (reports[2] as Partial<JSONReport>).suites,
			cause: /report 3.*no suites/i
		},
		{
			title: 'a report without its shard',
			damage: ({ reports }) => delete (reports[1].config as Partial<JSONReport['config']>).shard,
			cause: /report 2.*no shard/i
		},
		{
			title: 'a report with another total than the others',
			damage: ({ reports }) => (reports[3].config.shard = { current: 4, total: 5 }),
			cause: /number of shards.*4.*5/i
		},
		{
			title: 'a shard index twice',
			damage: ({ reports }) => (reports[1] = structuredClone(reports[0])),
			cause: /shard 1\/4.*twice/i
		},
		{
			title: 'a shard index missing',
			damage: ({ reports }) => reports.splice(3, 1),
			cause: /shard 4\/4.*missing/i
		},
		{
			title: 'a test of another project',
			damage: ({ reports }) => (reports[1] = otherShardTwo),
			cause: new RegExp(`project ${OTHER}`, 'i')
		},
		{
			title: 'a listed id that is in no report',
			damage: ({ reports }) => {
				const file = reports[2].suites[0];
				file.specs = file.specs.filter((spec) => spec.title !== 'third file');
			},
			cause: /third file.*in no report/is
		},
		{
			title: 'an id in a report that the listing does not have',
			damage: ({ listing: input }) => {
				const file = input.suites.find((suite) => suite.file === 'c.spec.ts');
				if (file) file.specs = [];
			},
			cause: /third file.*not in the listing/is
		},
		{
			title: 'an id in two reports',
			damage: ({ reports }) => reports[1].suites.push(structuredClone(reports[2].suites[0])),
			cause: /third file.*in 2 reports/is
		},
		{
			title: 'an empty listing',
			damage: ({ listing: input }) => (input.suites = []),
			cause: /listing.*no test/i
		},
		{
			title: 'a listed test with no attempt that the listing does not expect skipped',
			damage: ({ reports }) => {
				specNamed(reports[2], 'third file').tests[0].results = [];
			},
			cause: /third file.*no attempt/is
		}
	];

	it.each(refusals)('refuses $title and names the cause', ({ damage, cause }) => {
		const input = cloneOfEach();
		damage(input);
		const problems = compareReportIdentity(OWN, input.listing, input.reports);
		expect(problems.join('\n')).toMatch(cause);
	});

	it('refuses reports of another project than the one named', () => {
		const problems = compareReportIdentity(OTHER, listing, ownReports);
		expect(problems.join('\n')).toMatch(new RegExp(`project ${OWN}`, 'i'));
	});

	it('names a test by its title path', () => {
		const { reports } = cloneOfEach();
		specNamed(reports[3], 'nested').tests[0].results = [];
		expect(compareReportIdentity(OWN, listing, reports).join('\n')).toContain(
			'd.spec.ts › group › nested'
		);
	});
});

describe('the script form', () => {
	function script(...args: string[]): Promise<{ code: number; output: string }> {
		return run(process.execPath, [SCRIPT, ...args]).then(
			({ stdout, stderr }) => ({ code: 0, output: stdout + stderr }),
			(failure: { code: number; stdout: string; stderr: string }) => ({
				code: failure.code,
				output: failure.stdout + failure.stderr
			})
		);
	}

	it('exits zero for the four shards of a project', async () => {
		expect((await script(OWN, listingFile, ...ownReportFiles)).code).toBe(0);
	});

	it('exits non-zero and prints the title path of what is missing', async () => {
		const { code, output } = await script(OWN, listingFile, ...ownReportFiles.slice(0, 3));
		expect(code).not.toBe(0);
		expect(output).toContain('d.spec.ts › group › nested');
	});

	it('exits non-zero for a report that cannot be parsed', async () => {
		const broken = path.join(scratch, 'broken.json');
		writeFileSync(broken, readFileSync(ownReportFiles[0], 'utf8').slice(0, 100));
		const { code, output } = await script(OWN, listingFile, broken, ...ownReportFiles.slice(1));
		expect(code).not.toBe(0);
		expect(output).toContain(broken);
	});

	it('exits non-zero without any report', async () => {
		expect((await script(OWN, listingFile)).code).not.toBe(0);
	});
});
