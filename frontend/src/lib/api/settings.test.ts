import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import {
	deleteUserRateLimits,
	toggleModel,
	updateCowriterSettings,
	updateGenerationDefaults,
	updateJudgeSettings,
	updateRateLimits,
	updateUserRateLimits
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
		['generation defaults', () => updateGenerationDefaults({ acestep: { inference_steps: 7 } }), '/api/settings/generation-defaults', 'PUT', { acestep: { inference_steps: 7 } }],
		['judge settings', () => updateJudgeSettings('openai', 'gpt-5'), '/api/settings/judge', 'PUT', { provider: 'openai', model: 'gpt-5' }],
		['rate limits', () => updateRateLimits({ generate: 5 }), '/api/settings/rate-limits', 'PUT', { settings: { generate: 5 } }],
		['user rate limits', () => updateUserRateLimits('u-1', { generate: 5 }), '/api/settings/rate-limits/user/u-1', 'PUT', { settings: { generate: 5 } }]
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
			provider: 'anthropic', model: 'claude', tail_token_budget: 1200,
			provider_routes: { anthropic: 'api' }
		});
	});

	it('uses the model query and deletion endpoint without a JSON body', async () => {
		await toggleModel('acestep-1.5', false);
		let [url, init] = request();
		expect(url).toBe('/api/settings/models/acestep-1.5?active=false');
		expect(init.method).toBe('PUT');
		expect(init.body).toBeUndefined();

		mockFetch.mockClear();
		await deleteUserRateLimits('u-1');
		[url, init] = request();
		expect(url).toBe('/api/settings/rate-limits/user/u-1');
		expect(init.method).toBe('DELETE');
		expect(init.body).toBeUndefined();
	});
});
