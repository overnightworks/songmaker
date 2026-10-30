import { vi } from 'vitest';

// A stand-in for SvelteKit's `resolve`, shared by every test that mocks it:
//   vi.mock('$app/paths', async () =>
//     (await import('#lib/test-utils/app-paths.ts')).fakeAppPaths());
// Like the real one, a route ID loses its route groups and keeps a leading slash.
export function fakeAppPaths() {
	return {
		resolve: vi.fn((routeId: string) =>
			routeId.replace(/\/\([^/)]+\)/g, '').replace(/^(?!\/)/, '/')
		)
	};
}
