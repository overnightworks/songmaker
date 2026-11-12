import '@testing-library/jest-dom/vitest';
import { beforeEach, vi } from 'vitest';
import './browser-apis.ts';
import './viz-colors.ts';
import { loadPageKitWords } from '#lib/utils/kit-words.ts';
import { loadPageWords } from '#lib/utils/page-words.ts';
import { sourceLanguage } from '#lib/words/index.ts';

// jsdom performs no layout, so it ships no ResizeObserver. Components that
// re-measure when their box changes size must still be mountable here; a test
// that exercises that path installs its own stub and drives the callback.
class InertResizeObserver implements ResizeObserver {
	observe(): void {
		// Inert polyfill method; individual tests install observable stubs.
	}
	unobserve(): void {
		// Inert polyfill method; individual tests install observable stubs.
	}
	disconnect(): void {
		// Inert polyfill method; individual tests install observable stubs.
	}
}

if (!('ResizeObserver' in globalThis)) {
	globalThis.ResizeObserver = InertResizeObserver;
}

// Library history is written through SvelteKit's router, which no test page
// starts, so every test runs against the fake router unless it mocks
// `$app/navigation` itself.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

// The page's language is the source language at the start of every test, so
// a test that changes `<html lang>` cannot leak it into the next one.
beforeEach(() => {
	document.documentElement.lang = 'en';
});

// Every test file starts with the page's and the kit's words loaded, as the root layout's `load` leaves them.
await Promise.all([loadPageWords(sourceLanguage), loadPageKitWords(sourceLanguage)]);
