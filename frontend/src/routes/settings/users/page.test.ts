import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
	LoginAttemptItem,
	PaginatedResponse,
	ProviderStatus,
	ProviderSurfaceStatus,
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
function providerStatus(
	provider: string,
	cowriter: ProviderSurfaceStatus,
	judge: ProviderSurfaceStatus = cowriter
): ProviderStatus {
	return { provider, cowriter, judge };
}

const CLAUDE_VIA_CLI: ProviderSurfaceStatus = {
	state: 'configured',
	needs: null,
	setup_method: 'claude_cli',
	environment_key: null
};
const GROK_VIA_CLI: ProviderSurfaceStatus = {
	state: 'configured',
	needs: null,
	setup_method: 'grok_cli',
	environment_key: null
};
const GROK_CLI_NEEDS_API_KEY: ProviderSurfaceStatus = {
	state: 'cli_login_needs_api_key',
	needs: 'api_key',
	setup_method: 'grok_cli',
	environment_key: 'XAI_API_KEY'
};
const NO_CODEX_KEY: ProviderSurfaceStatus = {
	state: 'unconfigured',
	needs: 'api_key',
	setup_method: null,
	environment_key: 'OPENAI_API_KEY'
};
const GROK_CONFIGURED_VIA_CLI: ProviderStatus[] = [
	providerStatus('claude', CLAUDE_VIA_CLI),
	providerStatus('codex', NO_CODEX_KEY),
	providerStatus('grok', GROK_VIA_CLI, GROK_CLI_NEEDS_API_KEY)
];
const CLAUDE_KEY_WITHOUT_CLI: ProviderStatus[] = [
	providerStatus(
		'claude',
		{
			state: 'api_key_needs_cli_login',
			needs: 'cli_login',
			setup_method: 'api_key',
			environment_key: null
		},
		{
			state: 'configured',
			needs: null,
			setup_method: 'api_key',
			environment_key: 'ANTHROPIC_API_KEY'
		}
	),
	providerStatus('codex', NO_CODEX_KEY),
	providerStatus('grok', GROK_VIA_CLI)
];

function routeStatus(
	state: 'ready' | 'not_configured' | 'disturbed',
	models: string[],
	reason?: { code: 'api_key_not_set' | 'catalogue_http_error'; message: string },
	catalogVersion?: string
) {
	return {
		models,
		catalog_version: catalogVersion,
		readiness: {
			state,
			reason: reason ?? null,
			setup_label: 'CLI login'
		}
	};
}

