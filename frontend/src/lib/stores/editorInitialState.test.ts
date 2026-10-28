import { get } from 'svelte/store';
import { expect, it, vi } from 'vitest';

it('shows Auto duration before any song is loaded', async () => {
	vi.resetModules();
	const fresh = await import('./editor');
	expect(get(fresh.editAudioDuration)).toBe(0);
});
