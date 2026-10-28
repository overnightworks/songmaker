import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { resolve } from '$app/paths';
import { goto } from '$app/navigation';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
	CowriterSettings,
	ProviderRouteReadiness,
	ProviderRouteStatusResponse,
	ProviderStatus,
	SafeRouteReason
} from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork, serverRefusal } from '$lib/test-utils/network';
import {
	ADMIN_TABS_LABEL,
	ADMIN_VOICES_EMPTY,
	COMPACT_LAYOUT_MEDIA,
	MODELS_SAVE_FAILED_FALLBACK,
	UNREACHABLE_RELOAD_DELAYS_MS
} from '$lib/constants';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { COMPACT_SELECT_CLASS } from '$lib/styles/compact-ui';
import { currentUser } from '$lib/stores/auth';

const api = vi.hoisted(() => ({
	fetchAdminVoices: vi.fn(),
	fetchRateLimits: vi.fn(),
	updateRateLimits: vi.fn(),
	fetchGenerationDefaults: vi.fn(),
	updateGenerationDefaults: vi.fn(),
	fetchAllModels: vi.fn(),
	toggleModel: vi.fn(),
	fetchCowriterSettings: vi.fn(),
	updateCowriterSettings: vi.fn(),
	fetchCoverSettings: vi.fn(),
	updateCoverSettings: vi.fn(),
	fetchProviderStatus: vi.fn(),
	fetchBuiltinDefaults: vi.fn(),
	listWorkers: vi.fn(),
	getRegistry: vi.fn()
}));

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return { ...actual, ...api };
});

import AdminPage from './+page.svelte';

const VIEWPORT_PX = 320;
const VOICES = [
	{ id: 'voice-1', name: 'Warm Tenor', owner_username: 'jane', status: 'training' },
	{ id: 'voice-2', name: 'Dry Spoken Word', owner_username: 'jane', status: 'ready' }
];
const NO_IMAGE_TOOL: ProviderRouteReadiness = {
	state: 'not_configured',
	capability: 'text_only',
	reason: { code: 'no_image_tool', message: 'no image tool' },
	setup_label: 'CLI login'
};
const IMAGE_TOOL_READY: ProviderRouteReadiness = {
	state: 'ready',
	capability: 'tools_available',
	setup_label: 'CLI login'
};
const NO_COVER_ROUTES: Record<'cli' | 'api', ProviderRouteReadiness> = {
	cli: NO_IMAGE_TOOL,
	api: NO_IMAGE_TOOL
};

function readyRoute(models: string[]): ProviderRouteStatusResponse {
	return {
		models,
		readiness: { state: 'ready', capability: 'tools_available', setup_label: 'CLI login' }
	};
}

function blockedRoute(reason: SafeRouteReason, setupLabel: string): ProviderRouteStatusResponse {
	return {
		models: [],
		catalogue_failure: { code: reason.code, message: 'Model catalogue request failed.' },
		readiness: {
			state: 'not_configured',
			capability: 'tools_available',
			reason,
			setup_label: setupLabel
		}
	};
}

const KEY_NOT_SET: SafeRouteReason = { code: 'api_key_not_set', message: 'API key is not set.' };
const NOT_SIGNED_IN: SafeRouteReason = {
	code: 'cli_login_not_configured',
	message: 'CLI is not signed in.'
};

function providerStatus(
	provider: string,
	routes: Partial<Record<'cli' | 'api', ProviderRouteStatusResponse>> = {},
	coverRoutes: Record<'cli' | 'api', ProviderRouteReadiness> = NO_COVER_ROUTES
): ProviderStatus {
	return {
		provider,
		cowriter_routes: {
			cli: routes.cli ?? blockedRoute(NOT_SIGNED_IN, 'CLI login'),
			api: routes.api ?? blockedRoute(KEY_NOT_SET, 'API key')
		},
		cover_routes: coverRoutes
	};
}

const PROVIDER_STATUSES: ProviderStatus[] = [
	providerStatus('claude', {
		cli: readyRoute(['claude-sonnet', 'claude-opus-cli']),
		api: readyRoute(['claude-opus', 'claude-api'])
	}),
	providerStatus(
		'codex',
		{ cli: readyRoute(['gpt-5-codex']), api: readyRoute(['gpt-5.4']) },
		{ cli: IMAGE_TOOL_READY, api: NO_IMAGE_TOOL }
	),
	providerStatus('grok')
];

