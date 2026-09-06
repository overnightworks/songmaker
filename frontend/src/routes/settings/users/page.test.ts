import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
	CowriterSettings,
	JudgeSettings,
	LoginAttemptItem,
	PaginatedResponse,
	ProviderRouteReadiness,
	ProviderRouteStatusResponse,
	ProviderStatus,
	ProviderSurfaceStatus,
	SafeRouteReason,
	SessionItem,
	UserItem
} from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { ADMIN_TABS_LABEL, COMPACT_LAYOUT_MEDIA } from '$lib/constants';
import { COMPACT_SELECT_CLASS, COMPACT_STACK_CLASS } from '$lib/styles/compact-ui';
import { currentUser } from '$lib/stores/auth';

const api = vi.hoisted(() => ({
	fetchUsers: vi.fn(),
	fetchAdminVoices: vi.fn(),
	createUser: vi.fn(),
	updateUser: vi.fn(),
	hardDeleteUser: vi.fn(),
	fetchSessions: vi.fn(),
	forceLogout: vi.fn(),
	fetchLoginAttempts: vi.fn(),
	fetchRateLimits: vi.fn(),
	updateRateLimits: vi.fn(),
	fetchUserRateLimits: vi.fn(),
	updateUserRateLimits: vi.fn(),
	deleteUserRateLimits: vi.fn(),
	fetchGenerationDefaults: vi.fn(),
	updateGenerationDefaults: vi.fn(),
	fetchAllModels: vi.fn(),
	toggleModel: vi.fn(),
	fetchCowriterSettings: vi.fn(),
	updateCowriterSettings: vi.fn(),
	fetchJudgeSettings: vi.fn(),
	updateJudgeSettings: vi.fn(),
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
const ADMIN_USER: UserItem = {
	id: 'u1',
	username: 'felix',
	role: 'admin',
	is_active: true,
	created_at: '2026-01-01T00:00:00Z'
};
const OTHER_USER: UserItem = {
	id: 'u2',
	username: 'jane',
	role: 'user',
	is_active: true,
	created_at: '2026-01-02T00:00:00Z'
};
const VOICES = [
	{ id: 'voice-1', name: 'Warm Tenor', owner_username: 'jane', status: 'training' },
	{ id: 'voice-2', name: 'Dry Spoken Word', owner_username: 'jane', status: 'ready' }
];
const SESSION: SessionItem = {
	id: 's1',
	user_id: 'u2',
	username: 'jane',
	created_at: '2026-01-03T00:00:00Z',
	expires_at: '2026-01-04T00:00:00Z',
	ip_address: '203.0.113.10',
	user_agent: 'vitest'
};
const ATTEMPT: LoginAttemptItem = {
	id: 'a1',
	ip_address: '203.0.113.11',
	username: 'jane',
	success: false,
	attempted_at: '2026-01-03T01:00:00Z'
};
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
		catalogue_failure: { code: reason.code, message: 'List needs the key' },
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
	cowriter: ProviderSurfaceStatus,
	judge: ProviderSurfaceStatus = cowriter,
	routes: Partial<Record<'cli' | 'api', ProviderRouteStatusResponse>> = {},
	coverRoutes: Record<'cli' | 'api', ProviderRouteReadiness> = NO_COVER_ROUTES
): ProviderStatus {
	return {
		provider,
		cowriter,
		judge,
		cowriter_routes: {
			cli: routes.cli ?? blockedRoute(NOT_SIGNED_IN, 'CLI login'),
			api: routes.api ?? blockedRoute(KEY_NOT_SET, 'API key')
		},
		cover_routes: coverRoutes
	};
}

const CLAUDE_VIA_CLI: ProviderSurfaceStatus = {
	state: 'configured',
	needs: null,
	setup_method: 'claude_cli',
	environment_key: null
};
const CODEX_VIA_KEY: ProviderSurfaceStatus = {
	state: 'configured',
	needs: null,
	setup_method: 'api_key',
	environment_key: 'OPENAI_API_KEY'
};
const GROK_WITHOUT_KEY: ProviderSurfaceStatus = {
	state: 'unconfigured',
	needs: 'api_key',
	setup_method: null,
	environment_key: 'XAI_API_KEY'
};

const PROVIDER_STATUSES: ProviderStatus[] = [
	providerStatus('claude', CLAUDE_VIA_CLI, CLAUDE_VIA_CLI, {
		cli: readyRoute(['claude-sonnet', 'claude-opus-cli']),
		api: readyRoute(['claude-opus', 'claude-api'])
	}),
	providerStatus(
		'codex',
		CODEX_VIA_KEY,
		CODEX_VIA_KEY,
		{ cli: readyRoute(['gpt-5-codex']), api: readyRoute(['gpt-5.4']) },
		{ cli: IMAGE_TOOL_READY, api: NO_IMAGE_TOOL }
	),
	providerStatus('grok', GROK_WITHOUT_KEY)
];

function cowriterSettings(overrides: Partial<CowriterSettings> = {}): CowriterSettings {
	return {
		provider: 'claude',
		model: 'claude-sonnet',
		tail_token_budget: 8000,
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: ['claude-sonnet'],
		models_by_provider: {},
		selected_models_by_provider: {},
		models_errors: {},
		models_sources: {},
		current_models_not_in_catalog: {},
		probed_at: {},
		provider_routes: { claude: 'cli', codex: 'cli', grok: 'cli' },
		...overrides
	};
}

function judgeSettings(provider: string, model: string): JudgeSettings {
	return {
		provider,
		model,
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: [model],
		models_by_provider: {},
		models_errors: {},
		probed_at: {}
	};
}

const TAB_LABELS = [
	'Users',
	'Voices',
	'Sessions',
	'Login Attempts',
	'Rate Limits',
	'Generation',
	'Models',
	'ACE-Step'
];

let mounted: ReturnType<typeof mount> | undefined;

function pageOf<T>(items: T[]): PaginatedResponse<T> {
	return { items, total: items.length, offset: 0, limit: 50, has_more: false };
}

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

function taskSelect(target: HTMLElement, task: string, column: string): HTMLSelectElement {
	return requireElement<HTMLSelectElement>(target, `select[aria-label="${task} ${column}"]`);
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
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin' });
	api.fetchUsers.mockResolvedValue([ADMIN_USER, OTHER_USER]);
	api.fetchAdminVoices.mockResolvedValue(VOICES);
	api.fetchSessions.mockResolvedValue(pageOf([SESSION]));
	api.fetchLoginAttempts.mockResolvedValue(pageOf([ATTEMPT]));
	api.fetchRateLimits.mockResolvedValue({ settings: [] });
	api.fetchGenerationDefaults.mockResolvedValue({});
	api.fetchAllModels.mockResolvedValue([]);
	api.fetchBuiltinDefaults.mockResolvedValue({});
	api.fetchProviderStatus.mockResolvedValue(PROVIDER_STATUSES);
	api.fetchCowriterSettings.mockResolvedValue(cowriterSettings());
	api.updateCowriterSettings.mockImplementation(
		async (provider: string, model: string, tailTokenBudget: number) =>
			cowriterSettings({ provider, model, tail_token_budget: tailTokenBudget })
	);
	api.fetchCoverSettings.mockResolvedValue({
		provider: 'codex',
		route: 'cli',
		model: 'gpt-5-codex'
	});
	api.updateCoverSettings.mockImplementation(
		async (provider: string, route: 'cli' | 'api', model: string) => ({ provider, route, model })
	);
	api.fetchJudgeSettings.mockResolvedValue(judgeSettings('claude', 'claude-opus'));
	api.updateJudgeSettings.mockImplementation(async (provider: string, model: string) =>
		judgeSettings(provider, model)
	);
	api.listWorkers.mockResolvedValue({ workers: [] });
	api.getRegistry.mockResolvedValue({ models: [] });
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: VIEWPORT_PX });
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	currentUser.set(null);
	vi.clearAllMocks();
	vi.unstubAllGlobals();
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
		expect(select.value).toBe('users');
		expect(select.classList.contains(COMPACT_SELECT_CLASS)).toBe(true);
		expect(style.width).toBe('100%');
		expect(style.maxWidth).toBe('100%');
		expect(style.minWidth === '0px' || style.minWidth === '0').toBe(true);
	});

	it('restyles the users table into reachable action cards', async () => {
		const target = await renderPage(true);
		const table = requireElement<HTMLTableElement>(target, `.${COMPACT_STACK_CLASS}`);
		const row = requireElement<HTMLTableRowElement>(table, 'tbody tr:not(.inline-form-row)');
		const actions = requireElement<HTMLTableCellElement>(target, 'td.actions');
		const janeRow = Array.from(table.querySelectorAll('tr')).find((el) =>
			el.textContent?.includes('jane')
		);
		if (!janeRow) throw new Error('Expected jane row');

		expect(getComputedStyle(table).display).toBe('block');
		expect(getComputedStyle(requireElement(table, 'thead')).display).toBe('none');
		expect(getComputedStyle(row).display).toBe('flex');
		expect(getComputedStyle(actions).flexWrap).toBe('wrap');
		expect(janeRow.textContent).toContain('Promote');
		expect(janeRow.textContent).toContain('Disable');
		expect(janeRow.textContent).toContain('Reset PW');
		expect(janeRow.textContent).toContain('Delete');
		expect(target.textContent).toContain('You');
	});

	it('keeps reset-password confirm working inside a compact card', async () => {
		const target = await renderPage(true);
		const janeRow = Array.from(target.querySelectorAll('tr')).find((el) =>
			el.textContent?.includes('jane')
		);
		if (!janeRow) throw new Error('Expected jane row');
		const reset = Array.from(janeRow.querySelectorAll('button')).find(
			(button) => button.textContent?.trim() === 'Reset PW'
		);
		if (!reset) throw new Error('Expected Reset PW');
		reset.click();
		await tick();

		const form = requireElement<HTMLFormElement>(target, '.inline-form-row .inline-form');
		expect(form.querySelector('input')?.getAttribute('placeholder')).toBe(
			'New password (min 8 chars)'
		);
		expect(form.textContent).toContain('Save');
		expect(form.textContent).toContain('Cancel');
	});

	it('switches compact tabs to sessions and attempts with their actions', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'sessions');
		expect(target.textContent).toContain('Active Sessions');
		expect(target.textContent).toContain('jane');
		expect(target.textContent).toContain('Revoke');
		expect(getComputedStyle(requireElement(target, `.${COMPACT_STACK_CLASS}`)).display).toBe(
			'block'
		);

		await selectTab(target, 'attempts');
		expect(target.textContent).toContain('Recent Login Attempts');
		expect(target.textContent).toContain('Failed');
		expect(target.querySelector('.tabs button')).toBeNull();
	});

	it('shows every voice as read-only operational state', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'voices');
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
		api.fetchAdminVoices.mockRejectedValueOnce(new Error('Failed to load voices'));
		const target = await renderPage(true);
		await selectTab(target, 'voices');
		const voices = sectionByHeading(target, 'Voice operations');

		expect(voices.textContent).toContain('Failed to load voices');
		expect(voices.textContent).not.toContain('No voices have been created.');
	});

	it('still renders empty user, session, and attempt lists', async () => {
		api.fetchUsers.mockResolvedValue([]);
		api.fetchSessions.mockResolvedValue(pageOf([]));
		api.fetchLoginAttempts.mockResolvedValue(pageOf([]));
		const target = await renderPage(true);

		expect(target.textContent).toContain('Users');
		expect(target.querySelector('.stack-table')).not.toBeNull();
		expect(target.textContent).not.toContain('Promote');

		await selectTab(target, 'sessions');
		expect(target.textContent).toContain('Active Sessions');
		expect(target.textContent).not.toContain('Revoke');

		await selectTab(target, 'attempts');
		expect(target.textContent).toContain('Recent Login Attempts');
		expect(target.textContent).not.toContain('Failed');
	});

	it('keeps desktop tab buttons and a compact table layout off', async () => {
		const target = await renderPage(false);
		const buttons = Array.from(target.querySelectorAll('.tabs button')).map((button) =>
			button.textContent?.trim()
		);
		expect(target.querySelector(`select[aria-label="${ADMIN_TABS_LABEL}"]`)).toBeNull();
		expect(buttons).toEqual(TAB_LABELS);
		expect(getComputedStyle(requireElement(target, '.stack-table')).display).not.toBe('block');
	});
});

