import { afterEach, describe, expect, it, vi } from 'vitest';

import { playbackVisualizerAllowed } from './visualizer';

function stubMedia(narrow: boolean, coarse: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches:
				query === '(max-width: 640px)' ? narrow : query === '(any-pointer: coarse)' && coarse,
			media: query,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn()
		}))
	);
}

afterEach(() => {
	document.documentElement.removeAttribute('data-pointer');
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe('playbackVisualizerAllowed', () => {
	it('stays off when browser globals are unavailable', () => {
		vi.stubGlobal('window', undefined);

		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it.each([
		['a narrow viewport', true, false],
		['a coarse pointer', false, true]
	])('keeps Web Audio off for %s', (_label, narrow, coarse) => {
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		stubMedia(narrow, coarse);

		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it('keeps Web Audio off for the app coarse-pointer override and hidden documents', () => {
		stubMedia(false, false);
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		document.documentElement.dataset.pointer = 'coarse';
		expect(playbackVisualizerAllowed()).toBe(false);

		document.documentElement.removeAttribute('data-pointer');
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
		expect(playbackVisualizerAllowed()).toBe(false);
	});

	it('allows Web Audio only on a visible wide fine-pointer device', () => {
		vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
		stubMedia(false, false);

		expect(playbackVisualizerAllowed()).toBe(true);
	});
});