function cowriterSettings(overrides: Partial<CowriterSettings> = {}): CowriterSettings {
	return {
		tail_token_budget: 8000,
		...overrides
	};
}

const TAB_LABELS = ['Voices', 'Rate Limits', 'Generation', 'Models', 'ACE-Step', 'Cleanup'];

let mounted: ReturnType<typeof mount> | undefined;

function stubMatchMedia(matches: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches,
			media: COMPACT_LAYOUT_MEDIA,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function optionLabels(select: HTMLSelectElement): string[] {
	return Array.from(select.options).map((option) => option.textContent ?? '');
}

async function flush(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
	await Promise.resolve();
	await tick();
}

async function renderPage(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	target.style.width = `${VIEWPORT_PX}px`;
	document.body.append(target);
	mounted = mount(AdminPage, { target });
	await flush();
	return target;
}

async function selectTab(target: HTMLElement, tab: string): Promise<void> {
	const select = requireElement<HTMLSelectElement>(
		target,
		`select[aria-label="${ADMIN_TABS_LABEL}"]`
	);
	select.value = tab;
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await flush();
}

function sectionByHeading(target: HTMLElement, heading: string): HTMLElement {
	const section = Array.from(target.querySelectorAll('section')).find(
		(el) => el.querySelector('h2')?.textContent?.trim() === heading
	);
	if (!section) throw new Error(`Expected section "${heading}" to be rendered`);
	return section;
}

function headings(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('h2')).map((el) => el.textContent?.trim() ?? '');
}

function taskNames(section: HTMLElement): string[] {
	return Array.from(section.querySelectorAll('.cell-task')).map(
		(el) => el.textContent?.trim() ?? ''
	);
}

function columnNames(section: HTMLElement): string[] {
	return Array.from(section.querySelectorAll('.tt-head span')).map(
		(el) => el.textContent?.trim() ?? ''
	);
}

function saveButtons(section: HTMLElement): string[] {
	return Array.from(section.querySelectorAll('button'))
		.map((el) => el.textContent?.trim() ?? '')
		.filter((label) => label.startsWith('Save'));
}

function rowNamed(target: HTMLElement, task: string): HTMLElement {
	const row = Array.from(target.querySelectorAll<HTMLElement>('.tt-row')).find(
		(el) => el.querySelector('.cell-task')?.textContent?.trim() === task
	);
	if (!row) throw new Error(`Expected a "${task}" row`);
	return row;
}

const selectFor = (task: string, column: string) => `select[aria-label="${task} ${column}"]`;

function taskSelect(target: HTMLElement, task: string, column: string): HTMLSelectElement {
	return requireElement<HTMLSelectElement>(target, selectFor(task, column));
}

function providerSelect(target: HTMLElement, task: string): HTMLSelectElement {
	return taskSelect(target, task, 'provider');
}

function modelSelect(target: HTMLElement, task: string): HTMLSelectElement {
	return taskSelect(target, task, 'model');
}

function routeButton(row: HTMLElement, label: string): HTMLButtonElement {
	const button = Array.from(row.querySelectorAll<HTMLButtonElement>('.rsw button')).find(
		(el) => el.textContent?.trim() === label
	);
	if (!button) throw new Error(`Expected a ${label} route button`);
	return button;
}

function reasons(row: HTMLElement): string[] {
	return Array.from(row.querySelectorAll('.why')).map((el) => el.textContent?.trim() ?? '');
}

function statusText(row: HTMLElement): string {
	return requireElement(row, '.st').textContent?.trim() ?? '';
}

async function choose(select: HTMLSelectElement, value: string): Promise<void> {
	select.value = value;
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await flush();
}

