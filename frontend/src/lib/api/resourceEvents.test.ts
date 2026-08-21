import { describe, expect, it } from 'vitest';

import {
	compareDecimalId,
	parseGenerationCreated,
	parseResourceHello,
	parseResourceResync
} from './resourceEvents';

describe('compareDecimalId', () => {
	it('orders BIGINT decimal strings without number coercion', () => {
		expect(compareDecimalId('9', '10')).toBeLessThan(0);
		expect(compareDecimalId('10', '9')).toBeGreaterThan(0);
		expect(compareDecimalId('9007199254740993', '9007199254740992')).toBeGreaterThan(0);
		expect(compareDecimalId('9007199254740993', '9007199254740993')).toBe(0);
	});
});

describe('parseResourceHello', () => {
	it('parses a decimal high-water mark', () => {
		expect(parseResourceHello('{"high_water_mark":"4"}')).toEqual({ high_water_mark: '4' });
	});

	it('rejects numeric high-water marks', () => {
		expect(() => parseResourceHello('{"high_water_mark":4}')).toThrow(
			/Malformed resource event field: high_water_mark/
		);
	});

	it('rejects malformed payloads', () => {
		expect(() => parseResourceHello('not-json')).toThrow(/Malformed resource event: hello/);
	});
});

describe('parseResourceResync', () => {
	it('parses a decimal high-water mark', () => {
		expect(parseResourceResync('{"high_water_mark":"12"}')).toEqual({ high_water_mark: '12' });
	});
});

describe('parseGenerationCreated', () => {
	it('parses a generation.created frame without a user id', () => {
		expect(
			parseGenerationCreated(
				JSON.stringify({
					kind: 'generation.created',
					sequence: '5',
					resource_type: 'song',
					resource_id: 's1',
					generation_id: 'g1',
					created_at: '2026-01-01T00:00:00+00:00'
				})
			)
		).toEqual({
			kind: 'generation.created',
			sequence: '5',
			resource_type: 'song',
			resource_id: 's1',
			generation_id: 'g1',
			created_at: '2026-01-01T00:00:00+00:00'
		});
	});

	it('ignores a forbidden user id field instead of requiring it', () => {
		const parsed = parseGenerationCreated(
			JSON.stringify({
				kind: 'generation.created',
				sequence: '1',
				resource_type: 'song',
				resource_id: 's1',
				generation_id: 'g1',
				created_at: 't',
				user_id: 'u1'
			})
		);
		expect(parsed).not.toHaveProperty('user_id');
		expect(parsed.resource_id).toBe('s1');
	});

	it('rejects missing fields instead of skipping the frame', () => {
		expect(() => parseGenerationCreated('{"kind":"generation.created","sequence":"1"}')).toThrow(
			/Malformed resource event field/
		);
	});
});
