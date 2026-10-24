import { describe, expect, it } from 'vitest';

import {
	nowPlayingFromLabel,
	nowPlayingOpenSourceLabel,
	nowPlayingSheetCloseLabel,
	nowPlayingTakeLabel,
	nowPlayingTakeMeta,
	openVersionLabel,
	takeBatchReductionLabel,
	bulkDeleteLabel,
	bulkDeleteTitle,
	selectedCountLabel,
	currentVersionHeadLabel,
	foldedGroupLabel,
	takeVersion
} from './now-playing';

describe('nowPlayingTakeLabel', () => {
	it('names the version and the take', () => {
		expect(nowPlayingTakeLabel(1, 3)).toBe('v1 · take 3');
	});

	it('names only the take when the row carries no version', () => {
		expect(nowPlayingTakeLabel(null, 3)).toBe('take 3');
	});
});

describe('currentVersionHeadLabel (rule 1, cells 1/9)', () => {
	it.each([
		{ versionNumber: 6, count: 3, label: 'v6 current · 3 takes' },
		{ versionNumber: 3, count: 1, label: 'v3 current · 1 take' },
		{ versionNumber: 3, count: 0, label: 'v3 current · 0 takes' }
	])('names the head "$label"', ({ versionNumber, count, label }) => {
		expect(currentVersionHeadLabel(versionNumber, count)).toBe(label);
	});
});

describe('foldedGroupLabel (rules 2 and 5, cells 1/8)', () => {
	it.each([
		{ versionNumber: 5, count: 5, archived: 2, label: 'v5 · 5 takes · 2 archived' },
		{ versionNumber: 4, count: 3, archived: 3, label: 'v4 · 3 takes · all archived' },
		{ versionNumber: 2, count: 4, archived: 0, label: 'v2 · 4 takes' },
		{ versionNumber: 2, count: 1, archived: 0, label: 'v2 · 1 take' },
		{ versionNumber: null, count: 2, archived: 0, label: 'Imported · 2 takes' }
	])('names the row "$label"', ({ versionNumber, count, archived, label }) => {
		expect(foldedGroupLabel(versionNumber, count, archived)).toBe(label);
	});
});

describe('takeVersion', () => {
	it('opens the version a generated take came from', () => {
		expect(takeVersion('ver-5', 5)).toEqual({ versionId: 'ver-5', versionNumber: 5 });
	});

	it.each([
		{ versionId: null, versionNumber: null },
		{ versionId: 'ver-5', versionNumber: null },
		{ versionId: null, versionNumber: 5 }
	])('treats a take missing its version as imported ($versionId, $versionNumber)', (fields) => {
		expect(takeVersion(fields.versionId, fields.versionNumber)).toBeNull();
	});
});

describe('openVersionLabel', () => {
	it('names the version the link opens', () => {
		expect(openVersionLabel(5)).toBe('Open v5');
	});
});

describe('nowPlayingTakeMeta', () => {
	// #163/5: the playlist row wrote its separators in markup, where the one
	// before the duration sat at the start of an {#if} and lost its leading
	// space — "Fable · v1 · take 1· 3:15".
	const cases = [
		{
			name: 'artist, take and duration',
			parts: { artist: 'Fable', versionNumber: 1, generationNumber: 1, durationSec: 195 },
			line: 'Fable · v1 · take 1 · 3:15'
		},
		{
			name: 'no duration on a take that has none',
			parts: { artist: 'Fable', versionNumber: 1, generationNumber: 1, durationSec: null },
			line: 'Fable · v1 · take 1'
		},
		{
			name: 'no duration on a zero-length take',
			parts: { artist: 'Fable', versionNumber: 2, generationNumber: 4, durationSec: 0 },
			line: 'Fable · v2 · take 4'
		},
		{
			name: 'no version on a library-pool take',
			parts: { artist: 'Fable', versionNumber: null, generationNumber: 7, durationSec: 61 },
			line: 'Fable · take 7 · 1:01'
		},
		{
			name: 'no artist',
			parts: { artist: null, versionNumber: 1, generationNumber: 1, durationSec: 195 },
			line: 'v1 · take 1 · 3:15'
		}
	];

	it.each(cases)('writes $name', ({ parts, line }) => {
		expect(nowPlayingTakeMeta(parts)).toBe(line);
	});
});

describe('takeBatchReductionLabel', () => {
	it('names both numbers when the server delivered fewer takes than asked', () => {
		expect(takeBatchReductionLabel({ batch_size: 2, delivered_batch_size: 1 })).toBe('1 of 2');
	});

	it('shows nothing when delivered matches requested', () => {
		expect(takeBatchReductionLabel({ batch_size: 2, delivered_batch_size: 2 })).toBeNull();
	});

	it('shows nothing without a requested batch size on record', () => {
		expect(takeBatchReductionLabel({ delivered_batch_size: 1 })).toBeNull();
	});

	it('shows nothing without a worker-reported delivered batch size', () => {
		expect(takeBatchReductionLabel({ batch_size: 2 })).toBeNull();
	});

	it('shows nothing for a take with no generation_params at all', () => {
		expect(takeBatchReductionLabel(null)).toBeNull();
	});
});

describe('the names Now Playing gives its ways out (#1052)', () => {
	it('closes the sheet by its own name, never as ×', () => {
		expect(nowPlayingSheetCloseLabel('Now Playing panel')).toBe('Close Now Playing panel');
	});

	it('says where the music comes from', () => {
		expect(nowPlayingFromLabel('Nightdrive')).toBe('from Nightdrive');
	});

	it.each([
		{ kind: 'album' as const, title: 'Nightdrive', label: 'from Nightdrive — open album' },
		{
			kind: 'playlist' as const,
			title: 'Late Drives',
			label: 'from Late Drives — open playlist'
		}
	])('names opening the $kind, starting with the text it shows', ({ kind, title, label }) => {
		expect(nowPlayingOpenSourceLabel(kind, title)).toBe(label);
	});
});

describe('bulk delete copy', () => {
	it.each([
		{ count: 1, title: 'Delete 1 take?' },
		{ count: 3, title: 'Delete 3 takes?' }
	])('asks "$title" for $count ticked', ({ count, title }) => {
		expect(bulkDeleteTitle(count)).toBe(title);
	});

	it('counts the ticked takes the same in the button and the readout', () => {
		expect([bulkDeleteLabel(3), selectedCountLabel(3)]).toEqual(['Delete 3', '3 selected']);
	});
});