beforeEach(() => {
	window.history.replaceState({}, '', '/settings/users');
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin' });
	api.fetchAdminVoices.mockResolvedValue(VOICES);
	api.fetchRateLimits.mockResolvedValue({ settings: [] });
	api.fetchGenerationDefaults.mockResolvedValue({});
	api.fetchAllModels.mockResolvedValue([]);
	api.fetchBuiltinDefaults.mockResolvedValue({});
	api.fetchProviderStatus.mockResolvedValue(PROVIDER_STATUSES);
	api.fetchCowriterSettings.mockResolvedValue(cowriterSettings());
	api.updateCowriterSettings.mockImplementation(async (tailTokenBudget: number) =>
		cowriterSettings({ tail_token_budget: tailTokenBudget })
	);
	api.fetchCoverSettings.mockResolvedValue({
		provider: 'codex',
		route: 'cli',
		model: 'gpt-5-codex',
		allowed_providers: ['claude', 'codex', 'grok']
	});
	api.updateCoverSettings.mockImplementation(
		async (provider: string, route: 'cli' | 'api', model: string) => ({
			provider,
			route,
			model,
			allowed_providers: ['claude', 'codex', 'grok']
		})
	);
	api.listWorkers.mockResolvedValue({ workers: [] });
	api.getRegistry.mockResolvedValue({ models: [] });
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: VIEWPORT_PX });
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	window.history.replaceState({}, '', '/');
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	currentUser.set(null);
	resetConnectivityForTests();
	vi.clearAllMocks();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('C2: requested admin tab', () => {
	it.each([
		['?tab=acestep', 'acestep'],
		['?tab=models', 'models'],
		['', 'voices'],
		['?tab=unknown', 'voices']
	] as const)('C2: selects %s on arrival and later navigation', async (query, expected) => {
		window.history.replaceState({}, '', '/settings/users' + query);
		startFakeRouter();
		const target = await renderPage(true);
		const select = requireElement<HTMLSelectElement>(
			target,
			`select[aria-label="${ADMIN_TABS_LABEL}"]`
		);
		expect(select.value).toBe(expected);
		if (expected === 'acestep') expect(target.textContent).toContain('Worker');
		await goto(resolve('/settings/users?tab=generation'));
		await flush();
		expect(select.value).toBe('generation');
		await goto(resolve(`/settings/users${query}`));
		await flush();
		expect(select.value).toBe(expected);
	});
});

describe('admin settings compact layout', () => {
	it('keeps the tab selector inside 320px and hides the desktop tab row', async () => {
		const target = await renderPage(true);
		const select = requireElement<HTMLSelectElement>(
			target,
			`select[aria-label="${ADMIN_TABS_LABEL}"]`
		);
		const style = getComputedStyle(select);

		expect(target.querySelector('.tabs button')).toBeNull();
		expect(optionLabels(select)).toEqual(TAB_LABELS);
		expect(select.value).toBe('voices');
		expect(select.classList.contains(COMPACT_SELECT_CLASS)).toBe(true);
		expect(style.width).toBe('100%');
		expect(style.maxWidth).toBe('100%');
		expect(style.minWidth === '0px' || style.minWidth === '0').toBe(true);
	});

	it('shows every voice as read-only operational state', async () => {
		const target = await renderPage(true);
		const voices = sectionByHeading(target, 'Voice operations');

		expect(api.fetchAdminVoices).toHaveBeenCalledOnce();
		expect(voices.textContent).toContain('Warm Tenor');
		expect(voices.textContent).toContain('jane');
		expect(voices.textContent).toContain('training');
		expect(voices.textContent).toContain('Dry Spoken Word');
		expect(voices.textContent).toContain('ready');
		expect(voices.querySelectorAll('button')).toHaveLength(0);
		expect(voices.textContent).not.toContain('sft');
		expect(voices.textContent).not.toContain('turbo');
	});

	it('names a voices loading failure instead of showing an empty state', async () => {
		api.fetchAdminVoices.mockRejectedValueOnce(serverRefusal('Voice index is rebuilding'));
		const target = await renderPage(true);
		const voices = sectionByHeading(target, 'Voice operations');

		expect(voices.textContent).toContain('Voice index is rebuilding');
		expect(voices.textContent).not.toContain('No voices have been created.');
	});

	it('keeps desktop tab buttons and no tab selector', async () => {
		const target = await renderPage(false);
		const buttons = Array.from(target.querySelectorAll('.tabs button')).map((button) =>
			button.textContent?.trim()
		);
		expect(target.querySelector(`select[aria-label="${ADMIN_TABS_LABEL}"]`)).toBeNull();
		expect(buttons).toEqual(TAB_LABELS);
	});
});

