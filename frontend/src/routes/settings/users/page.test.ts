import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LoginAttemptItem, PaginatedResponse, SessionItem, UserItem } from '$lib/api/types';
import { ADMIN_TABS_LABEL, COMPACT_LAYOUT_MEDIA } from '$lib/constants';
import { COMPACT_SELECT_CLASS, COMPACT_STACK_CLASS } from '$lib/styles/compact-ui';
import { currentUser } from '$lib/stores/auth';

const api = vi.hoisted(() => ({
	fetchUsers: vi.fn(),
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
	fetchClaudeModels: vi.fn(),
	updateClaudeModels: vi.fn(),
	fetchCowriterSettings: vi.fn(),
	updateCowriterSettings: vi.fn(),
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
const TAB_LABELS = [
	'Users',
	'Sessions',
	'Login Attempts',
	'Rate Limits',
	'Generation',
	'Claude',
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

beforeEach(() => {
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin' });
	api.fetchUsers.mockResolvedValue([ADMIN_USER, OTHER_USER]);
	api.fetchSessions.mockResolvedValue(pageOf([SESSION]));
	api.fetchLoginAttempts.mockResolvedValue(pageOf([ATTEMPT]));
	api.fetchRateLimits.mockResolvedValue({ settings: [] });
	api.fetchGenerationDefaults.mockResolvedValue({});
	api.fetchAllModels.mockResolvedValue([]);
	api.fetchBuiltinDefaults.mockResolvedValue({});
	api.fetchClaudeModels.mockResolvedValue({
		chat_model: 'claude-sonnet',
		scoring_model: 'claude-sonnet',
		allowed_models: ['claude-sonnet']
	});
	api.fetchCowriterSettings.mockResolvedValue({
		provider: 'claude',
		model: 'claude-sonnet',
		tail_token_budget: 8000,
		allowed_providers: ['claude'],
		allowed_models: ['claude-sonnet'],
		models_by_provider: { claude: ['claude-sonnet'] },
		models_error: null
	});
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
