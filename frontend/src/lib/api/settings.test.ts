import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

import {
	fetchDefaultConfig,
	toggleModel,
	updateCoverSettings,
	updateCowriterSettings,
	updateDefaultConfig,
	updateGenerationDefaults,
	updateJudgeSettings,
	updateRateLimits
} from './settings';

function acceptRequests(): void {
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
}

function request(): [string, RequestInit] {
	return mockFetch.mock.calls[0] as [string, RequestInit];
}

beforeEach(() => {
	mockFetch.mockReset();
	acceptRequests();
});

describe('settings API contract', () => {
	it.each([
		[
			'generation defaults',
			() => updateGenerationDefaults({ acestep: { inference_steps: 7 } }),
			'/api/settings/generation-defaults',
			'PUT',
			{ acestep: { inference_steps: 7 } }
		],
		[
			'judge settings',
			() => updateJudgeSettings('claude', 'cli', 'claude-sonnet'),
			'/api/settings/judge',
			'PUT',
			{ provider: 'claude', route: 'cli', model: 'claude-sonnet' }
		],
		[
			'cover settings',
			() => updateCoverSettings('codex', 'cli', 'gpt-5-codex'),
			'/api/settings/cover',
			'PUT',
			{ provider: 'codex', route: 'cli', model: 'gpt-5-codex' }
		],
		[
			'rate limits',
			() => updateRateLimits({ generate: 5 }),
			'/api/settings/rate-limits',
			'PUT',
			{ settings: { generate: 5 } }
		]
	])('serializes %s as its public JSON request', async (_name, send, url, method, payload) => {
		await send();
		const [actualUrl, init] = request();
		expect(actualUrl).toBe(url);
		expect(init.method).toBe(method);
		expect(JSON.parse(String(init.body))).toEqual(payload);
	});

	it('preserves optional cowriter fields and routes in the settings payload', async () => {
		await updateCowriterSettings('anthropic', 'claude', 1200, { anthropic: 'api' });
		const [url, init] = request();
		expect(url).toBe('/api/settings/cowriter');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(String(init.body))).toEqual({
			provider: 'anthropic',
			model: 'claude',
			tail_token_budget: 1200,
			provider_routes: { anthropic: 'api' }
		});
	});

	it('uses the model query without a JSON body', async () => {
		await toggleModel('acestep-1.5', false);
		const [url, init] = request();
		expect(url).toBe('/api/settings/models/acestep-1.5?active=false');
		expect(init.method).toBe('PUT');
		expect(init.body).toBeUndefined();
	});

	it('#1882 wire bytes unchanged: reads and writes the default config as its response type', async () => {
		const stored = { config: 'steps: 7' };
		mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(stored) });

		expect(await fetchDefaultConfig()).toEqual(stored);
		expect(request()[0]).toBe('/api/settings/default-config');

		mockFetch.mockClear();
		expect(await updateDefaultConfig('steps: 7')).toEqual(stored);
		const [url, init] = request();
		expect(url).toBe('/api/settings/default-config');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(String(init.body))).toEqual({ config: 'steps: 7' });
	});
});
