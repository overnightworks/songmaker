import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { sveltekitOptions } from './vite.config';

export default defineConfig({
	plugins: [sveltekit(sveltekitOptions)],
	resolve: {
		conditions: ['browser']
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		// Node 26's built-in localStorage shadows jsdom's; the negated flag is accepted by Node 24 too.
		execArgv: ['--no-experimental-webstorage'],
		setupFiles: ['src/tests/setup.ts'],
		coverage: {
			provider: 'v8',
			include: ['src/**/*.{ts,svelte}'],
			exclude: [
				'src/**/*.test.ts',
				'src/tests/**',
				'src/lib/index.ts',
				'src/lib/api/types.ts',
				'src/service-worker.ts'
			],
			reporter: ['text', 'text-summary', 'lcov'],
			reportsDirectory: '../reports/frontend-coverage',
			thresholds: {
				statements: 94,
				lines: 95,
				branches: 87,
				'src/lib/**/*.ts': {
					statements: 90,
					lines: 93
				}
			}
		}
	}
});
