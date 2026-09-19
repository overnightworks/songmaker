import { afterEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';
import { subscribeCompactLayout } from './compact-layout';

type MediaListener = (event: MediaQueryListEvent) => void;

function stubMatchMedia(matches: boolean): {
	setMatches: (next: boolean) => void;
} {
	const listeners = new Set<MediaListener>();
	const media = {
		matches,
		media: COMPACT_LAYOUT_MEDIA,
		onchange: null,
		addEventListener: vi.fn((type: string, cb: EventListenerOrEventListenerObject) => {
			if (type === 'change' && typeof cb === 'function') listeners.add(cb as MediaListener);
		}),
		removeEventListener: vi.fn((type: string, cb: EventListenerOrEventListenerObject) => {
			if (type === 'change' && typeof cb === 'function') listeners.delete(cb as MediaListener);
		}),
		addListener: vi.fn(),
		removeListener: vi.fn(),
		dispatchEvent: vi.fn()
	};
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => media)
	);
	return {
		setMatches(next: boolean) {
			media.matches = next;
			for (const listener of listeners) {
				listener({ matches: next } as MediaQueryListEvent);
			}
		}
	};
}

afterEach(() => {
	delete document.documentElement.dataset.pointer;
	vi.unstubAllGlobals();
});

describe('subscribeCompactLayout', () => {
	it('falls back to the pointer hint when matchMedia is unavailable', async () => {
		vi.stubGlobal('matchMedia', undefined);
		delete document.documentElement.dataset.pointer;
		const values: boolean[] = [];
		const stop = subscribeCompactLayout((compact) => {
			values.push(compact);
		});

		expect(values).toEqual([false]);

		document.documentElement.dataset.pointer = 'coarse';
		await vi.waitFor(() => expect(values.at(-1)).toBe(true));

		stop();
	});

	it('syncs on subscribe, media change, and data-pointer mutations', async () => {
		const media = stubMatchMedia(false);
		delete document.documentElement.dataset.pointer;
		const values: boolean[] = [];
		const stop = subscribeCompactLayout((compact) => {
			values.push(compact);
		});

		expect(values).toEqual([false]);

		media.setMatches(true);
		expect(values.at(-1)).toBe(true);

		media.setMatches(false);
		expect(values.at(-1)).toBe(false);

		document.documentElement.dataset.pointer = 'coarse';
		await vi.waitFor(() => expect(values.at(-1)).toBe(true));

		stop();
	});

	it('queries the caller-supplied media string instead of the default', () => {
		const matchMediaSpy = vi.fn((query: string) => ({
			matches: false,
			media: query,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}));
		vi.stubGlobal('matchMedia', matchMediaSpy);
		const stop = subscribeCompactLayout(() => {}, '(max-width: 640px), (any-pointer: coarse)');

		expect(matchMediaSpy).toHaveBeenCalledWith('(max-width: 640px), (any-pointer: coarse)');

		stop();
	});
});