describe('admin error ownership (#1447)', () => {
	function clickNamed(target: HTMLElement, label: string): void {
		const button = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(el) => el.textContent?.trim() === label
		);
		if (!button) throw new Error(`Expected ${label}`);
		button.click();
	}

	beforeEach(() => {
		window.history.replaceState({}, '', '/settings/users');
	});

	const races = [
		{ action: 'Save Defaults', tab: 'ratelimits', request: 'updateRateLimits' },
		{ action: 'Save Defaults', tab: 'generation', request: 'updateGenerationDefaults' },
		{ action: 'MODEL ON', tab: 'acestep', request: 'toggleModel' }
	] as const;

	it.each(
		races.flatMap((scenario) =>
			[false, true].map((returnBeforeReply) => ({ ...scenario, returnBeforeReply }))
		)
	)(
		'defect:#920-11 ignores stale $tab $action completion (return: $returnBeforeReply)',
		async ({ action, tab, request, returnBeforeReply }) => {
			let rejectRequest!: (reason: unknown) => void;
			api[request].mockImplementationOnce(
				() =>
					new Promise((_resolve, reject) => {
						rejectRequest = reject;
					})
			);
			api.fetchRateLimits.mockResolvedValue({
				settings: [{ setting_key: 'generation_rate_limit', value: 10 }]
			});
			api.fetchAllModels.mockResolvedValue([{ id: 'model', is_active: true }]);
			const target = await renderPage(true);
			await selectTab(target, tab);
			clickNamed(target, action);
			await flush();
			await selectTab(target, 'voices');
			if (returnBeforeReply) await selectTab(target, tab);
			rejectRequest(serverRefusal('Action refused'));
			await flush();
			expect(target.querySelector('.error')).toBeNull();
			if (!returnBeforeReply) {
				await selectTab(target, tab);
				expect(target.querySelector('.error')).toBeNull();
			}
		}
	);

	it.each([
		{ load: 'rateLimits', request: 'fetchRateLimits', start: 'ratelimits', tabs: ['ratelimits'] },
		{ load: 'cowriter', request: 'fetchCowriterSettings', start: 'models', tabs: ['models'] },
		{ load: 'cover', request: 'fetchCoverSettings', start: 'models', tabs: ['models'] }
	] as const)(
		'defect:#920-12 shows $load failures only on their data tabs',
		async ({ load, request, start, tabs }) => {
			const message = `${load} unavailable`;
			api[request].mockRejectedValue(serverRefusal(message));
			const target = await renderPage(true);
			await selectTab(target, start);
			expect(target.textContent).toContain(message);
			for (const destination of ['ratelimits', 'models', 'voices', 'generation', 'acestep']) {
				await selectTab(target, destination);
				expect(target.textContent?.includes(message), destination).toBe(
					(tabs as readonly string[]).includes(destination)
				);
			}
		}
	);
});

describe('admin reads and actions that fail', () => {
	it('offline, Voices claims no empty list and shows the voices once back online', async () => {
		reportResourceStreamReachable(false);
		api.fetchAdminVoices.mockRejectedValueOnce(lostNetwork());
		const target = await renderPage(true);
		const voices = sectionByHeading(target, 'Voice operations');

		expect(voices.textContent).not.toContain(ADMIN_VOICES_EMPTY);
		expect(voices.querySelector('.error')).toBeNull();

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(voices.textContent).toContain('Warm Tenor'));
	});

	it('names a save the network swallowed without browser text', async () => {
		api.updateCowriterSettings.mockRejectedValue(lostNetwork());
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const budget = requireElement<HTMLInputElement>(target, '#cowriter-budget');
		budget.value = '32000';
		budget.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();

		expect(requireElement(target, '.budget-error').textContent).toBe(MODELS_SAVE_FAILED_FALLBACK);
		expect(target.textContent).not.toContain('Failed to fetch');
	});
});