describe('admin models tab', () => {
	it('answers who does what in one row per task', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const models = sectionByHeading(target, 'Models');
		expect(taskNames(models)).toEqual(['Co-Writer', 'Cover', 'Scoring']);
		expect(columnNames(models)).toEqual(['Task', 'Provider', 'Route', 'Model', 'Status']);
		expect(headings(target)).not.toContain('Providers');
		expect(models.querySelector('.route-card')).toBeNull();
		expect(saveButtons(models)).toEqual([]);
	});

	it('offers every provider in every task with the state that task gives it', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Co-Writer'))).toEqual([
			'Claude ✓ ready',
			'Codex ✓ ready',
			'Grok · needs its API key'
		]);
		expect(optionLabels(providerSelect(target, 'Cover'))).toEqual([
			'Claude · no image tool',
			'Codex ✓ ready',
			'Grok · no image tool'
		]);
	});

	it('shows each row its live models for the selected route', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(modelSelect(target, 'Co-Writer'))).toEqual([
			'claude-sonnet',
			'claude-opus-cli'
		]);
		expect(optionLabels(modelSelect(target, 'Cover'))).toEqual(['gpt-5-codex']);
	});

	it('greys a route that is not set up and names its reason in the row', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const cover = rowNamed(target, 'Cover');
		expect(routeButton(cover, 'API')).toHaveClass('dead');
		expect(reasons(cover)).toContain('API · no image tool');
	});

	it('stands with the table while the reachability probe is still running', async () => {
		api.fetchProviderStatus.mockReturnValue(new Promise(() => {}));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(taskNames(sectionByHeading(target, 'Models'))).toEqual([
			'Co-Writer',
			'Cover',
			'Scoring'
		]);
		expect(statusText(rowNamed(target, 'Co-Writer'))).toBe('○Checking…');
		expect(providerSelect(target, 'Co-Writer').disabled).toBe(false);
	});

	it('names a failed reachability probe in the row instead of claiming Checking', async () => {
		api.fetchProviderStatus.mockRejectedValue(new Error('Provider probe failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(statusText(rowNamed(target, 'Co-Writer'))).toBe('○Claude · Provider probe failed');
	});

	it('saves the co-writer row with its route map as soon as the model changes', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(modelSelect(target, 'Co-Writer'), 'claude-opus-cli');

		expect(api.updateCowriterSettings).toHaveBeenCalledWith('claude', 'claude-opus-cli', 8000, {
			claude: 'cli',
			codex: 'cli',
			grok: 'cli'
		});
		expect(rowNamed(target, 'Co-Writer').textContent).toContain('Saved.');
	});

	it('saves the cover row with its own provider, route and model', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Cover'), 'claude');

		expect(api.updateCoverSettings).toHaveBeenCalledWith('claude', 'cli', '');
		expect(optionLabels(modelSelect(target, 'Cover'))).toEqual(['No models']);
	});

	it('keeps saving the scoring row against the judge settings', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Scoring'), 'codex');

		expect(api.updateJudgeSettings).toHaveBeenCalledWith('codex', 'gpt-5.4');
		expect(statusText(rowNamed(target, 'Scoring'))).toBe('✓Ready · key set');
	});

	it('shows a scoring provider that cannot answer as its own grey row', async () => {
		api.fetchJudgeSettings.mockResolvedValue({
			provider: 'grok',
			model: '',
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: [],
			models_by_provider: {},
			models_errors: {},
			probed_at: {}
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(statusText(rowNamed(target, 'Scoring'))).toBe('!Needs its API key');
	});

	it('names a rejected save in a red sub-row with a retry', async () => {
		api.updateCowriterSettings.mockRejectedValue(
			new ApiError(422, 'Provider not configured', '/api/settings/cowriter', null, {
				provider: 'grok',
				surface: 'cowriter',
				status: {
					state: 'unconfigured',
					needs: 'api_key',
					setup_method: null,
					environment_key: 'XAI_API_KEY'
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Co-Writer'), 'grok');

		const failure = requireElement(sectionByHeading(target, 'Models'), '.tt-sub.bad');
		expect(failure.textContent).toContain('Grok co-writer: Missing XAI_API_KEY');
		expect(requireElement<HTMLButtonElement>(failure, '.retry').textContent?.trim()).toBe('Retry');

		api.updateCowriterSettings.mockResolvedValue(cowriterSettings({ provider: 'grok', model: '' }));
		requireElement<HTMLButtonElement>(failure, '.retry').click();
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledTimes(2);
		expect(sectionByHeading(target, 'Models').querySelector('.tt-sub.bad')).toBeNull();
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

		expect(api.updateCowriterSettings).toHaveBeenCalledWith('claude', 'claude-sonnet', 24000, {
			claude: 'cli',
			codex: 'cli',
			grok: 'cli'
		});
		expect(disclosure.textContent).toContain('Saved.');
	});
});
