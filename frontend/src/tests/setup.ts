import '@testing-library/jest-dom/vitest';

// jsdom performs no layout, so it ships no ResizeObserver. Components that
// re-measure when their box changes size must still be mountable here; a test
// that exercises that path installs its own stub and drives the callback.
class InertResizeObserver implements ResizeObserver {
	observe(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
	unobserve(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
	disconnect(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
}

if (!('ResizeObserver' in globalThis)) {
	globalThis.ResizeObserver = InertResizeObserver;
}
