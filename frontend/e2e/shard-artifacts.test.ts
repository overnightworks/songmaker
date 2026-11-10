// @vitest-environment node
import { execFile } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { chooseNewestAttempts } from './shard-artifacts.ts';

const run = promisify(execFile);
const SCRIPT = fileURLToPath(new URL('./shard-artifacts.ts', import.meta.url));
const PREFIX = 'report';
const PROJECT = 'alpha';
const TOTAL = 4;

function choose(...names: string[]) {
	return chooseNewestAttempts(names, { prefix: PREFIX, project: PROJECT, total: TOTAL });
}

describe('the newest attempt per shard', () => {
	it('is the highest attempt present, compared as a number', () => {
		const { chosen, problems } = choose(
			'report-alpha-1-1',
			'report-alpha-1-2',
			'report-alpha-2-9',
			'report-alpha-2-10',
			'report-alpha-3-1',
			'report-alpha-4-3'
		);
		expect(chosen).toEqual([
			'report-alpha-1-2',
			'report-alpha-2-10',
			'report-alpha-3-1',
			'report-alpha-4-3'
		]);
		expect(problems).toEqual([]);
	});

	it('does not need any particular attempt, nor the same one for every shard', () => {
		const { chosen, problems } = choose(
			'report-alpha-4-7',
			'report-alpha-3-1',
			'report-alpha-2-5',
			'report-alpha-1-2'
		);
		expect(chosen).toEqual([
			'report-alpha-1-2',
			'report-alpha-2-5',
			'report-alpha-3-1',
			'report-alpha-4-7'
		]);
		expect(problems).toEqual([]);
	});

	it('names a shard without any attempt and still chooses for the others', () => {
		const { chosen, problems } = choose('report-alpha-1-1', 'report-alpha-2-1', 'report-alpha-4-2');
		expect(chosen).toEqual(['report-alpha-1-1', 'report-alpha-2-1', 'report-alpha-4-2']);
		expect(problems).toHaveLength(1);
		expect(problems[0]).toMatch(/shard 3\/4/);
	});

	it('names every shard when nothing was downloaded', () => {
		const { chosen, problems } = choose();
		expect(chosen).toEqual([]);
		expect(problems).toHaveLength(TOTAL);
	});

	const foreign = [
		{ title: 'another project', name: 'report-beta-2-1' },
		{ title: 'another artifact kind', name: 'store-alpha-2-1' },
		{ title: 'a shard beyond the total', name: 'report-alpha-5-1' },
		{ title: 'shard zero', name: 'report-alpha-0-1' },
		{ title: 'a shard with a leading zero', name: 'report-alpha-02-1' },
		{ title: 'an attempt of zero', name: 'report-alpha-2-0' },
		{ title: 'no attempt', name: 'report-alpha-2' },
		{ title: 'a trailing part', name: 'report-alpha-2-1-extra' },
		{ title: 'a longer project name', name: 'report-alpha-beta-2-1' },
		{ title: 'a stray prefix', name: 'old-report-alpha-2-1' }
	];

	it.each(foreign)('refuses $title, names it, and does not count it for a shard', ({ name }) => {
		const { chosen, problems } = choose(
			'report-alpha-1-1',
			name,
			'report-alpha-3-1',
			'report-alpha-4-1'
		);
		expect(chosen).toEqual(['report-alpha-1-1', 'report-alpha-3-1', 'report-alpha-4-1']);
		expect(problems.some((problem) => problem.includes(name))).toBe(true);
		expect(problems.some((problem) => /shard 2\/4/.test(problem))).toBe(true);
	});
});

describe('the command', () => {
	let downloads: string;

	beforeEach(() => {
		downloads = mkdtempSync(path.join(tmpdir(), 'shard-artifacts-'));
	});
	afterEach(() => {
		rmSync(downloads, { recursive: true, force: true });
	});

	function artifact(name: string): void {
		mkdirSync(path.join(downloads, name));
	}

	async function command(directory = downloads) {
		return run(process.execPath, [SCRIPT, PREFIX, PROJECT, String(TOTAL), directory]).then(
			({ stdout, stderr }) => ({ code: 0, stdout, stderr }),
			(failure: { code: number; stdout: string; stderr: string }) => failure
		);
	}

	it('prints the directory of the newest attempt of every shard in shard order', async () => {
		for (const name of ['4-1', '1-1', '1-2', '2-1', '3-2', '3-1']) {
			artifact(`report-alpha-${name}`);
		}
		const { code, stdout } = await command();
		expect(code).toBe(0);
		expect(stdout.split('\n').filter(Boolean)).toEqual(
			['1-2', '2-1', '3-2', '4-1'].map((shard) => path.join(downloads, `report-alpha-${shard}`))
		);
	});

	it('fails on a shard without any attempt after printing the others', async () => {
		for (const name of ['1-1', '2-1', '4-1']) {
			artifact(`report-alpha-${name}`);
		}
		const { code, stdout, stderr } = await command();
		expect(code).toBe(1);
		expect(stdout.split('\n').filter(Boolean)).toHaveLength(3);
		expect(stderr).toMatch(/shard 3\/4/);
	});

	it('fails on every shard when the directory does not exist', async () => {
		const { code, stdout, stderr } = await command(path.join(downloads, 'missing'));
		expect(code).toBe(1);
		expect(stdout).toBe('');
		expect(stderr).toMatch(/shard 1\/4[\s\S]*shard 4\/4/);
	});

	it('refuses a call without its arguments', async () => {
		const { code, stderr } = await run(process.execPath, [SCRIPT]).then(
			() => ({ code: 0, stderr: '' }),
			(failure: { code: number; stderr: string }) => failure
		);
		expect(code).toBe(2);
		expect(stderr).toMatch(/Usage/);
	});
});
