import { describe, expect, it, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';

const mockStorage: Record<string, string> = {};

vi.stubGlobal('localStorage', {
	getItem: (key: string) => mockStorage[key] ?? null,
	setItem: (key: string, value: string) => {
		mockStorage[key] = value;
	},
	removeItem: (key: string) => {
		Reflect.deleteProperty(mockStorage, key);
	}
});

import { claudeApiKey, getClaudeKey } from './settings';

describe('settings store', () => {
	beforeEach(() => {
		Object.keys(mockStorage).forEach((k) => Reflect.deleteProperty(mockStorage, k));
		claudeApiKey.set('');
	});

	it('defaults to empty string', () => {
		expect(get(claudeApiKey)).toBe('');
	});

	it('persists key to localStorage', () => {
		claudeApiKey.set('sk-test-123');
		expect(mockStorage['songmaker:claude-key']).toBe('sk-test-123');
	});

	it('removes key from localStorage when cleared', () => {
		claudeApiKey.set('sk-test');
		claudeApiKey.set('');
		expect(mockStorage['songmaker:claude-key']).toBeUndefined();
	});

	it('getClaudeKey returns current value', () => {
		claudeApiKey.set('sk-abc');
		expect(getClaudeKey()).toBe('sk-abc');
	});
});
