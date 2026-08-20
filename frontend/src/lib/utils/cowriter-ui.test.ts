import { describe, expect, it } from 'vitest';
import {
	cowriterHeaderLabel,
	cowriterThinkingLabel,
	cowriterUnavailableLabel
} from './cowriter-ui';

describe('co-writer provider copy', () => {
	it('uses the active provider instead of a hardcoded Claude name', () => {
		expect(cowriterHeaderLabel('grok', 'grok-4.6')).toBe('grok · grok-4.6');
		expect(cowriterThinkingLabel('codex')).toBe('codex is thinking...');
		expect(cowriterUnavailableLabel('grok')).toBe('grok is currently unavailable');
		expect(cowriterThinkingLabel('claude')).not.toContain('Claude Co-Writer');
	});
});
