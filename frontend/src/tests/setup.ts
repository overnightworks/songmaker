import '@testing-library/jest-dom/vitest';
import { beforeEach, vi } from 'vitest';

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

// jsdom loads no stylesheet, so the visualizer's accent channels are unset and
// reading them raises. Every test starts with scenario channels; a test that
// needs other values or none sets or removes them itself.
beforeEach(() => {
	const root = document.documentElement.style;
	root.setProperty('--viz-accent-r', '1');
	root.setProperty('--viz-accent-g', '2');
	root.setProperty('--viz-accent-b', '3');
});
