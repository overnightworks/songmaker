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
		setupFiles: ['src/tests/setup.ts'],
		coverage: {
			provider: 'v8',
			include: ['src/lib/**/*.ts'],
			exclude: ['src/lib/index.ts', 'src/lib/api/types.ts'],
			reporter: ['text', 'text-summary', 'lcov'],
			reportsDirectory: '../reports/frontend-coverage',
			all: false,
			thresholds: {
				statements: 90,
				lines: 93
			}
		}
	}
});
