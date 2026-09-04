import { expect, test, type Page } from '@playwright/test';

import { ADMIN_TABS_LABEL } from '../src/lib/constants';

type RouteState = 'ready' | 'not_configured' | 'disturbed';

function route(state: RouteState, model: string, reason?: string) {
	return {
		models: state === 'ready' ? [model] : [],
		catalog_source: state === 'ready' ? 'Live catalog' : null,
		catalog_version: state === 'ready' ? '2026.9' : null,
		catalogue_failure: reason ? { code: 'catalogue_http_error', message: reason } : null,
		readiness: {
			state,
			reason: reason ? { code: 'catalogue_http_error', message: reason } : null,
			setup_label: 'CLI login'
		}
	};
}

function cowriterSettings(states: Record<'cli' | 'api', RouteState>, reason?: string) {
	const providers = ['claude', 'codex', 'grok'];
	return {
		provider: 'claude',
		model: 'claude-cli',
		tail_token_budget: 8000,
		allowed_providers: providers,
		allowed_models: ['claude-cli'],
		models_by_provider: Object.fromEntries(providers.map((provider) => [provider, []])),
		models_errors: {},
		models_sources: {},
		current_models_not_in_catalog: {},
		probed_at: {},
		provider_routes: { claude: 'cli', codex: 'cli', grok: 'cli' },
		provider_routes_status: Object.fromEntries(
			providers.map((provider) => [
				provider,
				{
					cli: route(states.cli, `${provider}-cli`, reason),
					api: route(states.api, `${provider}-api`, reason)
				}
			])
		)
	};
}

async function openModelsTab(page: Page): Promise<void> {
	await page.goto('/settings/users');
	await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible();

	const compactTabs = page.getByRole('combobox', { name: ADMIN_TABS_LABEL, exact: true });
	if (await compactTabs.count()) {
		await compactTabs.selectOption('models');
	} else {
		await page.getByRole('button', { name: 'Models', exact: true }).click();
	}
}

test('the admin UI proves ready, blocked, and unavailable provider routes at desktop and 375px', async ({
	page,
	isMobile
}) => {
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });

	let settings = cowriterSettings({ cli: 'ready', api: 'ready' });
	await page.route('**/api/settings/cowriter', async (request) => {
		if (request.request().method() !== 'GET') return request.continue();
		await request.fulfill({ json: settings });
	});

	await openModelsTab(page);
	const cowriter = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'Co-Writer' }) });
	const claudeCard = cowriter.locator('.route-card').filter({ hasText: 'Claude' });
	await expect(claudeCard).toContainText('CLI · ready');
	await expect(claudeCard).toContainText('API · ready');
	await expect(claudeCard).toContainText('key: set');
	await expect(claudeCard.locator('#cowriter-model-claude')).toHaveValue('claude-cli');
	await claudeCard.getByRole('button', { name: 'Use Claude API route' }).click();
	await expect(claudeCard.locator('#cowriter-model-claude')).toHaveValue('claude-api');
	await expect(claudeCard).toContainText('Version 2026.9');

	settings = cowriterSettings({ cli: 'ready', api: 'disturbed' }, 'Rate limit exceeded');
	await openModelsTab(page);
	await claudeCard.getByRole('button', { name: 'Use Claude API route' }).click();
	await expect(cowriter.getByRole('alert')).toContainText('Turn blocked');
	await expect(cowriter.getByRole('alert')).toContainText('Rate limit exceeded');
	await expect(claudeCard.locator('#cowriter-model-claude')).toBeDisabled();

	settings = cowriterSettings({ cli: 'not_configured', api: 'not_configured' });
	await openModelsTab(page);
	await expect(cowriter.getByRole('alert')).toContainText('Provider unavailable');
	await expect(claudeCard.locator('#cowriter-model-claude')).toBeDisabled();
	await expect(claudeCard.locator('#cowriter-model-claude')).toHaveText('No models available');

	if (isMobile) {
		await expect
			.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
			.toBe(true);
	}
});
