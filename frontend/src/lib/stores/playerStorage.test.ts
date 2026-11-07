import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { setShuffle } from './player';

beforeEach(() => {
	localStorage.clear();
});

// Spec: REQ-LISTENING-03 -- a reloaded browser profile restores the Shuffle state the musician chose last.
it.each([true, false])('restores Shuffle %s on the next visit', async (enabled) => {
	setShuffle(enabled);
	vi.resetModules();
	const { shuffleEnabled } = await import('./player');

	expect(get(shuffleEnabled)).toBe(enabled);
});

it('imports with the defaults when browser storage throws', async () => {
	vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
		throw new DOMException('blocked', 'SecurityError');
	});
	vi.resetModules();
	const { shuffleEnabled } = await import('./player');
	vi.restoreAllMocks();

	expect(get(shuffleEnabled)).toBe(false);
});
