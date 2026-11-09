import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';
import './viz-colors.ts';

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

// jsdom implements neither scrolling into view, pointer capture, animation listing nor
// media queries, which every supported browser has; components call them directly,
// so they exist here as no-ops and a test that needs the arguments installs
// its own spy.
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.getAnimations ??= () => [];
window.matchMedia ??= (query: string) =>
	({
		matches: false,
		media: query,
		addEventListener: () => {},
		removeEventListener: () => {}
	}) as unknown as MediaQueryList;

// Library history is written through SvelteKit's router, which no test page
// starts, so every test runs against the fake router unless it mocks
// `$app/navigation` itself.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
