// @vitest-environment node
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { MCR } from 'monocart-coverage-reports';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { collectionTimeFile, coverageOptions, coverageStoreDir } from './coverage-options.ts';
import { summarizeCoverage } from './coverage-summary.ts';

const PROJECT = 'desktop';
const SOURCE = 'function alpha() {}\nfunction beta() {}\n';
const FUNCTIONS = ['alpha', 'beta'] as const;
type FunctionName = (typeof FUNCTIONS)[number];

let scratch: string;
beforeEach(() => {
	scratch = mkdtempSync(path.join(tmpdir(), 'coverage-summary-'));
});
afterEach(() => rmSync(scratch, { recursive: true, force: true }));

function rootNamed(name: string): string {
	return path.join(scratch, name);
}

// The collector writes the store itself: one page that ran only `called`.
async function writeStore(root: string, called: readonly FunctionName[]): Promise<void> {
	const functionRange = (name: FunctionName) => {
		const startOffset = SOURCE.indexOf(`function ${name}`);
		const endOffset = SOURCE.indexOf('\n', startOffset);
		return { startOffset, endOffset, count: called.includes(name) ? 1 : 0 };
	};
	const entry = {
		url: 'http://localhost/_app/immutable/src/module.js',
		source: SOURCE,
		functions: [
			{
				functionName: '',
				isBlockCoverage: true,
				ranges: [{ startOffset: 0, endOffset: SOURCE.length, count: 1 }]
			},
			...FUNCTIONS.map((name) => ({
				functionName: name,
				isBlockCoverage: true,
				ranges: [functionRange(name)]
			}))
		]
	};
	await MCR(coverageOptions(PROJECT, [], root)).add([entry]);
}

function writeTimes(root: string, milliseconds: readonly number[]): void {
	const timeFile = collectionTimeFile(PROJECT, root);
	mkdirSync(path.dirname(timeFile), { recursive: true });
	appendFileSync(timeFile, milliseconds.map((ms) => `${ms}\n`).join(''));
}

describe('summarizeCoverage', () => {
	it.each([
		{ title: 'one store alone', own: ['alpha'], extra: [] },
		{ title: 'two roots covering different functions', own: [], extra: [['alpha'], ['beta']] },
		{ title: 'the own store and one root', own: ['alpha'], extra: [['beta']] }
	] as { title: string; own: FunctionName[]; extra: FunctionName[][] }[])(
		'$title gives the functions any store covered',
		async ({ own, extra }) => {
			const ownRoot = rootNamed('own');
			await writeStore(ownRoot, own);
			writeTimes(ownRoot, [1]);
			const extraRoots: string[] = [];
			for (const [index, called] of extra.entries()) {
				const root = rootNamed(`extra-${index}`);
				await writeStore(root, called);
				writeTimes(root, [1]);
				extraRoots.push(root);
			}

			const figures = await summarizeCoverage(PROJECT, extraRoots, ownRoot);

			const union = new Set([...own, ...extra.flat()]);
			expect(figures.functions.covered).toBe(union.size);
			expect(figures.functions.total).toBe(FUNCTIONS.length);
		}
	);

	it('merges more than either store alone covers', async () => {
		const alone = rootNamed('alone');
		const first = rootNamed('first');
		const second = rootNamed('second');
		for (const [root, called] of [
			[alone, ['alpha']],
			[first, ['alpha']],
			[second, ['beta']]
		] as const) {
			await writeStore(root, called);
			writeTimes(root, [1]);
		}

		const single = await summarizeCoverage(PROJECT, [], alone);
		const together = await summarizeCoverage(PROJECT, [first, second], rootNamed('merged'));

		expect(together.functions.covered).toBeGreaterThan(single.functions.covered);
	});

	it('sums the time files of the own root and every extra root', async () => {
		const ownRoot = rootNamed('own');
		const extraRoot = rootNamed('extra');
		await writeStore(ownRoot, ['alpha']);
		await writeStore(extraRoot, ['beta']);
		writeTimes(ownRoot, [100, 200]);
		writeTimes(extraRoot, [300]);

		const figures = await summarizeCoverage(PROJECT, [extraRoot], ownRoot);

		expect(figures.collectionSeconds).toBeCloseTo(0.6);
	});

	it('hands the collector no inputDir without extra roots', () => {
		expect(coverageOptions(PROJECT)).not.toHaveProperty('inputDir');
		expect(coverageOptions(PROJECT, [])).not.toHaveProperty('inputDir');
	});

	it('keeps the own store out of the inputs', () => {
		const ownRoot = rootNamed('own');
		const extraRoot = rootNamed('extra');

		const { inputDir, outputDir } = coverageOptions(PROJECT, [extraRoot], ownRoot);

		expect(outputDir).toBe(coverageStoreDir(PROJECT, ownRoot));
		expect(inputDir).toEqual([path.join(coverageStoreDir(PROJECT, extraRoot), '.cache')]);
	});

	it('gives without extra roots the figures and lcov of the plain collector call', async () => {
		const summarized = rootNamed('summarized');
		const plain = rootNamed('plain');
		for (const root of [summarized, plain]) {
			await writeStore(root, ['alpha']);
			writeTimes(root, [5]);
		}

		const figures = await summarizeCoverage(PROJECT, [], summarized);
		const direct = await MCR(coverageOptions(PROJECT, [], plain)).generate();

		for (const kind of ['branches', 'lines', 'functions'] as const) {
			expect(figures[kind]).toEqual(direct?.summary[kind]);
		}
		const lcov = (root: string) =>
			readFileSync(path.join(coverageStoreDir(PROJECT, root), 'lcov.info'), 'utf8');
		expect(lcov(summarized)).toBe(lcov(plain));
	});

	it('throws on a missing own time file without extra roots', async () => {
		const ownRoot = rootNamed('own');
		await writeStore(ownRoot, ['alpha']);

		await expect(summarizeCoverage(PROJECT, [], ownRoot)).rejects.toThrow();
	});

	it('accepts a missing own time file with extra roots', async () => {
		const extraRoot = rootNamed('extra');
		await writeStore(extraRoot, ['alpha']);
		writeTimes(extraRoot, [250]);

		const figures = await summarizeCoverage(PROJECT, [extraRoot], rootNamed('own'));

		expect(figures.collectionSeconds).toBeCloseTo(0.25);
	});

	it('throws naming an extra root that has a time file but no store', async () => {
		const ownRoot = rootNamed('own');
		const typoRoot = rootNamed('typo');
		await writeStore(ownRoot, ['alpha']);
		writeTimes(ownRoot, [1]);
		writeTimes(typoRoot, [1]);

		await expect(summarizeCoverage(PROJECT, [typoRoot], ownRoot)).rejects.toThrow(typoRoot);
	});
});
