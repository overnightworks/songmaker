// What every spec imports instead of '@playwright/test': the same exports, but
// its `test` records each page's browser JavaScript coverage into the project's
// raw store, which coverage-report.ts turns into a report. A collection error
// is reported and never fails the test, so the tests alone decide the run.
//
// Not collected: pages opened from a spec's own `browser.newContext` and
// popups; they run uninstrumented, so the report under-counts what those flows reach.

import { appendFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { test as base } from '@playwright/test';
import { MCR } from 'monocart-coverage-reports';
import { collectionTimeFile, coverageOptions } from './coverage-options.ts';

export * from '@playwright/test';

export const test = base.extend({
	page: async ({ page, browserName }, use, testInfo) => {
		const project = testInfo.project.name;
		const warn = (error: unknown) =>
			console.warn(`coverage not collected for "${testInfo.titlePath.join(' > ')}": ${error}`);
		if (browserName !== 'chromium') {
			await use(page);
			return;
		}
		const collecting = await page.coverage.startJSCoverage({ resetOnNavigation: false }).then(
			() => true,
			(error) => (warn(error), false)
		);
		await use(page);
		if (!collecting) return;
		const started = performance.now();
		try {
			const coverage = await page.coverage.stopJSCoverage();
			// A page that loaded no script (a stubbed route, an error page) has nothing to add.
			if (coverage.length > 0) await MCR(coverageOptions(project)).add(coverage);
			const timeFile = collectionTimeFile(project);
			mkdirSync(path.dirname(timeFile), { recursive: true });
			appendFileSync(timeFile, `${Math.round(performance.now() - started)}\n`);
		} catch (error) {
			warn(error);
		}
	}
});
