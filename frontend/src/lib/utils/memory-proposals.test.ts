import { describe, expect, it } from 'vitest';
import {
	collectPendingProposals,
	parseMemoryProposals,
	proposalKey,
	stripMemoryProposals
} from './memory-proposals';

const SAMPLE = `Keep the chorus.
<memory_proposal scope="song" target_id="s1">
<current>
open: bridge
</current>
<proposed>
locked: bridge stays short
open: outro
</proposed>
</memory_proposal>
Thanks.`;

describe('memory proposals', () => {
	it('parses scope, target, current, and proposed bodies', () => {
		const proposals = parseMemoryProposals(SAMPLE);
		expect(proposals).toHaveLength(1);
		expect(proposals[0]).toEqual({
			scope: 'song',
			targetId: 's1',
			currentBody: 'open: bridge',
			proposedBody: 'locked: bridge stays short\nopen: outro'
		});
	});

	it('strips proposal blocks from display text', () => {
		expect(stripMemoryProposals(SAMPLE)).toBe('Keep the chorus.\n\nThanks.');
	});

	it('parses a user-scope proposal without target_id', () => {
		const text = `<memory_proposal scope="user">
<current>
prefer German
</current>
<proposed>
prefer German, no auto-rhyme
</proposed>
</memory_proposal>`;
		expect(parseMemoryProposals(text)[0]).toEqual({
			scope: 'user',
			targetId: null,
			currentBody: 'prefer German',
			proposedBody: 'prefer German, no auto-rhyme'
		});
	});

	it('returns no proposals for ordinary assistant text', () => {
		expect(parseMemoryProposals('just a reply')).toEqual([]);
		expect(stripMemoryProposals('just a reply')).toBe('just a reply');
	});

	it('keeps visible proposals until accept or reject', () => {
		const pending = collectPendingProposals([SAMPLE], []);
		expect(pending).toHaveLength(1);
		const rejected = collectPendingProposals([SAMPLE], [proposalKey(pending[0])]);
		expect(rejected).toHaveLength(0);
	});
});
