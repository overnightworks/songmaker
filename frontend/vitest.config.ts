import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { sveltekitOptions } from './vite.config';

export default defineConfig({
	plugins: [sveltekit(sveltekitOptions)],
	resolve: {
		conditions: ['browser']
	},
	test: {
		// The setup file and jsdom belong to the component tests; the coverage
		// report's test runs in plain Node.
		projects: [
			{
				extends: true,
				test: {
					name: 'components',
					include: ['src/**/*.test.ts'],
					environment: 'jsdom',
					// Node 26's built-in localStorage shadows jsdom's; the negated flag is accepted by Node 24 too.
					execArgv: ['--no-experimental-webstorage'],
					setupFiles: ['src/tests/setup.ts']
				}
			},
			{
				extends: true,
				test: {
					name: 'e2e-report',
					include: [
						'e2e/coverage-summary.test.ts',
						'e2e/report-identity.test.ts',
						'e2e/shard-artifacts.test.ts'
					],
					environment: 'node'
				}
			}
		],
		coverage: {
			provider: 'v8',
			include: ['src/**/*.{ts,svelte}'],
			exclude: ['src/lib/index.ts', 'src/lib/api/types.ts', 'src/service-worker.ts'],
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
