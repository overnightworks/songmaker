import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { resolve } from '$app/paths';
import { goto } from '$app/navigation';
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
	SafeRouteReason,
	SessionItem,
	UserItem
} from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { lostNetwork, serverRefusal } from '$lib/test-utils/network';
import {
	ADMIN_SESSION_ALREADY_ENDED_MESSAGE,
	ADMIN_TABS_LABEL,
	ADMIN_VOICES_EMPTY,
	COMPACT_LAYOUT_MEDIA,
	MODELS_SAVE_FAILED_FALLBACK,
	PASSWORD_MIN_LENGTH,
	UNREACHABLE_RELOAD_DELAYS_MS
} from '$lib/constants';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
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
	user_agent: 'vitest',
	is_current: false
};
const OWN_SESSION: SessionItem = {
	...SESSION,
	id: 's0',
	user_id: 'u1',
	username: 'felix',
	is_current: true
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

function judgeSettings(
	provider: string,
	model: string,
	route: 'cli' | 'api' = 'api'
): JudgeSettings {
	return {
		provider,
		route,
		provider_routes_status: {},
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
	window.history.replaceState({}, '', '/settings/users');
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin' });
	api.fetchUsers.mockResolvedValue([ADMIN_USER, OTHER_USER]);
	api.fetchAdminVoices.mockResolvedValue(VOICES);
	api.fetchSessions.mockResolvedValue(pageOf([SESSION]));
	api.forceLogout.mockResolvedValue(undefined);
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
	api.updateJudgeSettings.mockImplementation(
		async (provider: string, route: 'cli' | 'api', model: string) =>
			judgeSettings(provider, model, route)
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
		['', 'users'],
		['?tab=unknown', 'users']
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
		await goto(resolve('/settings/users?tab=voices'));
		await flush();
		expect(select.value).toBe('voices');
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
			`New password (min ${PASSWORD_MIN_LENGTH} chars)`
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

	it.each([true, false])(
		'refetches sessions on every opening without a reload (compact: %s)',
		async (compact) => {
			const target = await renderPage(compact);
			for (const [index, label] of ['Sessions', 'Users', 'Sessions'].entries()) {
				const newSession = {
					...SESSION,
					id: `new-session-${index}`,
					username: `new-user-${index}`
				};
				api.fetchSessions.mockClear();
				api.fetchSessions.mockResolvedValue(pageOf([newSession]));
				if (compact) {
					await selectTab(target, label.toLowerCase());
				} else {
					const button = Array.from(
						target.querySelectorAll<HTMLButtonElement>('.tabs button')
					).find((button) => button.textContent?.trim() === label);
					if (!button) throw new Error(`Expected ${label} tab`);
					button.click();
					await flush();
				}
				if (label === 'Sessions') {
					expect(api.fetchSessions).toHaveBeenCalledTimes(1);
					expect(sectionByHeading(target, 'Active Sessions').textContent).not.toContain('jane');
					expect(sectionByHeading(target, 'Active Sessions').textContent).toContain(
						newSession.username
					);
					expect(target.textContent).toContain('Revoke');
				}
			}
		}
	);

	it.each([
		{
			action: 'editing the username',
			selector: 'input[placeholder="Username"]',
			value: '',
			event: 'input'
		},
		{
			action: 'editing the password',
			selector: 'input[placeholder="Password"]',
			value: '',
			event: 'input'
		},
		{ action: 'changing the role', selector: 'select', value: 'admin', event: 'change' },
		{ action: 'submitting again', selector: null, value: '', event: 'submit' }
	])('clears a create-user refusal on $action', async ({ selector, value, event }) => {
		api.createUser.mockRejectedValueOnce(serverRefusal('Username already exists'));
		const target = await renderPage(true);
		const form = requireElement<HTMLFormElement>(target, '.create-form');
		for (const [placeholder, value] of [
			['Username', 'jane'],
			['Password', 'example-password']
		]) {
			const input = requireElement<HTMLInputElement>(form, `input[placeholder="${placeholder}"]`);
			input.value = value;
			input.dispatchEvent(new Event('input', { bubbles: true }));
		}
		form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
		await flush();
		expect(target.textContent).toContain('Username already exists');

		if (selector) {
			const field = requireElement<HTMLInputElement | HTMLSelectElement>(form, selector);
			field.value = value;
			field.dispatchEvent(new Event(event, { bubbles: true }));
		} else {
			api.createUser.mockImplementationOnce(() => new Promise(() => {}));
			form.dispatchEvent(new Event(event, { bubbles: true, cancelable: true }));
		}
		await flush();

		expect(target.querySelector('.error')).toBeNull();
		if (selector?.startsWith('input')) {
			expect(form.checkValidity()).toBe(false);
			form.requestSubmit();
			await flush();
			expect(target.querySelector('.error')).toBeNull();
		}
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
		api.fetchAdminVoices.mockRejectedValueOnce(serverRefusal('Voice index is rebuilding'));
		const target = await renderPage(true);
		await selectTab(target, 'voices');
		const voices = sectionByHeading(target, 'Voice operations');

		expect(voices.textContent).toContain('Voice index is rebuilding');
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

function typeInto(form: HTMLFormElement, placeholder: string, value: string): void {
	const input = requireElement<HTMLInputElement>(form, `input[placeholder="${placeholder}"]`);
	input.value = value;
	input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function submitCreate(target: HTMLElement): Promise<HTMLFormElement> {
	const form = requireElement<HTMLFormElement>(target, '.create-form');
	typeInto(form, 'Username', 'jane');
	typeInto(form, 'Password', 'example-password');
	form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
	await flush();
	return form;
}

describe('admin sessions, revokes and the errors they leave', () => {
	const KIM_SESSION: SessionItem = { ...SESSION, id: 's2', user_id: 'u3', username: 'kim' };
	const USERS_TAB_REFUSAL = 'Cannot remove the last admin';

	function rowOf(section: HTMLElement, username: string): HTMLElement {
		const row = Array.from(section.querySelectorAll<HTMLElement>('tbody tr')).find(
			(el) => el.querySelector('[data-label="User"]')?.textContent?.trim() === username
		);
		if (!row) throw new Error(`Expected a session row for ${username}`);
		return row;
	}

	/**
	 * The server's live sessions: a revoke ends one, a session it no longer has
	 * answers 404, and the returned function ends one from another tab.
	 */
	function serveSessions(initial: SessionItem[]): (sessionId: string) => void {
		let live = initial;
		const end = (sessionId: string): void => {
			live = live.filter((session) => session.id !== sessionId);
		};
		api.fetchSessions.mockImplementation(async () => pageOf(live));
		api.forceLogout.mockImplementation(async (sessionId: string) => {
			if (!live.some((session) => session.id === sessionId)) {
				throw new ApiError(404, 'Not Found', `/api/admin/sessions/${sessionId}`);
			}
			end(sessionId);
		});
		return end;
	}

	async function revoke(target: HTMLElement, username: string): Promise<void> {
		requireElement<HTMLButtonElement>(
			rowOf(sectionByHeading(target, 'Active Sessions'), username),
			'button'
		).click();
		await flush();
	}

	function sessionUsernames(target: HTMLElement): string[] {
		return Array.from(
			sectionByHeading(target, 'Active Sessions').querySelectorAll('[data-label="User"]')
		).map((el) => el.textContent?.trim() ?? '');
	}

	function errorLines(target: HTMLElement): string[] {
		return Array.from(target.querySelectorAll('.error')).map((el) => el.textContent?.trim() ?? '');
	}

	async function refuseDisabling(target: HTMLElement, username: string): Promise<void> {
		api.updateUser.mockRejectedValueOnce(serverRefusal(USERS_TAB_REFUSAL));
		const row = Array.from(target.querySelectorAll<HTMLElement>('tbody tr')).find(
			(el) => el.querySelector('[data-label="Username"]')?.textContent?.trim() === username
		);
		if (!row) throw new Error(`Expected a user row for ${username}`);
		const disable = Array.from(row.querySelectorAll<HTMLButtonElement>('button')).find(
			(button) => button.textContent?.trim() === 'Disable'
		);
		if (!disable) throw new Error(`Expected a Disable button for ${username}`);
		disable.click();
		await flush();
	}

	it.each([true, false])(
		'marks the own session This device and offers Revoke only on the others (compact: %s)',
		async (compact) => {
			api.fetchSessions.mockResolvedValue(pageOf([OWN_SESSION, SESSION]));
			const target = await renderPage(compact);
			if (compact) await selectTab(target, 'sessions');
			else {
				const button = Array.from(target.querySelectorAll<HTMLButtonElement>('.tabs button')).find(
					(el) => el.textContent?.trim() === 'Sessions'
				);
				button?.click();
				await flush();
			}
			const sessions = sectionByHeading(target, 'Active Sessions');
			const own = rowOf(sessions, 'felix');
			const other = rowOf(sessions, 'jane');

			expect(own.querySelector('.actions')?.textContent?.trim()).toBe('This device');
			expect(own.querySelector('button')).toBeNull();
			expect(other.querySelector('button')?.textContent?.trim()).toBe('Revoke');
		}
	);

	it('shows a create refusal inside the create form, not in the page banner', async () => {
		api.createUser.mockRejectedValueOnce(serverRefusal('Username already exists'));
		const target = await renderPage(true);
		await submitCreate(target);

		expect(sectionByHeading(target, 'Create User').textContent).toContain(
			'Username already exists'
		);
		expect(target.querySelectorAll('.error')).toHaveLength(1);
	});

	it('typing in the create form clears its own refusal and leaves the Users error standing', async () => {
		api.createUser.mockRejectedValueOnce(serverRefusal('Username already exists'));
		const target = await renderPage(true);
		await refuseDisabling(target, 'jane');
		const form = await submitCreate(target);
		expect(target.textContent).toContain('Username already exists');

		typeInto(form, 'Username', 'janet');
		await flush();

		expect(target.textContent).not.toContain('Username already exists');
		expect(errorLines(target)).toEqual([USERS_TAB_REFUSAL]);
	});

	it('a revoke of a session that already ended drops its row and says it had already ended', async () => {
		const endElsewhere = serveSessions([OWN_SESSION, SESSION]);
		const target = await renderPage(true);
		await selectTab(target, 'sessions');
		endElsewhere(SESSION.id);

		await revoke(target, 'jane');

		expect(sessionUsernames(target)).toEqual(['felix']);
		expect(errorLines(target)).toEqual([ADMIN_SESSION_ALREADY_ENDED_MESSAGE]);
	});

	it('a revoke that works clears the line an earlier revoke left', async () => {
		const endElsewhere = serveSessions([OWN_SESSION, SESSION, KIM_SESSION]);
		const target = await renderPage(true);
		await selectTab(target, 'sessions');
		endElsewhere(SESSION.id);
		await revoke(target, 'jane');
		expect(errorLines(target)).toEqual([ADMIN_SESSION_ALREADY_ENDED_MESSAGE]);

		await revoke(target, 'kim');

		expect(sessionUsernames(target)).toEqual(['felix']);
		expect(errorLines(target)).toEqual([]);
	});

	it('switching tabs drops the error of the tab it leaves, and coming back does not restore it', async () => {
		const endElsewhere = serveSessions([OWN_SESSION, SESSION]);
		const target = await renderPage(true);
		await selectTab(target, 'sessions');
		endElsewhere(SESSION.id);
		await revoke(target, 'jane');

		await selectTab(target, 'users');
		expect(errorLines(target)).toEqual([]);

		await selectTab(target, 'sessions');
		expect(errorLines(target)).toEqual([]);
	});

	it('a successful create clears the error the Users tab showed', async () => {
		const target = await renderPage(true);
		await refuseDisabling(target, 'jane');
		expect(errorLines(target)).toEqual([USERS_TAB_REFUSAL]);

		await submitCreate(target);

		expect(errorLines(target)).toEqual([]);
	});

	it('takes every password minimum from the one shared constant', async () => {
		const target = await renderPage(true);
		const janeRow = Array.from(target.querySelectorAll('tr')).find((el) =>
			el.textContent?.includes('jane')
		);
		const reset = Array.from(janeRow?.querySelectorAll('button') ?? []).find(
			(button) => button.textContent?.trim() === 'Reset PW'
		);
		reset?.click();
		await tick();

		const passwordInputs = Array.from(
			target.querySelectorAll<HTMLInputElement>('input[type="password"]')
		);
		expect(passwordInputs).toHaveLength(2);
		for (const input of passwordInputs) expect(input.minLength).toBe(PASSWORD_MIN_LENGTH);

		const resetForm = requireElement<HTMLFormElement>(target, '.inline-form-row .inline-form');
		const resetInput = requireElement<HTMLInputElement>(resetForm, 'input');
		resetInput.value = 'x'.repeat(PASSWORD_MIN_LENGTH - 1);
		resetInput.dispatchEvent(new Event('input', { bubbles: true }));
		resetForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
		await flush();

		expect(target.textContent).toContain(
			`Password must be at least ${PASSWORD_MIN_LENGTH} characters`
		);
		expect(api.updateUser).not.toHaveBeenCalled();
	});
});

describe('admin error ownership (#1447)', () => {
	function userRow(target: HTMLElement): HTMLElement {
		const row = Array.from(target.querySelectorAll<HTMLElement>('tbody tr')).find(
			(el) => el.querySelector('[data-label="Username"]')?.textContent?.trim() === 'jane'
		);
		if (!row) throw new Error('Expected jane in the user list');
		return row;
	}

	function clickNamed(target: HTMLElement, label: string): void {
		const button = Array.from(target.querySelectorAll<HTMLButtonElement>('button')).find(
			(el) => el.textContent?.trim() === label
		);
		if (!button) throw new Error(`Expected ${label}`);
		button.click();
	}

	async function userAction(target: HTMLElement, action: string): Promise<void> {
		clickNamed(userRow(target), action);
		await flush();
		if (action === 'Reset PW' || action === 'Delete') {
			const form = requireElement<HTMLFormElement>(target, '.inline-form-row form');
			const input = requireElement<HTMLInputElement>(form, 'input');
			input.value = action === 'Delete' ? 'jane' : 'example-password';
			input.dispatchEvent(new Event('input', { bubbles: true }));
			form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
			await flush();
		}
	}

	it.each([
		{
			cause: 'rate limit',
			failure: new ApiError(429, 'Too Many Requests', '/api/admin/sessions/s1'),
			message: 'Too many requests. Wait before revoking the session again.'
		},
		{
			cause: 'unreachable server',
			failure: lostNetwork(),
			message: 'Could not reach the server. Try revoking the session again when connected.'
		},
		{
			cause: 'unknown failure',
			failure: new Error('private browser detail'),
			message: 'Could not revoke the session. Try again.'
		}
	])('defect:#920-10 names the revoke cause: $cause', async ({ failure, message }) => {
		api.forceLogout.mockRejectedValueOnce(failure);
		const target = await renderPage(true);
		await selectTab(target, 'sessions');
		clickNamed(target, 'Revoke');
		await flush();
		expect(requireElement(target, '.error').textContent).toBe(message);
	});

	beforeEach(() => {
		window.history.replaceState({}, '', '/settings/users');
		api.updateUser.mockReset();
		api.hardDeleteUser.mockReset();
		api.fetchUserRateLimits.mockReset();
	});

	const limits = {
		overrides: [],
		effective: [{ setting_key: 'generation_rate_limit', value: 10, is_override: false }]
	};
	const races = [
		{ action: 'Disable', tab: 'users', request: 'updateUser' },
		{ action: 'Promote', tab: 'users', request: 'updateUser' },
		{ action: 'Reset PW', tab: 'users', request: 'updateUser' },
		{ action: 'Delete', tab: 'users', request: 'hardDeleteUser' },
		{ action: 'Revoke', tab: 'sessions', request: 'forceLogout' },
		{ action: 'Revoke already ended', tab: 'sessions', request: 'forceLogout' },
		{ action: 'Save Defaults', tab: 'ratelimits', request: 'updateRateLimits' },
		{ action: 'Save Overrides', tab: 'ratelimits', request: 'updateUserRateLimits' },
		{ action: 'Clear All', tab: 'ratelimits', request: 'deleteUserRateLimits' },
		{ action: 'Save Defaults', tab: 'generation', request: 'updateGenerationDefaults' },
		{ action: 'MODEL ON', tab: 'acestep', request: 'toggleModel' }
	] as const;

	it.each([
		...races.flatMap((scenario) =>
			[false, true].map((returnBeforeReply) => ({
				...scenario,
				returnBeforeReply,
				freshError: false
			}))
		),
		...races
			.filter(({ tab }) => tab === 'users')
			.map((scenario) => ({
				...scenario,
				returnBeforeReply: true,
				freshError: true
			})),
		{
			action: 'Create',
			tab: 'users',
			request: 'createUser',
			returnBeforeReply: true,
			freshError: true
		} as const
	])(
		'defect:#920-11 ignores stale $tab $action completion (return: $returnBeforeReply, fresh error: $freshError)',
		async ({ action, tab, request, returnBeforeReply, freshError }) => {
			let rejectRequest!: (reason: unknown) => void;
			let resolveRequest!: (value: unknown) => void;
			api[request].mockImplementationOnce(
				() =>
					new Promise((resolve, reject) => {
						resolveRequest = resolve;
						rejectRequest = reject;
					})
			);
			api.fetchRateLimits.mockResolvedValue({
				settings: [{ setting_key: 'generation_rate_limit', value: 10 }]
			});
			api.fetchUserRateLimits.mockResolvedValue(limits);
			api.fetchAllModels.mockResolvedValue([{ id: 'model', is_active: true }]);
			const target = await renderPage(true);
			await selectTab(target, tab);
			if (action === 'Create') await submitCreate(target);
			else if (tab === 'users') await userAction(target, action);
			else if (action === 'Save Overrides' || action === 'Clear All') {
				userRow(target).click();
				await flush();
				if (action === 'Save Overrides') {
					const input = requireElement<HTMLInputElement>(target, '.override-row input');
					input.value = '5';
					input.dispatchEvent(new Event('input', { bubbles: true }));
				}
				requireElement<HTMLElement>(
					target,
					action === 'Clear All' ? '.override-actions .clear-btn' : '.override-actions .save-btn'
				).click();
			} else clickNamed(target, action === 'Revoke already ended' ? 'Revoke' : action);
			await flush();
			await selectTab(target, 'voices');
			if (returnBeforeReply) await selectTab(target, tab);
			const freshMessage = 'Cannot remove the last admin';
			if (freshError) {
				api.updateUser.mockRejectedValueOnce(serverRefusal(freshMessage));
				await userAction(target, 'Disable');
				expect(requireElement(target, '.error').textContent).toBe(freshMessage);
			}
			if (action === 'Create') resolveRequest(OTHER_USER);
			else
				rejectRequest(
					action === 'Revoke already ended'
						? new ApiError(404, 'Not Found', '/api/admin/sessions/s1')
						: serverRefusal('Action refused')
				);
			await flush();
			if (freshError) expect(requireElement(target, '.error').textContent).toBe(freshMessage);
			else expect(target.querySelector('.error')).toBeNull();
			if (!returnBeforeReply) {
				await selectTab(target, tab);
				expect(target.querySelector('.error')).toBeNull();
			}
		}
	);

	it.each([
		{
			load: 'users',
			request: 'fetchUsers',
			start: 'users',
			tabs: ['users', 'sessions', 'attempts', 'ratelimits']
		},
		{ load: 'rateLimits', request: 'fetchRateLimits', start: 'ratelimits', tabs: ['ratelimits'] },
		{
			load: 'userLimits',
			request: 'fetchUserRateLimits',
			start: 'ratelimits',
			tabs: ['ratelimits']
		},
		{ load: 'cowriter', request: 'fetchCowriterSettings', start: 'models', tabs: ['models'] },
		{ load: 'cover', request: 'fetchCoverSettings', start: 'models', tabs: ['models'] },
		{ load: 'scoring', request: 'fetchJudgeSettings', start: 'models', tabs: ['models'] }
	] as const)(
		'defect:#920-12 shows $load failures only on their data tabs',
		async ({ load, request, start, tabs }) => {
			const message = `${load} unavailable`;
			api[request].mockRejectedValue(serverRefusal(message));
			const target = await renderPage(true);
			await selectTab(target, start);
			if (load === 'userLimits') {
				userRow(target).click();
				await flush();
			}
			expect(target.textContent).toContain(message);
			for (const destination of [
				'users',
				'sessions',
				'attempts',
				'ratelimits',
				'models',
				'voices',
				'generation',
				'acestep'
			]) {
				await selectTab(target, destination);
				expect(target.textContent?.includes(message), destination).toBe(
					(tabs as readonly string[]).includes(destination)
				);
			}
		}
	);

	it.each(['Disable', 'Promote', 'Reset PW', 'Delete'])(
		'defect:#920-13 explains a missing account on %s and removes its stale actions',
		async (action) => {
			const failure = new ApiError(404, 'Not Found', '/api/admin/users/u2');
			api.updateUser.mockRejectedValueOnce(failure);
			api.hardDeleteUser.mockRejectedValueOnce(failure);
			const target = await renderPage(true);
			await userAction(target, action);
			expect(requireElement(target, '.error').textContent).toBe('That account no longer exists.');
			expect(target.querySelector('.inline-form-row')).toBeNull();
			expect(target.textContent).not.toContain('jane');
		}
	);
});

describe('admin reads and actions that fail', () => {
	it('offline, Users shows no failure of its own and the list is back without a tap once online', async () => {
		reportResourceStreamReachable(false);
		api.fetchUsers.mockRejectedValueOnce(lostNetwork());
		const target = await renderPage(true);

		expect(target.querySelector('.error')).toBeNull();
		expect(target.textContent).not.toContain('Failed to fetch');
		expect(target.textContent).not.toContain('jane');

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.textContent).toContain('jane'));
		expect(target.querySelector('.error')).toBeNull();
	});

	it('names a users read the server refused in its own words', async () => {
		api.fetchUsers.mockRejectedValueOnce(serverRefusal('Database is migrating'));
		const target = await renderPage(true);

		expect(requireElement(target, '.error').textContent).toBe('Database is migrating');
	});

	it('while no strip shows, reads users again on a bounded backoff before naming the failure', async () => {
		vi.useFakeTimers();
		api.fetchUsers.mockRejectedValue(lostNetwork());
		const target = await renderPage(true);
		expect(target.querySelector('.error')).toBeNull();

		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		expect(api.fetchUsers).toHaveBeenCalledTimes(1 + UNREACHABLE_RELOAD_DELAYS_MS.length);
		expect(requireElement(target, '.error').textContent).toBe('Failed to load users');
	});

	it('hides a users failure it named once the offline strip says the connection is lost', async () => {
		vi.useFakeTimers();
		api.fetchUsers.mockRejectedValue(lostNetwork());
		const target = await renderPage(true);
		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		reportResourceStreamReachable(false);
		await tick();

		expect(target.querySelector('.error')).toBeNull();
	});

	it('offline, Voices claims no empty list and shows the voices once back online', async () => {
		reportResourceStreamReachable(false);
		api.fetchAdminVoices.mockRejectedValueOnce(lostNetwork());
		const target = await renderPage(true);
		await selectTab(target, 'voices');
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
		expect(optionLabels(providerSelect(target, 'Scoring'))).toEqual([
			'Claude ✓ ready',
			'Codex ✓ ready',
			'Grok · needs its API key'
		]);
	});

	it('keeps every provider offered while the reachability probe is pending', async () => {
		api.fetchProviderStatus.mockReturnValue(new Promise(() => {}));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Co-Writer'))).toEqual([
			'Claude · Checking…',
			'Codex · Checking…',
			'Grok · Checking…'
		]);
	});

	it('keeps every provider offered after the reachability probe fails', async () => {
		api.fetchProviderStatus.mockRejectedValue(serverRefusal('Provider probe failed'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		expect(optionLabels(providerSelect(target, 'Scoring'))).toEqual([
			'Claude · Provider probe failed',
			'Codex · Provider probe failed',
			'Grok · Provider probe failed'
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
		api.fetchProviderStatus.mockRejectedValue(serverRefusal('Provider probe failed'));
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
		expect(rowNamed(target, 'Cover').textContent).toContain('Claude cannot draw');
	});

	it('saves the scoring row on its saved API route', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Scoring'), 'codex');

		expect(api.updateJudgeSettings).toHaveBeenCalledWith('codex', 'api', 'gpt-5.4');
		expect(statusText(rowNamed(target, 'Scoring'))).toBe('✓Ready · key set');
	});

	describe('with the judge saved on the CLI route', () => {
		beforeEach(() => {
			window.history.replaceState({}, '', '/settings/users');
			api.fetchJudgeSettings.mockResolvedValue(judgeSettings('claude', 'claude-sonnet', 'cli'));
		});

		it('shows the saved route with its state and its own model list', async () => {
			const target = await renderPage(true);
			await selectTab(target, 'models');

			const scoring = rowNamed(target, 'Scoring');
			expect(routeButton(scoring, 'CLI')).toHaveClass('on');
			expect(statusText(scoring)).toBe('✓Ready · CLI login');
			expect(optionLabels(modelSelect(target, 'Scoring'))).toEqual([
				'claude-sonnet',
				'claude-opus-cli'
			]);
			expect(modelSelect(target, 'Scoring').value).toBe('claude-sonnet');
		});

		it('greys the other route with the reason it has no way to score', async () => {
			const target = await renderPage(true);
			await selectTab(target, 'models');

			const scoring = rowNamed(target, 'Scoring');
			const apiRoute = routeButton(scoring, 'API');
			expect(apiRoute).toHaveClass('dead');
			expect(apiRoute.disabled).toBe(true);
			expect(reasons(scoring)).toContain('API · not available for scoring');

			apiRoute.click();
			await flush();

			expect(api.updateJudgeSettings).not.toHaveBeenCalled();
		});

		it('saves a model change on the saved route and says Saved.', async () => {
			const target = await renderPage(true);
			await selectTab(target, 'models');

			await choose(modelSelect(target, 'Scoring'), 'claude-opus-cli');

			expect(api.updateJudgeSettings).toHaveBeenCalledWith('claude', 'cli', 'claude-opus-cli');
			const scoring = rowNamed(target, 'Scoring');
			expect(scoring.textContent).toContain('Saved.');
			expect(statusText(scoring)).toBe('✓Ready · CLI login');
		});

		it('saves a provider change on the saved route and shows that provider on it', async () => {
			const target = await renderPage(true);
			await selectTab(target, 'models');

			await choose(providerSelect(target, 'Scoring'), 'codex');

			expect(api.updateJudgeSettings).toHaveBeenCalledWith('codex', 'cli', 'gpt-5-codex');
			const scoring = rowNamed(target, 'Scoring');
			expect(routeButton(scoring, 'CLI')).toHaveClass('on');
			expect(optionLabels(modelSelect(target, 'Scoring'))).toEqual(['gpt-5-codex']);
		});
	});

	it('greys the CLI a scoring row saved on the API route has no way to use', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const scoring = rowNamed(target, 'Scoring');
		const cli = routeButton(scoring, 'CLI');
		expect(cli).toHaveClass('dead');
		expect(cli.disabled).toBe(true);
		expect(reasons(scoring)).toContain('CLI · not available for scoring');
		expect(routeButton(scoring, 'API')).toHaveClass('on');
		expect(optionLabels(modelSelect(target, 'Scoring'))).toEqual(['claude-opus', 'claude-api']);

		cli.click();
		await flush();

		expect(api.updateJudgeSettings).not.toHaveBeenCalled();
	});

	it('shows a scoring provider that cannot answer as its own grey row', async () => {
		api.fetchJudgeSettings.mockResolvedValue({
			provider: 'grok',
			route: 'api',
			provider_routes_status: {},
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
		const rejection = "Unknown grok model 'grok-4'";
		api.updateCowriterSettings.mockRejectedValue(
			new ApiError(422, rejection, '/api/settings/cowriter', null, rejection)
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Co-Writer'), 'grok');

		const failure = requireElement(sectionByHeading(target, 'Models'), '.tt-sub.bad');
		expect(failure.textContent).toContain(rejection);
		expect(requireElement<HTMLButtonElement>(failure, '.retry').textContent?.trim()).toBe('Retry');

		api.updateCowriterSettings.mockResolvedValue(cowriterSettings({ provider: 'grok', model: '' }));
		requireElement<HTMLButtonElement>(failure, '.retry').click();
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledTimes(2);
		expect(sectionByHeading(target, 'Models').querySelector('.tt-sub.bad')).toBeNull();
	});

	it.each([
		{
			shape: 'a route reason the row can phrase',
			detail: { code: 'cli_login_not_configured', message: 'grok CLI is not signed in.' },
			sentence: 'CLI · not logged in'
		},
		{
			shape: 'a plain sentence from the server',
			detail: "Unknown grok model 'grok-4'",
			sentence: "Unknown grok model 'grok-4'"
		},
		{
			shape: 'a detail the page cannot read',
			detail: [{ loc: ['body', 'model'], msg: 'field required' }],
			sentence: 'The server rejected the change.'
		}
	])('names a rejected save that carries $shape', async ({ detail, sentence }) => {
		api.updateCowriterSettings.mockRejectedValue(
			new ApiError(
				422,
				typeof detail === 'string' ? detail : '',
				'/api/settings/cowriter',
				null,
				detail
			)
		);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		await choose(providerSelect(target, 'Co-Writer'), 'grok');

		const failure = requireElement(sectionByHeading(target, 'Models'), '.tt-sub.bad');
		expect(failure.textContent).toContain(sentence);
		expect(failure.textContent).not.toContain('Something went wrong');
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

		expect(api.updateCowriterSettings).toHaveBeenCalledWith('claude', 'claude-sonnet', 24000, {
			claude: 'cli',
			codex: 'cli',
			grok: 'cli'
		});
		expect(disclosure.textContent).toContain('Saved.');
	});
});