function routeAwareCowriterSettings(overrides: Record<string, unknown> = {}) {
	return {
		provider: 'claude',
		model: 'claude-cli',
		tail_token_budget: 8000,
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: ['claude-cli'],
		models_by_provider: { claude: ['claude-cli'], codex: ['codex-cli'], grok: ['grok-cli'] },
		models_errors: {},
		models_sources: {},
		provider_routes: { claude: 'cli' as const, codex: 'cli' as const, grok: 'cli' as const },
		provider_routes_status: {
			claude: {
				cli: routeStatus('ready', ['claude-cli'], undefined, '1.4.0'),
				api: routeStatus('ready', ['claude-api'], undefined, '2026-09')
			},
			codex: {
				cli: routeStatus('ready', ['codex-cli']),
				api: routeStatus('ready', ['codex-api'])
			},
			grok: {
				cli: routeStatus('ready', ['grok-cli']),
				api: routeStatus('ready', ['grok-api'])
			}
		},
		...overrides
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

function pillNamed(section: HTMLElement, name: string): HTMLButtonElement {
	const pill = Array.from(section.querySelectorAll<HTMLButtonElement>('.provider-pill')).find(
		(el) => el.textContent?.includes(name)
	);
	if (!pill) throw new Error(`Expected a "${name}" provider pill`);
	return pill;
}

function buttonNamed(section: HTMLElement, label: string): HTMLButtonElement {
	const button = Array.from(section.querySelectorAll<HTMLButtonElement>('button')).find((el) =>
		el.textContent?.trim().startsWith(label)
	);
	if (!button) throw new Error(`Expected a button starting with "${label}"`);
	return button;
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
	api.fetchProviderStatus.mockResolvedValue([
		providerStatus('claude', CLAUDE_VIA_CLI),
		providerStatus('codex', {
			state: 'configured',
			needs: null,
			setup_method: 'api_key',
			environment_key: 'OPENAI_API_KEY'
		}),
		providerStatus('grok', {
			state: 'unconfigured',
			needs: 'api_key',
			setup_method: null,
			environment_key: 'XAI_API_KEY'
		})
	]);
	api.fetchCowriterSettings.mockResolvedValue({
		provider: 'claude',
		model: 'claude-sonnet',
		tail_token_budget: 8000,
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: ['claude-sonnet'],
		models_by_provider: { claude: ['claude-sonnet'], codex: [], grok: [] },
		models_errors: {
			codex: 'could not list codex models',
			grok: 'grok is not configured: missing XAI_API_KEY'
		}
	});
	api.fetchJudgeSettings.mockResolvedValue({
		provider: 'claude',
		model: 'claude-opus',
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: ['claude-opus'],
		models_by_provider: { claude: ['claude-opus'], codex: ['gpt-5.4'], grok: [] },
		models_errors: { grok: 'grok is not configured: missing XAI_API_KEY' }
	});
	api.updateJudgeSettings.mockImplementation(async (provider: string, model: string) => ({
		provider,
		model,
		allowed_providers: ['claude', 'codex', 'grok'],
		allowed_models: [model],
		models_by_provider: { claude: ['claude-opus'], codex: ['gpt-5.4'], grok: [] },
		models_errors: { grok: 'grok is not configured: missing XAI_API_KEY' }
	}));
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
	it('shows each provider real reachability with its setup method or missing key', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const providers = sectionByHeading(target, 'Providers');

		expect(providers.textContent).toContain('Claude Code CLI login');
		expect(providers.textContent).toContain('Configured via OPENAI_API_KEY');
		expect(providers.textContent).toContain('Missing XAI_API_KEY');
	});

	it('names the CLI each provider is signed in with', async () => {
		api.fetchProviderStatus.mockResolvedValue([
			providerStatus('claude', CLAUDE_VIA_CLI),
			providerStatus('codex', {
				state: 'configured',
				setup_method: 'codex_cli',
				environment_key: null
			}),
			providerStatus('grok', {
				state: 'configured',
				setup_method: 'grok_cli',
				environment_key: null
			})
		]);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const providers = sectionByHeading(target, 'Providers');

		expect(providers.textContent).toContain('Grok CLI login');
		expect(providers.textContent).toContain('Codex CLI login');
	});

	it('names an unverified provider while its background check is running', async () => {
		api.fetchProviderStatus.mockResolvedValue([
			providerStatus('claude', {
				state: 'unverified',
				probed_at: '2026-09-03T09:00:00Z'
			})
		]);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('Provider check is still running in the background');
		expect(requireElement(providers, '.provider-status-row')).toHaveClass('unverified');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		expect(pillNamed(cowriter, 'Claude')).toMatchObject({
			disabled: true,
			textContent: expect.stringContaining('Unchecked')
		});
		expect(cowriter.textContent).toContain('Provider check is still running in the background');
	});

	it('offers Grok through its CLI login to the co-writer but not scoring', async () => {
		api.fetchProviderStatus.mockResolvedValue(GROK_CONFIGURED_VIA_CLI);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(pillNamed(sectionByHeading(target, 'Co-Writer'), 'Grok').disabled).toBe(false);
		const scoring = sectionByHeading(target, 'Scoring');
		expect(pillNamed(scoring, 'Grok').disabled).toBe(true);
		expect(scoring.textContent).toContain('answering needs its API key');
		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('Configured via Grok CLI login');
		expect(providers.textContent).toContain(
			'Grok CLI login found — but answering needs its API key'
		);
	});

	it('names a missing dependency and a missing status without inventing an API key', async () => {
		api.fetchProviderStatus.mockResolvedValue([
			providerStatus('claude', {
				state: 'missing_dependency',
				needs: null,
				setup_method: null,
				environment_key: null,
				missing_dependency: 'anthropic'
			})
		]);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(sectionByHeading(target, 'Providers').textContent).toContain('Missing anthropic');
		expect(sectionByHeading(target, 'Co-Writer').textContent).toContain(
			'Provider status is unavailable'
		);
		expect(target.textContent).not.toContain('Missing undefined');
	});

	it('shows a provider-status fetch failure instead of loading forever', async () => {
		api.fetchProviderStatus.mockRejectedValue(new Error('Provider probe failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('Provider probe failed');
		expect(providers.textContent).not.toContain('Loading...');
	});

	it('does not show stale reachability after a provider-status refresh fails', async () => {
		api.fetchProviderStatus
			.mockResolvedValueOnce([providerStatus('claude', CLAUDE_VIA_CLI)])
			.mockRejectedValueOnce(new Error('Provider refresh failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');
		expect(sectionByHeading(target, 'Providers').textContent).toContain('Claude Code CLI login');

		await selectTab(target, 'models');
		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('Provider refresh failed');
		expect(providers.textContent).not.toContain('Claude Code CLI login');
	});

	it('keeps known reachability enabled while refreshing it', async () => {
		let resolveRefresh: ((statuses: ProviderStatus[]) => void) | undefined;
		const refresh = new Promise<ProviderStatus[]>((resolve) => {
			resolveRefresh = resolve;
		});
		api.fetchProviderStatus
			.mockResolvedValueOnce([providerStatus('claude', CLAUDE_VIA_CLI)])
			.mockReturnValueOnce(refresh);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await selectTab(target, 'models');
		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('Refreshing provider status...');
		expect(providers.textContent).toContain('Claude Code CLI login');
		expect(pillNamed(sectionByHeading(target, 'Co-Writer'), 'Claude').disabled).toBe(false);

		resolveRefresh?.([providerStatus('claude', CLAUDE_VIA_CLI)]);
		await flush();
		expect(providers.textContent).not.toContain('Refreshing provider status...');
	});

	it('names an empty provider-status response as empty', async () => {
		api.fetchProviderStatus.mockResolvedValue([]);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const providers = sectionByHeading(target, 'Providers');
		expect(providers.textContent).toContain('No provider status is available.');
		expect(providers.textContent).not.toContain('Loading...');
	});

	it('offers a Claude API key to the judge but not the co-writer', async () => {
		api.fetchProviderStatus.mockResolvedValue(CLAUDE_KEY_WITHOUT_CLI);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(pillNamed(sectionByHeading(target, 'Scoring'), 'Claude').disabled).toBe(false);
		const cowriter = sectionByHeading(target, 'Co-Writer');
		expect(pillNamed(cowriter, 'Claude').disabled).toBe(true);
		expect(cowriter.textContent).toContain('answering needs the Claude Code CLI login');
	});

	it('spells out both surfaces when their reachability differs', async () => {
		api.fetchProviderStatus.mockResolvedValue(CLAUDE_KEY_WITHOUT_CLI);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const providers = sectionByHeading(target, 'Providers');

		expect(providers.textContent).toContain('co-writer:');
		expect(providers.textContent).toContain('judge:');
	});

	it('disables picking an unconfigured provider in the co-writer picker', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(pillNamed(cowriter, 'Grok').disabled).toBe(true);
	});

	it('shows the catalog failure reason for a provider that is viewed but not saved', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		pillNamed(cowriter, 'Codex').click();
		await tick();

		expect(cowriter.textContent).toContain('could not list codex models');
	});

	it('disables Save Co-Writer once switched to a provider with no valid model', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		pillNamed(cowriter, 'Codex').click();
		await tick();

		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(true);
		expect(cowriter.textContent).toContain('Choose a model before saving.');
	});

	it('activates Codex with its CLI catalog and names its source', async () => {
		const codexCatalog = ['gpt-5.6-terra', 'gpt-5.6'];
		api.fetchCowriterSettings.mockResolvedValue({
			provider: 'claude',
			model: 'claude-sonnet',
			tail_token_budget: 8000,
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: ['claude-sonnet'],
			models_by_provider: {
				claude: ['claude-sonnet'],
				codex: codexCatalog,
				grok: []
			},
			models_errors: {},
			models_sources: { codex: 'known models for the CLI route' }
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		pillNamed(cowriter, 'Codex').click();
		await tick();

		expect(cowriter.textContent).toContain('known models for the CLI route');
		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model').value).toBe(
			codexCatalog[0]
		);
		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(false);
	});

	it('disables picking an unconfigured provider in the scoring picker', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const scoring = sectionByHeading(target, 'Scoring');

		expect(pillNamed(scoring, 'Grok').disabled).toBe(true);
	});

	it('disables Save and shows "Nothing changed" right after a clean load', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const scoring = sectionByHeading(target, 'Scoring');

		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(true);
		expect(cowriter.textContent).toContain('Nothing changed.');
		expect(buttonNamed(scoring, 'Save Scoring').disabled).toBe(true);
		expect(scoring.textContent).toContain('Nothing changed.');
	});

	it('selects the active full model ID supplied by the catalog', async () => {
		api.fetchCowriterSettings.mockResolvedValue({
			provider: 'claude',
			model: 'claude-opus-4-6',
			tail_token_budget: 8000,
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: ['claude-opus-4-6', 'haiku', 'opus', 'sonnet'],
			models_by_provider: {
				claude: ['claude-opus-4-6', 'haiku', 'opus', 'sonnet'],
				codex: [],
				grok: []
			},
			models_errors: {}
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model').value).toBe(
			'claude-opus-4-6'
		);
	});

	it('has no Chat Model field anymore', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(target.textContent).not.toContain('Chat Model');
	});

	it('opens without claiming unsaved changes when the saved provider has no live catalog', async () => {
		api.fetchCowriterSettings.mockResolvedValue({
			provider: 'claude',
			model: 'claude-sonnet',
			tail_token_budget: 8000,
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: [],
			models_by_provider: { claude: [], codex: [], grok: [] },
			models_errors: { claude: 'could not list claude models' }
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const modelSelect = requireElement<HTMLSelectElement>(cowriter, '#cowriter-model');

		expect(cowriter.textContent).toContain('Nothing changed.');
		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(true);
		expect(modelSelect.value).toBe('claude-sonnet');
		expect(modelSelect.disabled).toBe(true);
	});

	it('keeps a saved model missing from the catalog selectable and honestly labelled', async () => {
		api.fetchCowriterSettings.mockResolvedValue({
			provider: 'claude',
			model: 'claude-opus-4-6',
			tail_token_budget: 8000,
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: ['opus', 'claude-opus-4-6'],
			models_by_provider: { claude: ['opus', 'claude-opus-4-6'], codex: [], grok: [] },
			models_errors: {},
			current_models_not_in_catalog: { claude: 'claude-opus-4-6' }
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model').value).toBe(
			'claude-opus-4-6'
		);
		expect(cowriter.textContent).toContain('claude-opus-4-6 (current, not in catalog)');
		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(true);
		expect(cowriter.textContent).toContain('Nothing changed.');
	});

	it('shows each route state, redacts API keys, and changes the model catalog with the selected route', async () => {
		api.fetchCowriterSettings.mockResolvedValue(routeAwareCowriterSettings());
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(cowriter.textContent).toContain('CLI · ready');
		expect(cowriter.textContent).toContain('API · ready');
		expect(cowriter.textContent).toContain('key: set');
		expect(cowriter.textContent).toContain('Version 1.4.0');
		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').value).toBe(
			'claude-cli'
		);

		buttonNamed(cowriter, 'API').click();
		await tick();

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').value).toBe(
			'claude-api'
		);
		expect(cowriter.textContent).toContain('Version 2026-09');
	});

	it('keeps the selected route catalog when the saved provider is selected again', async () => {
		api.fetchCowriterSettings.mockResolvedValue(routeAwareCowriterSettings());
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		buttonNamed(cowriter, 'API').click();
		await tick();
		buttonNamed(cowriter, 'Claude').click();
		await tick();

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').value).toBe(
			'claude-api'
		);
	});

	it('uses the selected provider card default and cannot save a model from another card', async () => {
		api.fetchCowriterSettings.mockResolvedValue(routeAwareCowriterSettings());
		api.updateCowriterSettings.mockResolvedValue(
			routeAwareCowriterSettings({ provider: 'grok', model: 'grok-cli' })
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const claudeModel = requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude');
		const grokModel = requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-grok');

		buttonNamed(cowriter, 'Grok').click();
		await tick();

		expect(grokModel.value).toBe('grok-cli');
		expect(claudeModel.disabled).toBe(true);
		expect(grokModel.disabled).toBe(false);

		buttonNamed(cowriter, 'Save Co-Writer').click();
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledWith('grok', 'grok-cli', 8000, {
			claude: 'cli',
			codex: 'cli',
			grok: 'cli'
		});
	});

	it('keeps the saved card model when switching away and back', async () => {
		const settings = routeAwareCowriterSettings({ provider: 'grok', model: 'grok-4.6' });
		settings.provider_routes_status.grok.cli = routeStatus('ready', ['grok-4.5', 'grok-4.6']);
		api.fetchCowriterSettings.mockResolvedValue(settings);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const grokModel = requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-grok');

		expect(grokModel.value).toBe('grok-4.6');
		buttonNamed(cowriter, 'Claude').click();
		await tick();
		expect(grokModel.value).toBe('grok-4.6');

		buttonNamed(cowriter, 'Grok').click();
		await tick();
		expect(grokModel.value).toBe('grok-4.6');
	});

	it('shows every provider card model returned after a reload', async () => {
		const settings = routeAwareCowriterSettings({
			provider: 'codex',
			model: 'codex-cli',
			selected_models_by_provider: {
				claude: 'claude-cli',
				codex: 'codex-cli',
				grok: 'grok-4.6'
			}
		});
		settings.provider_routes_status.grok.cli = routeStatus('ready', ['grok-4.5', 'grok-4.6']);
		api.fetchCowriterSettings.mockResolvedValue(settings);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').value).toBe(
			'claude-cli'
		);
		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-codex').value).toBe(
			'codex-cli'
		);
		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-grok').value).toBe(
			'grok-4.6'
		);
	});

	it('keeps the stored model selectable when the selected route no longer catalogs it', async () => {
		api.fetchCowriterSettings.mockResolvedValue(
			routeAwareCowriterSettings({
				model: 'claude-legacy',
				allowed_models: ['claude-legacy', 'claude-cli'],
				provider_routes_status: {
					claude: {
						cli: {
							...routeStatus('ready', ['claude-cli', 'claude-legacy']),
							retained_model_id: 'claude-legacy'
						},
						api: routeStatus('ready', ['claude-api'])
					}
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').value).toBe(
			'claude-legacy'
		);
		expect(cowriter.textContent).toContain('claude-legacy (current, not in catalog)');
	});

	it('shows a selected broken route as a blocked turn without silently falling back', async () => {
		api.fetchCowriterSettings.mockResolvedValue(
			routeAwareCowriterSettings({
				provider_routes: { claude: 'api', codex: 'cli', grok: 'cli' },
				provider_routes_status: {
					claude: {
						cli: routeStatus('ready', ['claude-cli']),
						api: routeStatus('disturbed', [], {
							code: 'catalogue_http_error',
							message: 'Rate limit exceeded'
						})
					}
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(cowriter.textContent).toContain('API · broken');
		expect(cowriter.textContent).toContain('Turn blocked');
		expect(cowriter.textContent).toContain('Rate limit exceeded');
		expect(cowriter.textContent).toContain('Choose a ready route to continue.');
		expect(requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude').disabled).toBe(
			true
		);
	});

	it('names routes that are not set up and saves the complete route choice with the model', async () => {
		const saved = routeAwareCowriterSettings({
			provider_routes: { claude: 'api', codex: 'cli', grok: 'cli' },
			model: 'claude-api',
			allowed_models: ['claude-api']
		});
		api.fetchCowriterSettings.mockResolvedValue(
			routeAwareCowriterSettings({
				provider_routes_status: {
					claude: {
						cli: routeStatus('not_configured', [], {
							code: 'catalogue_http_error',
							message: 'CLI login required'
						}),
						api: routeStatus('not_configured', [], {
							code: 'api_key_not_set',
							message: 'API key is missing'
						})
					}
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');

		expect(cowriter.textContent).toContain('CLI · not set up');
		expect(cowriter.textContent).toContain('API · not set up');
		expect(cowriter.textContent).toContain('key: not set');

		api.fetchCowriterSettings.mockResolvedValue(routeAwareCowriterSettings());
		api.updateCowriterSettings.mockResolvedValue(saved);
		await selectTab(target, 'models');
		buttonNamed(cowriter, 'API').click();
		await tick();
		buttonNamed(cowriter, 'Save Co-Writer').click();
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledWith('claude', 'claude-api', 8000, {
			claude: 'api',
			codex: 'cli',
			grok: 'cli'
		});
	});

	it('shows no invented model when no route is ready', async () => {
		api.fetchCowriterSettings.mockResolvedValue(
			routeAwareCowriterSettings({
				provider_routes_status: {
					claude: {
						cli: routeStatus('not_configured', []),
						api: routeStatus('not_configured', [])
					},
					codex: {
						cli: routeStatus('not_configured', []),
						api: routeStatus('not_configured', [])
					},
					grok: {
						cli: routeStatus('not_configured', []),
						api: routeStatus('not_configured', [])
					}
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const modelSelect = requireElement<HTMLSelectElement>(cowriter, '#cowriter-model-claude');

		expect(cowriter.textContent).toContain('Provider unavailable');
		expect(modelSelect.disabled).toBe(true);
		expect(optionLabels(modelSelect)).toEqual(['No models available']);
	});

	it('lets a history-tail-only change stay saveable when the saved provider has no live catalog', async () => {
		api.fetchCowriterSettings.mockResolvedValue({
			provider: 'claude',
			model: 'claude-sonnet',
			tail_token_budget: 8000,
			allowed_providers: ['claude', 'codex', 'grok'],
			allowed_models: [],
			models_by_provider: { claude: [], codex: [], grok: [] },
			models_errors: { claude: 'could not list claude models' }
		});
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const budgetInput = requireElement<HTMLInputElement>(cowriter, '#cowriter-budget');
		budgetInput.value = '30000';
		budgetInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect(buttonNamed(cowriter, 'Save Co-Writer').disabled).toBe(false);
	});

	it('renders a provider configuration error from its structured detail', async () => {
		api.updateCowriterSettings.mockRejectedValueOnce(
			new ApiError(422, '', '/api/settings/cowriter', null, {
				provider: 'grok',
				surface: 'cowriter',
				status: {
					state: 'unconfigured',
					needs: 'api_key',
					environment_key: 'XAI_API_KEY'
				}
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const budgetInput = requireElement<HTMLInputElement>(cowriter, '#cowriter-budget');
		budgetInput.value = '30000';
		budgetInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		buttonNamed(cowriter, 'Save Co-Writer').click();
		await flush();

		expect(target.querySelector('.error')?.textContent).toBe('Grok co-writer: Missing XAI_API_KEY');
	});

	it('falls back to the generic error message for a malformed provider detail', async () => {
		api.updateCowriterSettings.mockRejectedValueOnce(
			new ApiError(422, 'Could not save co-writer settings', '/api/settings/cowriter', null, {
				provider: 'grok',
				surface: 'cowriter',
				status: { state: 'unknown' }
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const budgetInput = requireElement<HTMLInputElement>(cowriter, '#cowriter-budget');
		budgetInput.value = '30000';
		budgetInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		buttonNamed(cowriter, 'Save Co-Writer').click();
		await flush();

		expect(target.querySelector('.error')?.textContent).toBe('Could not save co-writer settings');
	});

	it('names a missing CLI setup method in a structured provider detail', async () => {
		api.updateCowriterSettings.mockRejectedValueOnce(
			new ApiError(422, '', '/api/settings/cowriter', null, {
				provider: 'grok',
				surface: 'cowriter',
				status: { state: 'cli_login_needs_api_key', needs: 'api_key' }
			})
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const cowriter = sectionByHeading(target, 'Co-Writer');
		const budgetInput = requireElement<HTMLInputElement>(cowriter, '#cowriter-budget');
		budgetInput.value = '30000';
		budgetInput.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		buttonNamed(cowriter, 'Save Co-Writer').click();
		await flush();

		expect(target.querySelector('.error')?.textContent).toBe(
			'Grok co-writer: required CLI login found — but answering needs its API key'
		);
	});

	it('loads and saves the scoring block against /api/settings/judge', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');
		const scoring = sectionByHeading(target, 'Scoring');
		expect(scoring.textContent).toContain('claude-opus');

		pillNamed(scoring, 'Codex').click();
		await tick();
		const modelSelect = requireElement<HTMLSelectElement>(scoring, '#judge-model');
		modelSelect.value = 'gpt-5.4';
		modelSelect.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();

		const saveButton = buttonNamed(scoring, 'Save Scoring');
		expect(saveButton.disabled).toBe(false);
		saveButton.click();
		await flush();

		expect(api.updateJudgeSettings).toHaveBeenCalledWith('codex', 'gpt-5.4');
	});
});
