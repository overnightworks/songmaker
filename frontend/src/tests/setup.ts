import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

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

// Likewise for IntersectionObserver: nothing intersects without layout, and a
// test that needs a view change installs its own stub and drives the callback.
class InertIntersectionObserver implements IntersectionObserver {
	readonly root = null;
	readonly rootMargin = '';
	readonly thresholds: readonly number[] = [];
	observe(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
	unobserve(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
	disconnect(): void {} // NOSONAR S1186: inert polyfill method; individual tests install observable stubs.
	takeRecords(): IntersectionObserverEntry[] {
		return [];
	}
}

if (!('IntersectionObserver' in globalThis)) {
	globalThis.IntersectionObserver = InertIntersectionObserver;
}

// Library history is written through SvelteKit's router, which no test page
// starts, so every test runs against the fake router unless it mocks
// `$app/navigation` itself.
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