describe('admin models tab', () => {
	it('answers who does what in one row per task', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const models = sectionByHeading(target, 'Models');
		expect(taskNames(models)).toEqual(['Co-Writer', 'Cover']);
		expect(columnNames(models)).toEqual(['Task', 'Provider', 'Route', 'Model', 'Status']);
		expect(headings(target)).not.toContain('Providers');
		expect(models.querySelector('.route-card')).toBeNull();
		expect(saveButtons(models)).toEqual([]);
	});

	it('offers every provider in the cover task with the state that task gives it', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Cover'))).toEqual([
			'Claude · no image tool',
			'Codex ✓ ready',
			'Grok · no image tool'
		]);
	});

	it('keeps every provider offered and names a failed reachability probe in the row', async () => {
		api.fetchProviderStatus.mockRejectedValue(serverRefusal('Provider probe failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Cover'))).toEqual([
			'Claude · Provider probe failed',
			'Codex · Provider probe failed',
			'Grok · Provider probe failed'
		]);
		expect(statusText(rowNamed(target, 'Cover'))).toBe('○Codex · Provider probe failed');
	});

	it('shows the cover row its live models and greys a route that is not set up', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const cover = rowNamed(target, 'Cover');
		expect(optionLabels(modelSelect(target, 'Cover'))).toEqual(['gpt-5-codex']);
		expect(routeButton(cover, 'API')).toHaveClass('dead');
		expect(reasons(cover)).toContain('API · no image tool');
	});

	it('keeps every provider offered while the reachability probe runs', async () => {
		api.fetchProviderStatus.mockReturnValue(new Promise(() => {}));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const models = sectionByHeading(target, 'Models');
		expect(taskNames(models)).toEqual(['Co-Writer', 'Cover']);
		expect(optionLabels(providerSelect(target, 'Cover'))[0]).toBe('Claude · Checking…');
		expect(statusText(rowNamed(target, 'Cover'))).toBe('○Checking…');
	});

	it('C16 shows the co-writer row as set by the agent service, without a choice', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const row = rowNamed(target, 'Co-Writer');
		expect(row.textContent).toContain('Set by the agent service');
		expect(row.querySelector('select, [role="group"]')).toBeNull();
	});

	it('lists the cover row providers from the cover settings when the co-writer settings do not load', async () => {
		api.fetchCowriterSettings.mockRejectedValue(serverRefusal('Co-writer settings failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Cover'))).toEqual([
			'Claude · no image tool',
			'Codex ✓ ready',
			'Grok · no image tool'
		]);
	});

	it('keeps the cover row on the loading hint until the cover settings arrive', async () => {
		let arrive: (settings: Awaited<ReturnType<typeof api.fetchCoverSettings>>) => void = () => {};
		api.fetchCoverSettings.mockReturnValue(new Promise((resolve) => (arrive = resolve)));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(target.querySelector(selectFor('Cover', 'provider'))).toBeNull();
		expect(rowNamed(target, 'Co-Writer')).toBeTruthy();
		expect(sectionByHeading(target, 'Models').textContent).toContain('Loading…');
		arrive({
			provider: 'codex',
			route: 'cli',
			model: 'gpt-5-codex',
			allowed_providers: ['claude', 'codex', 'grok']
		});
		await flush();

		expect(optionLabels(providerSelect(target, 'Cover')).length).toBeGreaterThan(0);
	});

	it('shows the load error and no cover select when the cover settings fail', async () => {
		api.fetchCoverSettings.mockRejectedValue(serverRefusal('cover unavailable'));
		const target = await renderPage(true);
		await selectTab(target, 'models');
		expect(target.textContent).toContain('cover unavailable');
		expect(target.textContent).not.toContain('Loading…');
		expect(target.querySelector(selectFor('Cover', 'provider'))).toBeNull();
	});

	it('saves the cover row with its own provider, route and model', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Cover'), 'claude');

		expect(api.updateCoverSettings).toHaveBeenCalledWith('claude', 'cli', '');
		expect(optionLabels(modelSelect(target, 'Cover'))).toEqual(['No models']);
		expect(rowNamed(target, 'Cover').textContent).toContain('Claude cannot draw');
	});

	it('offers no defaults editor and sends nothing while the generation defaults failed to load', async () => {
		api.fetchGenerationDefaults.mockRejectedValue(
			new ApiError(
				500,
				'Defaults unavailable',
				'/api/settings/generation-defaults',
				null,
				'Defaults unavailable'
			)
		);
		const target = await renderPage(true);
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, 'Generation Defaults');
		expect(requireElement(section, '.error').textContent).toContain('Defaults unavailable');
		expect(section.querySelector('.save-btn')).toBeNull();
		expect(section.querySelector('.gen-model-tab')).toBeNull();
		expect(api.updateGenerationDefaults).not.toHaveBeenCalled();
	});

	it('refills the form from the stored defaults once a failed read recovers, so Save never wipes them', async () => {
		const stored = { turbo: { inference_steps: 20, guidance_scale: 5 } };
		api.fetchBuiltinDefaults.mockResolvedValue({ turbo: { inference_steps: 8 } });
		api.fetchGenerationDefaults
			.mockRejectedValueOnce(
				new ApiError(500, 'Defaults unavailable', '/api/settings/generation-defaults', null, null)
			)
			.mockResolvedValue(stored);
		api.updateGenerationDefaults.mockImplementation(async (body: unknown) => body);
		const target = await renderPage(true);
		await selectTab(target, 'generation');
		await selectTab(target, 'users');
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, 'Generation Defaults');
		const save = requireElement<HTMLButtonElement>(section, '.save-btn');
		const stepsInput = requireElement<HTMLInputElement>(section, 'input');
		expect(save.disabled).toBe(false);
		expect(stepsInput.value).toBe('20');

		save.click();
		await flush();
		expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith(stored);

		stepsInput.value = '30';
		stepsInput.dispatchEvent(new Event('input', { bubbles: true }));
		stepsInput.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();
		save.click();
		await flush();
		expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith({
			turbo: { inference_steps: 30, guidance_scale: 5 }
		});
	});

	it('renders no defaults editor while the read has failed, and Save after recovery sends the stored values', async () => {
		const stored = { turbo: { inference_steps: 20 }, base: { inference_steps: 40 } };
		api.fetchBuiltinDefaults.mockResolvedValue({
			turbo: { inference_steps: 8 },
			base: { inference_steps: 8 }
		});
		api.fetchGenerationDefaults
			.mockRejectedValueOnce(
				new ApiError(500, 'Defaults unavailable', '/api/settings/generation-defaults', null, null)
			)
			.mockResolvedValue(stored);
		api.updateGenerationDefaults.mockImplementation(async (body: unknown) => body);
		const target = await renderPage(true);
		await selectTab(target, 'generation');

		const failed = sectionByHeading(target, 'Generation Defaults');
		expect(requireElement(failed, '.error').textContent).toContain('Defaults unavailable');
		expect(failed.querySelector('.save-btn')).toBeNull();

		await selectTab(target, 'users');
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, 'Generation Defaults');
		requireElement<HTMLButtonElement>(section, '.save-btn').click();
		await flush();
		expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith(stored);
	});

	describe('generation defaults editing across reads', () => {
		const builtins = { turbo: { inference_steps: 8 }, sft: { inference_steps: 8 } };

		async function typeSteps(section: HTMLElement, value: string): Promise<void> {
			const stepsInput = requireElement<HTMLInputElement>(section, 'input');
			stepsInput.value = value;
			stepsInput.dispatchEvent(new Event('input', { bubbles: true }));
			stepsInput.dispatchEvent(new Event('change', { bubbles: true }));
			await flush();
		}

		function modeTab(section: HTMLElement, mode: string): HTMLButtonElement {
			const tab = Array.from(section.querySelectorAll<HTMLButtonElement>('.gen-model-tab')).find(
				(candidate) => candidate.textContent?.trim() === mode
			);
			if (!tab) throw new Error(`no mode tab ${mode}`);
			return tab;
		}

		beforeEach(() => {
			api.fetchBuiltinDefaults.mockResolvedValue(builtins);
			api.updateGenerationDefaults.mockImplementation(async (body: unknown) => body);
		});

		it('re-hydrates after a network-loss read retries successfully, and an edit merges into the stored values', async () => {
			vi.useFakeTimers();
			const firstStored = { turbo: { inference_steps: 20 }, sft: { inference_steps: 40 } };
			const recoveredStored = {
				turbo: { inference_steps: 21, guidance_scale: 5 },
				sft: { inference_steps: 41, guidance_scale: 6 }
			};
			api.fetchGenerationDefaults
				.mockResolvedValueOnce(firstStored)
				.mockRejectedValueOnce(lostNetwork())
				.mockResolvedValue(recoveredStored);
			const target = await renderPage(true);
			await selectTab(target, 'generation');
			modeTab(sectionByHeading(target, 'Generation Defaults'), 'SFT').click();
			await flush();
			await selectTab(target, 'users');
			await selectTab(target, 'generation');
			await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS[0]);

			const section = sectionByHeading(target, 'Generation Defaults');
			expect(requireElement<HTMLInputElement>(section, 'input').value).toBe('41');
			await typeSteps(section, '30');
			requireElement<HTMLButtonElement>(section, '.save-btn').click();
			await flush();

			expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith({
				turbo: recoveredStored.turbo,
				sft: { inference_steps: 30, guidance_scale: 6 }
			});
		});

		it('keeps an unsaved edit when the admin leaves the tab and returns while reads succeed', async () => {
			const stored = { turbo: { inference_steps: 20 }, sft: { inference_steps: 50 } };
			api.fetchGenerationDefaults.mockResolvedValue(stored);
			const target = await renderPage(true);
			await selectTab(target, 'generation');
			const first = sectionByHeading(target, 'Generation Defaults');
			modeTab(first, 'SFT').click();
			await flush();
			await typeSteps(first, '77');
			await selectTab(target, 'acestep');
			await selectTab(target, 'generation');

			const section = sectionByHeading(target, 'Generation Defaults');
			expect(requireElement<HTMLInputElement>(section, 'input').value).toBe('77');
			requireElement<HTMLButtonElement>(section, '.save-btn').click();
			await flush();

			expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith({
				turbo: stored.turbo,
				sft: { inference_steps: 77 }
			});
		});
	});

	it.each([
		{
			shape: 'a route reason the row can phrase',
			detail: { code: 'api_key_not_set', message: 'codex key is not set.' },
			sentence: 'CLI · key not set'
		},
		{
			shape: 'a plain sentence from the server',
			detail: "Unknown codex model 'gpt-9'",
			sentence: "Unknown codex model 'gpt-9'"
		},
		{
			shape: 'a detail the page cannot read',
			detail: [{ loc: ['body', 'model'], msg: 'field required' }],
			sentence: 'The server rejected the change.'
		}
	])('names a rejected save that carries $shape', async ({ detail, sentence }) => {
		api.updateCoverSettings.mockRejectedValue(
			new ApiError(
				422,
				typeof detail === 'string' ? detail : '',
				'/api/settings/cover',
				null,
				detail
			)
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Cover'), 'claude');

		const failure = requireElement(sectionByHeading(target, 'Models'), '.tt-sub.bad');
		expect(failure.textContent).toContain(sentence);
		expect(failure.textContent).not.toContain('Something went wrong');
		expect(requireElement(failure, '.retry').textContent?.trim()).toBe('Retry');
	});

	it('names a rejected history-tail save next to the field with a retry', async () => {
		api.updateCowriterSettings.mockRejectedValue(serverRefusal('Tail budget out of range'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const disclosure = requireElement<HTMLDetailsElement>(
			sectionByHeading(target, 'Models'),
			'details'
		);
		const budget = requireElement<HTMLInputElement>(disclosure, '#cowriter-budget');
		budget.value = '999999';
		budget.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();

		expect(disclosure.textContent).toContain('Tail budget out of range');
		expect(disclosure.textContent).not.toContain('Saved.');

		api.updateCowriterSettings.mockResolvedValue(cowriterSettings({ tail_token_budget: 999999 }));
		requireElement<HTMLButtonElement>(disclosure, '.retry').click();
		await flush();

		expect(disclosure.textContent).toContain('Saved.');
		expect(disclosure.textContent).not.toContain('Tail budget out of range');
	});

	it('keeps the history tail under a collapsed Advanced disclosure and saves it there', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const disclosure = requireElement<HTMLDetailsElement>(
			sectionByHeading(target, 'Models'),
			'details'
		);
		expect(disclosure.open).toBe(false);
		expect(disclosure.textContent).toContain('History tail (tokens)');

		const budget = requireElement<HTMLInputElement>(disclosure, '#cowriter-budget');
		budget.value = '24000';
		budget.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledWith(24000);
		expect(disclosure.textContent).toContain('Saved.');
	});
});
