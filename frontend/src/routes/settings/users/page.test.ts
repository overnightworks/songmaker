import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { resolve } from '$app/paths';
import { goto } from '$app/navigation';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CowriterSettings } from '#lib/api/types.ts';
import { lostNetwork, serverRefusal } from '#lib/test-utils/network.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants/connectivity.ts';
import { COMPACT_LAYOUT_MEDIA } from '#lib/constants/media.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { COMPACT_SELECT_CLASS } from '#lib/styles/compact-ui.ts';
import { currentUser } from '#lib/stores/auth.ts';

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
	fetchBuiltinDefaults: vi.fn(),
	listWorkers: vi.fn(),
	getRegistry: vi.fn()
}));

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return { ...actual, ...api };
});

import AdminPage from './+page.svelte';
import { words } from '#lib/words/en.ts';
import { ADMIN_VOICE_STATUS_TEXT_KEYS } from '#lib/constants/admin.ts';

const VIEWPORT_PX = 320;
const VOICES = [
	{ id: 'voice-1', name: 'Warm Tenor', owner_username: 'jane', status: 'training' },
	{ id: 'voice-2', name: 'Dry Spoken Word', owner_username: 'jane', status: 'ready' }
];
function cowriterSettings(overrides: Partial<CowriterSettings> = {}): CowriterSettings {
	return {
		tail_token_budget: 8000,
		...overrides
	};
}

const TAB_LABELS = [
	words['adminPage.tabVoices'],
	words['adminPage.tabRateLimits'],
	words['adminPage.tabGeneration'],
	words['adminPage.tabModels'],
	words['adminPage.tabAcestep'],
	words['adminPage.tabCleanup']
];

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
		`select[aria-label="${words['adminPage.sections']}"]`
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

beforeEach(() => {
	window.history.replaceState({}, '', '/settings/users');
	currentUser.set({ id: 'u1', username: 'felix', role: 'admin', account_console_url: '' });
	api.fetchAdminVoices.mockResolvedValue(VOICES);
	api.fetchRateLimits.mockResolvedValue({ settings: [] });
	api.fetchGenerationDefaults.mockResolvedValue({});
	api.fetchAllModels.mockResolvedValue([]);
	api.fetchBuiltinDefaults.mockResolvedValue({});
	api.fetchCowriterSettings.mockResolvedValue(cowriterSettings());
	api.updateCowriterSettings.mockImplementation(async (tailTokenBudget: number) =>
		cowriterSettings({ tail_token_budget: tailTokenBudget })
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
			`select[aria-label="${words['adminPage.sections']}"]`
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
			`select[aria-label="${words['adminPage.sections']}"]`
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
		const voices = sectionByHeading(target, words['adminVoices.heading']);

		expect(api.fetchAdminVoices).toHaveBeenCalledOnce();
		expect(voices.textContent).toContain('Warm Tenor');
		expect(voices.textContent).toContain('jane');
		expect(voices.textContent).toContain(words[ADMIN_VOICE_STATUS_TEXT_KEYS.training]);
		expect(voices.textContent).toContain('Dry Spoken Word');
		expect(voices.textContent).toContain(words[ADMIN_VOICE_STATUS_TEXT_KEYS.ready]);
		expect(voices.querySelectorAll('button')).toHaveLength(0);
		expect(voices.textContent).not.toContain('sft');
		expect(voices.textContent).not.toContain('turbo');
	});

	it('names a voices loading failure instead of showing an empty state', async () => {
		api.fetchAdminVoices.mockRejectedValueOnce(serverRefusal('Voice index is rebuilding'));
		const target = await renderPage(true);
		const voices = sectionByHeading(target, words['adminVoices.heading']);

		expect(voices.textContent).toContain('Voice index is rebuilding');
		expect(voices.textContent).not.toContain(words['adminVoices.empty']);
	});

	it('keeps desktop tab buttons and no tab selector', async () => {
		const target = await renderPage(false);
		const buttons = Array.from(target.querySelectorAll('.tabs button')).map((button) =>
			button.textContent?.trim()
		);
		expect(target.querySelector(`select[aria-label="${words['adminPage.sections']}"]`)).toBeNull();
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
		{ action: words['adminPage.saveDefaults'], tab: 'ratelimits', request: 'updateRateLimits' },
		{
			action: words['adminPage.saveDefaults'],
			tab: 'generation',
			request: 'updateGenerationDefaults'
		},
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
		{ load: 'cowriter', request: 'fetchCowriterSettings', start: 'models', tabs: ['models'] }
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
		const voices = sectionByHeading(target, words['adminVoices.heading']);

		expect(voices.textContent).not.toContain(words['adminVoices.empty']);
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

		expect(requireElement(target, '.budget-error').textContent).toBe(
			words['modelsTable.saveFailed']
		);
		expect(target.textContent).not.toContain('Failed to fetch');
	});
});

