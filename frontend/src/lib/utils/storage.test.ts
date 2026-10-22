import { afterEach, expect, it, vi } from 'vitest';
import { readStorage, removeStorage, writeStorage } from './storage';

afterEach(() => {
	vi.restoreAllMocks();
	localStorage.clear();
});

it('reads, writes and removes a value when storage works', () => {
	writeStorage('k', 'v');
	expect(readStorage('k')).toBe('v');
	removeStorage('k');
	expect(readStorage('k')).toBeNull();
});

it('remembers nothing and reads null when storage throws', () => {
	const blocked = () => {
		throw new DOMException('blocked', 'SecurityError');
	};
	vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
	vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);
	vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(blocked);

	expect(readStorage('k')).toBeNull();
	expect(() => writeStorage('k', 'v')).not.toThrow();
	expect(() => removeStorage('k')).not.toThrow();
	vi.restoreAllMocks();
	expect(readStorage('k')).toBeNull();
});
