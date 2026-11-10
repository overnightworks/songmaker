import { describe, expect, it } from 'vitest';

import type { JobItem } from '#lib/api/types.ts';
import {
	coverBusyWaitSeconds,
	coverProblemClosesSuggest,
	coverRefusalProblem,
	coverRunProblem
} from './cover-problem';

const ENDED_AT = Date.parse('2026-11-05T12:00:00Z');

function endedRun(overrides: Partial<JobItem> = {}): JobItem {
	return {
		id: 'cover-run',
		type: 'cover',
		status: 'failed',
		progress: 0,
		completed_at: new Date(ENDED_AT).toISOString(),
		...overrides
	};
}

const FOLLOWED = { followed: true };
const FROM_BEFORE = { followed: false };

describe('the problem a cover run ended with', () => {
	it.each([
		['unavailable', 'unavailable'],
		['budget_spent', 'budget_spent'],
		['timeout', 'unavailable'],
		[null, 'unavailable']
	] as const)('reads a run that failed with %s as %s', (errorType, problem) => {
		expect(coverRunProblem(endedRun({ error_type: errorType }), FROM_BEFORE, ENDED_AT)).toBe(
			problem
		);
	});

	it.each(['not_enabled', 'sign_in_again'] as const)(
		'shows %s only for the run this page followed, so the next load opens Suggest',
		(problem) => {
			const run = endedRun({ error_type: problem });
			expect(coverRunProblem(run, FOLLOWED, ENDED_AT)).toBe(problem);
			expect(coverRunProblem(run, FROM_BEFORE, ENDED_AT)).toBeNull();
		}
	);

	it('shows busy while the wait it was given lasts, on any load, and nothing after', () => {
		const run = endedRun({ error_type: 'busy', retry_after_seconds: 42 });
		expect(coverRunProblem(run, FROM_BEFORE, ENDED_AT + 41_000)).toBe('busy');
		expect(coverRunProblem(run, FROM_BEFORE, ENDED_AT + 42_000)).toBeNull();
	});

	it.each(['completed', 'running', 'cancelled'])('names no problem for a %s run', (status) => {
		expect(
			coverRunProblem(endedRun({ status, error_type: 'busy' }), FOLLOWED, ENDED_AT)
		).toBeNull();
	});
});

describe('the busy wait', () => {
	it('counts down from the end of the run plus the wait it was given', () => {
		const run = endedRun({ error_type: 'busy', retry_after_seconds: 42 });
		expect(coverBusyWaitSeconds(run, ENDED_AT)).toBe(42);
		expect(coverBusyWaitSeconds(run, ENDED_AT + 500)).toBe(42);
		expect(coverBusyWaitSeconds(run, ENDED_AT + 41_500)).toBe(1);
		expect(coverBusyWaitSeconds(run, ENDED_AT + 60_000)).toBe(0);
	});

	it('never waits longer than the wait it was given, whatever the clock says', () => {
		const run = endedRun({ error_type: 'busy', retry_after_seconds: 42 });
		expect(coverBusyWaitSeconds(run, ENDED_AT - 3_600_000)).toBe(42);
	});

	it.each([
		['a run with no wait', endedRun({ error_type: 'busy' })],
		['a run that was not busy', endedRun({ error_type: 'unavailable', retry_after_seconds: 42 })],
		['no run', null]
	])('waits for nothing after %s', (_name, run) => {
		expect(coverBusyWaitSeconds(run, ENDED_AT)).toBe(0);
	});
});

describe('a refusal at the click', () => {
	it.each(['unavailable', 'busy', 'budget_spent', 'not_enabled', 'sign_in_again'] as const)(
		'reads the problem %s from the refusal body',
		(problem) => {
			expect(coverRefusalProblem({ problem })).toBe(problem);
		}
	);

	it.each([
		['a sentence', 'Cover suggestions need a browser login.'],
		['an unknown problem', { problem: 'gone' }],
		['nothing', null]
	])('names no problem for %s', (_name, detail) => {
		expect(coverRefusalProblem(detail)).toBeNull();
	});
});

describe('what each problem does to Suggest', () => {
	it.each([
		['busy', true],
		['not_enabled', true],
		['sign_in_again', true],
		['unavailable', false],
		['budget_spent', false]
	] as const)('%s closes Suggest: %s', (problem, closes) => {
		expect(coverProblemClosesSuggest(problem)).toBe(closes);
	});
});