describe('admin models tab', () => {
	it('answers who does what in one row per task', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const models = sectionByHeading(target, words['modelsTable.heading']);
		expect(taskNames(models)).toEqual([
			words['modelsTable.taskCowriter'],
			words['modelsTable.taskCover']
		]);
		expect(columnNames(models)).toEqual([
			words['modelsTable.columnTask'],
			words['modelsTable.columnProvider'],
			words['modelsTable.columnRoute'],
			words['modelsTable.columnModel'],
			words['modelsTable.columnStatus']
		]);
		expect(headings(target)).not.toContain('Providers');
		expect(models.querySelector('.route-card')).toBeNull();
		expect(saveButtons(models)).toEqual([]);
	});

	it.each([words['modelsTable.taskCowriter'], words['modelsTable.taskCover']])(
		'C16 shows the %s row as set by the agent file through the gateway, without a choice',
		async (task) => {
			const target = await renderPage(true);
			await selectTab(target, 'models');
			const row = rowNamed(target, task);
			expect(row.textContent).toContain(words['modelsTable.setByAgentFile']);
			expect(row.textContent).toContain(words['modelsTable.routeGateway']);
			expect(row.querySelector('select, button, [role="group"]')).toBeNull();
		}
	);

	it('asks the server for no provider status and no cover settings', async () => {
		const requests = vi.fn(() => new Promise<Response>(() => {}));
		vi.stubGlobal('fetch', requests);
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const urls = requests.mock.calls.map((call) => String((call as unknown[])[0]));
		expect(urls.filter((url) => /settings\/(providers|cover)/.test(url))).toEqual([]);
	});

	it('offers no defaults editor and sends nothing while the generation defaults failed to load', async () => {
		api.fetchGenerationDefaults.mockRejectedValue(serverRefusal('Defaults unavailable'));
		const target = await renderPage(true);
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, words['generationDefaults.heading']);
		expect(requireElement(section, '.error').textContent).toContain('Defaults unavailable');
		expect(section.querySelector('.save-btn')).toBeNull();
		expect(section.querySelector('.gen-model-tab')).toBeNull();
		expect(api.updateGenerationDefaults).not.toHaveBeenCalled();
	});

	it('refills the form from the stored defaults once a failed read recovers, so Save never wipes them', async () => {
		const stored = { turbo: { inference_steps: 20, guidance_scale: 5 } };
		api.fetchBuiltinDefaults.mockResolvedValue({ turbo: { inference_steps: 8 } });
		api.fetchGenerationDefaults
			.mockRejectedValueOnce(serverRefusal('Defaults unavailable'))
			.mockResolvedValue(stored);
		api.updateGenerationDefaults.mockImplementation(async (body: unknown) => body);
		const target = await renderPage(true);
		await selectTab(target, 'generation');
		await selectTab(target, 'users');
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, words['generationDefaults.heading']);
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
			.mockRejectedValueOnce(serverRefusal('Defaults unavailable'))
			.mockResolvedValue(stored);
		api.updateGenerationDefaults.mockImplementation(async (body: unknown) => body);
		const target = await renderPage(true);
		await selectTab(target, 'generation');

		const failed = sectionByHeading(target, words['generationDefaults.heading']);
		expect(requireElement(failed, '.error').textContent).toContain('Defaults unavailable');
		expect(failed.querySelector('.save-btn')).toBeNull();

		await selectTab(target, 'users');
		await selectTab(target, 'generation');

		const section = sectionByHeading(target, words['generationDefaults.heading']);
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
			modeTab(sectionByHeading(target, words['generationDefaults.heading']), 'SFT').click();
			await flush();
			await selectTab(target, 'users');
			await selectTab(target, 'generation');
			await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS[0]);

			const section = sectionByHeading(target, words['generationDefaults.heading']);
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
			const first = sectionByHeading(target, words['generationDefaults.heading']);
			modeTab(first, 'SFT').click();
			await flush();
			await typeSteps(first, '77');
			await selectTab(target, 'acestep');
			await selectTab(target, 'generation');

			const section = sectionByHeading(target, words['generationDefaults.heading']);
			expect(requireElement<HTMLInputElement>(section, 'input').value).toBe('77');
			requireElement<HTMLButtonElement>(section, '.save-btn').click();
			await flush();

			expect(api.updateGenerationDefaults).toHaveBeenLastCalledWith({
				turbo: stored.turbo,
				sft: { inference_steps: 77 }
			});
		});
	});

	it('names a rejected history-tail save next to the field with a retry', async () => {
		api.updateCowriterSettings.mockRejectedValue(serverRefusal('Tail budget out of range'));
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const disclosure = requireElement<HTMLDetailsElement>(
			sectionByHeading(target, words['modelsTable.heading']),
			'details'
		);
		const budget = requireElement<HTMLInputElement>(disclosure, '#cowriter-budget');
		budget.value = '999999';
		budget.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();

		expect(disclosure.textContent).toContain('Tail budget out of range');
		expect(disclosure.textContent).not.toContain(words['modelsTable.saved']);

		api.updateCowriterSettings.mockResolvedValue(cowriterSettings({ tail_token_budget: 999999 }));
		requireElement<HTMLButtonElement>(disclosure, '.retry').click();
		await flush();

		expect(disclosure.textContent).toContain(words['modelsTable.saved']);
		expect(disclosure.textContent).not.toContain('Tail budget out of range');
	});

	it('keeps the history tail under a collapsed Advanced disclosure and saves it there', async () => {
		const target = await renderPage(true);
		await selectTab(target, 'models');

		const disclosure = requireElement<HTMLDetailsElement>(
			sectionByHeading(target, words['modelsTable.heading']),
			'details'
		);
		expect(disclosure.open).toBe(false);
		expect(disclosure.textContent).toContain(words['modelsTable.historyTail']);

		const budget = requireElement<HTMLInputElement>(disclosure, '#cowriter-budget');
		budget.value = '24000';
		budget.dispatchEvent(new Event('change', { bubbles: true }));
		await flush();

		expect(api.updateCowriterSettings).toHaveBeenCalledWith(24000);
		expect(disclosure.textContent).toContain(words['modelsTable.saved']);
	});
});
