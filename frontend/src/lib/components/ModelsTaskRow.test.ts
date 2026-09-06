import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	MODELS_ADVANCED_LABEL,
	MODELS_NO_MODELS_LABEL,
	MODELS_RETRY_LABEL,
	MODELS_SAVED_LABEL,
	MODELS_STATUS_CHECKING_LABEL,
	MODELS_STATUS_NEEDS_API_KEY_LABEL,
	MODELS_STATUS_NOT_SAVED_LABEL,
	MODELS_STATUS_READY_CLI_LABEL,
	MODELS_STATUS_READY_KEY_LABEL
} from '$lib/constants';
import ModelsTaskRow, { MODELS_ROUTE_NOT_AVAILABLE_CODE } from './ModelsTaskRow.svelte';
import type {
	ModelsRouteKey,
	ModelsSaveOutcome,
	ModelsTaskProvider,
	ModelsTaskRoute,
	ModelsTaskSelection
} from './ModelsTaskRow.svelte';

const TASK = 'Co-Writer';

const READY_CLI: ModelsTaskRoute = { ready: true, reason: null, models: ['opus', 'sonnet'] };
const NO_KEY: ModelsTaskRoute = {
	ready: false,
	reason: { code: 'api_key_not_set', message: 'API key is not set.' },
	models: []
};
const NO_LOGIN: ModelsTaskRoute = {
	ready: false,
	reason: { code: 'cli_login_not_configured', message: 'CLI is not signed in.' },
	models: []
};
const NO_IMAGE_TOOL: ModelsTaskRoute = {
	ready: false,
	reason: { code: 'no_image_tool', message: 'no image tool' },
	models: []
};
const UNPROBED: ModelsTaskRoute = { ready: false, reason: null, models: [] };
const NOT_AVAILABLE_FOR_TASK: ModelsTaskRoute = {
	ready: false,
	reason: { code: MODELS_ROUTE_NOT_AVAILABLE_CODE, message: 'not available for co-writer' },
	models: []
};
const CATALOGUE_DOWN: ModelsTaskRoute = {
	ready: false,
	reason: { code: 'catalogue_http_error', message: 'Model catalogue request failed.' },
	models: []
};

function provider(
	name: string,
	label: string,
	cli: ModelsTaskRoute,
	api: ModelsTaskRoute
): ModelsTaskProvider {
	return { provider: name, label, routes: { cli, api } };
}

const CLAUDE_ON_CLI = provider('claude', 'Claude', READY_CLI, { ...NO_KEY });
const GROK_WITHOUT_KEY = provider('grok', 'Grok', NO_LOGIN, NO_KEY);
const CODEX_WITHOUT_IMAGE_TOOL = provider('codex', 'Codex', NO_IMAGE_TOOL, NO_IMAGE_TOOL);

let mounted: ReturnType<typeof mount> | undefined;

interface RenderOptions {
	providers?: ModelsTaskProvider[];
	selection?: ModelsTaskSelection;
	save?: (selection: ModelsTaskSelection) => Promise<ModelsSaveOutcome>;
}

async function flush(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
	await Promise.resolve();
	await tick();
}

async function renderRow(options: RenderOptions = {}): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ModelsTaskRow, {
		target,
		props: {
			task: TASK,
			providers: options.providers ?? [CLAUDE_ON_CLI, GROK_WITHOUT_KEY, CODEX_WITHOUT_IMAGE_TOOL],
			selection: options.selection ?? { provider: 'claude', route: 'cli', model: 'opus' },
			save: options.save ?? vi.fn().mockResolvedValue({ ok: true })
		}
	});
	await flush();
	return target;
}

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

function selectNamed(root: ParentNode, column: string): HTMLSelectElement {
	return requireElement<HTMLSelectElement>(root, `select[aria-label="${TASK} ${column}"]`);
}

function optionLabels(select: HTMLSelectElement): string[] {
	return Array.from(select.options).map((option) => option.textContent?.trim() ?? '');
}

function routeButton(root: ParentNode, route: ModelsRouteKey): HTMLButtonElement {
	const label = route === 'cli' ? 'CLI' : 'API';
	const button = Array.from(root.querySelectorAll<HTMLButtonElement>('.rsw button')).find(
		(candidate) => candidate.textContent?.trim() === label
	);
	if (!button) throw new Error(`Expected a ${label} route button`);
	return button;
}

function statusText(root: ParentNode): string {
	return requireElement(root, '.st').textContent?.trim() ?? '';
}

const STATUS_SHAPES = ['ok', 'warn', 'off', 'bad'];

function statusShape(root: ParentNode): string {
	const status = requireElement(root, '.st');
	return Array.from(status.classList)
		.filter((name) => STATUS_SHAPES.includes(name))
		.join(' ');
}

function reasons(root: ParentNode): string[] {
	return Array.from(root.querySelectorAll('.why')).map((el) => el.textContent?.trim() ?? '');
}

async function choose(select: HTMLSelectElement, value: string): Promise<void> {
	select.value = value;
	select.dispatchEvent(new Event('change', { bubbles: true }));
	await flush();
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.clearAllMocks();
});

describe('models task row', () => {
	it('offers every provider with its own state and keeps each one selectable', async () => {
		const target = await renderRow();

		const providers = selectNamed(target, 'provider');
		expect(optionLabels(providers)).toEqual([
			'Claude ✓ ready',
			'Grok · needs its API key',
			'Codex · no image tool'
		]);
		expect(Array.from(providers.options).some((option) => option.disabled)).toBe(false);
	});

	it('keeps both route pills alive when both routes are set up', async () => {
		const bothReady = provider('claude', 'Claude', READY_CLI, {
			ready: true,
			reason: null,
			models: ['claude-api']
		});
		const target = await renderRow({ providers: [bothReady] });

		expect(routeButton(target, 'cli').classList.contains('dead')).toBe(false);
		expect(routeButton(target, 'api').classList.contains('dead')).toBe(false);
		expect(reasons(target)).toEqual(['API · key set']);
	});

	it('greys a route that is not set up and names its reason', async () => {
		const target = await renderRow();

		expect(routeButton(target, 'api').classList.contains('dead')).toBe(true);
		expect(reasons(target)).toEqual(['API · key not set']);
	});

	it('greys both routes and marks the stored one when nothing is set up', async () => {
		const target = await renderRow({
			providers: [GROK_WITHOUT_KEY],
			selection: { provider: 'grok', route: 'api', model: '' }
		});

		expect(routeButton(target, 'api').classList.contains('picked-dead')).toBe(true);
		expect(routeButton(target, 'cli').classList.contains('dead')).toBe(true);
		expect(reasons(target)).toEqual(['API · key not set', 'CLI · not logged in']);
	});

	it('selects the only route that is set up when the provider changes', async () => {
		const save = vi.fn().mockResolvedValue({ ok: true });
		const grokOnApi = provider('grok', 'Grok', NO_LOGIN, {
			ready: true,
			reason: null,
			models: ['grok-4-1-fast']
		});
		const target = await renderRow({ providers: [CLAUDE_ON_CLI, grokOnApi], save });

		await choose(selectNamed(target, 'provider'), 'grok');

		expect(save).toHaveBeenCalledWith({
			provider: 'grok',
			route: 'api',
			model: 'grok-4-1-fast'
		});
	});

	it('shows "No models" instead of inventing one', async () => {
		const target = await renderRow({
			providers: [GROK_WITHOUT_KEY],
			selection: { provider: 'grok', route: 'api', model: '' }
		});

		const models = selectNamed(target, 'model');
		expect(optionLabels(models)).toEqual([MODELS_NO_MODELS_LABEL]);
		expect(models.disabled).toBe(true);
	});

	it.each([
		['a missing API key', 'api' as ModelsRouteKey, GROK_WITHOUT_KEY, 'List needs the key'],
		['a CLI nobody signed in to', 'cli' as ModelsRouteKey, GROK_WITHOUT_KEY, 'List needs the CLI'],
		[
			'a provider that cannot draw',
			'cli' as ModelsRouteKey,
			CODEX_WITHOUT_IMAGE_TOOL,
			'Codex cannot draw'
		],
		[
			'a catalogue that failed',
			'cli' as ModelsRouteKey,
			provider('claude', 'Claude', CATALOGUE_DOWN, CATALOGUE_DOWN),
			'Model catalogue request failed.'
		]
	])('names %s as the reason the model list is empty', async (_name, route, entry, hint) => {
		const target = await renderRow({
			providers: [entry],
			selection: { provider: entry.provider, route, model: '' }
		});

		expect(requireElement(target, '.hint').textContent?.trim()).toBe(hint);
	});

	it('keeps a catalogue failure on a route that is otherwise set up', async () => {
		const brokenCatalogue = provider(
			'claude',
			'Claude',
			{ ready: true, reason: null, models: [], modelsReason: 'Model catalogue request failed.' },
			NO_KEY
		);
		const target = await renderRow({
			providers: [brokenCatalogue],
			selection: { provider: 'claude', route: 'cli', model: '' }
		});

		expect(requireElement(target, '.hint').textContent?.trim()).toBe(
			'Model catalogue request failed.'
		);
	});

	it('keeps a stored model that the live catalogue no longer lists', async () => {
		const target = await renderRow({
			selection: { provider: 'claude', route: 'cli', model: 'retired-opus' }
		});

		expect(optionLabels(selectNamed(target, 'model'))).toEqual(['opus', 'sonnet', 'retired-opus']);
	});

	it.each([
		[
			'a ready CLI route',
			{ provider: 'claude', route: 'cli' as ModelsRouteKey, model: 'opus' },
			[CLAUDE_ON_CLI],
			'ok',
			`✓${MODELS_STATUS_READY_CLI_LABEL}`
		],
		[
			'a ready API route',
			{ provider: 'claude', route: 'api' as ModelsRouteKey, model: 'claude-api' },
			[
				provider('claude', 'Claude', NO_LOGIN, {
					ready: true,
					reason: null,
					models: ['claude-api']
				})
			],
			'ok',
			`✓${MODELS_STATUS_READY_KEY_LABEL}`
		],
		[
			'a missing API key',
			{ provider: 'grok', route: 'api' as ModelsRouteKey, model: '' },
			[GROK_WITHOUT_KEY],
			'warn',
			`!${MODELS_STATUS_NEEDS_API_KEY_LABEL}`
		],
		[
			'a provider without an image tool',
			{ provider: 'codex', route: 'cli' as ModelsRouteKey, model: '' },
			[CODEX_WITHOUT_IMAGE_TOOL],
			'off',
			'○Codex · no image tool'
		],
		[
			'a CLI that is not signed in',
			{ provider: 'grok', route: 'cli' as ModelsRouteKey, model: '' },
			[GROK_WITHOUT_KEY],
			'off',
			'○Grok CLI not logged in'
		],
		[
			'a route whose catalogue is down',
			{ provider: 'claude', route: 'cli' as ModelsRouteKey, model: '' },
			[provider('claude', 'Claude', CATALOGUE_DOWN, CATALOGUE_DOWN)],
			'off',
			'○Claude · Model catalogue request failed.'
		],
		[
			'a readiness that has not been probed yet',
			{ provider: 'claude', route: 'cli' as ModelsRouteKey, model: '' },
			[provider('claude', 'Claude', UNPROBED, UNPROBED)],
			'off',
			`○${MODELS_STATUS_CHECKING_LABEL}`
		]
	])('shows %s as its own status shape', async (_name, selection, providers, shape, text) => {
		const target = await renderRow({ providers, selection });

		expect(statusShape(target)).toBe(shape);
		expect(statusText(target)).toBe(text);
	});

	it('saves the row on a model change and confirms it in the row', async () => {
		const save = vi.fn().mockResolvedValue({ ok: true });
		const target = await renderRow({ save });

		await choose(selectNamed(target, 'model'), 'sonnet');

		expect(save).toHaveBeenCalledWith({ provider: 'claude', route: 'cli', model: 'sonnet' });
		expect(target.textContent).toContain(MODELS_SAVED_LABEL);
	});

	it('saves a route change without hiding the switch', async () => {
		const save = vi.fn().mockResolvedValue({ ok: true });
		const bothReady = provider('claude', 'Claude', READY_CLI, {
			ready: true,
			reason: null,
			models: ['claude-api']
		});
		const target = await renderRow({ providers: [bothReady], save });

		routeButton(target, 'api').click();
		await flush();

		expect(save).toHaveBeenCalledWith({ provider: 'claude', route: 'api', model: 'claude-api' });
		expect(routeButton(target, 'api')).toBeTruthy();
	});

	it('keeps a chosen combination nobody can run instead of falling back', async () => {
		let accept: (outcome: ModelsSaveOutcome) => void = () => {};
		const save = vi.fn(
			() =>
				new Promise<ModelsSaveOutcome>((resolve) => {
					accept = resolve;
				})
		);
		const target = await renderRow({ save });

		await choose(selectNamed(target, 'provider'), 'codex');

		expect(save).toHaveBeenCalledWith({ provider: 'codex', route: 'cli', model: '' });
		expect(statusText(target)).toBe('○Codex · no image tool');

		accept({ ok: true });
		await flush();
		expect(target.textContent).toContain(MODELS_SAVED_LABEL);
	});

	it('names a rejected save in a red sub-row and retries it', async () => {
		const save = vi
			.fn()
			.mockResolvedValueOnce({ ok: false, reason: 'The server rejected sonnet: unknown model.' })
			.mockResolvedValueOnce({ ok: true });
		const target = await renderRow({ save });

		await choose(selectNamed(target, 'model'), 'sonnet');

		expect(statusText(target)).toBe(`✕${MODELS_STATUS_NOT_SAVED_LABEL}`);
		const failure = requireElement(target, '.tt-sub.bad');
		expect(failure.textContent).toContain('The server rejected sonnet: unknown model.');

		const retry = requireElement<HTMLButtonElement>(failure, '.retry');
		expect(retry.textContent?.trim()).toBe(MODELS_RETRY_LABEL);
		retry.click();
		await flush();

		expect(save).toHaveBeenCalledTimes(2);
		expect(save).toHaveBeenLastCalledWith({ provider: 'claude', route: 'cli', model: 'sonnet' });
		expect(target.querySelector('.tt-sub.bad')).toBeNull();
		expect(target.textContent).toContain(MODELS_SAVED_LABEL);
	});

	it('greys a route the task cannot use and ignores clicks on it', async () => {
		const save = vi.fn().mockResolvedValue({ ok: true });
		const onlyApi = provider('claude', 'Claude', NOT_AVAILABLE_FOR_TASK, {
			ready: true,
			reason: null,
			models: ['claude-api']
		});
		const target = await renderRow({
			providers: [onlyApi],
			selection: { provider: 'claude', route: 'api', model: 'claude-api' },
			save
		});

		const cli = routeButton(target, 'cli');
		expect(cli.classList.contains('dead')).toBe(true);
		expect(cli.disabled).toBe(true);
		expect(reasons(target)).toEqual(['CLI · not available for co-writer']);
		expect(routeButton(target, 'api').classList.contains('on')).toBe(true);
		expect(routeButton(target, 'api').disabled).toBe(false);

		cli.click();
		await flush();

		expect(save).not.toHaveBeenCalled();
	});

	it('never moves to a route the task cannot use when the provider changes', async () => {
		const save = vi.fn().mockResolvedValue({ ok: true });
		const claudeOnApi = provider('claude', 'Claude', NOT_AVAILABLE_FOR_TASK, {
			ready: true,
			reason: null,
			models: ['claude-api']
		});
		const grokWithoutKey = provider('grok', 'Grok', NOT_AVAILABLE_FOR_TASK, NO_KEY);
		const target = await renderRow({
			providers: [claudeOnApi, grokWithoutKey],
			selection: { provider: 'claude', route: 'api', model: 'claude-api' },
			save
		});

		await choose(selectNamed(target, 'provider'), 'grok');

		expect(save).toHaveBeenCalledWith({ provider: 'grok', route: 'api', model: '' });
	});

	it('reads its reasons out with the control they belong to', async () => {
		const target = await renderRow({
			providers: [GROK_WITHOUT_KEY],
			selection: { provider: 'grok', route: 'api', model: '' }
		});

		const describedRoutes = requireElement(target, '.rsw').getAttribute('aria-describedby');
		expect(describedRoutes).not.toBeNull();
		expect(requireElement(target, `#${describedRoutes}`).textContent).toContain(
			'API · key not set'
		);

		const describedModels = selectNamed(target, 'model').getAttribute('aria-describedby');
		expect(describedModels).not.toBeNull();
		expect(requireElement(target, `#${describedModels}`).textContent).toContain(
			'List needs the key'
		);
	});

	it('announces a save without stealing focus', async () => {
		const target = await renderRow();
		const confirmation = requireElement(target, '.saved');
		expect(confirmation.getAttribute('aria-live')).toBe('polite');
		expect(confirmation.textContent?.trim()).toBe('');

		await choose(selectNamed(target, 'model'), 'sonnet');

		expect(confirmation.textContent).toContain(MODELS_SAVED_LABEL);
	});

	it('keeps task extras behind a collapsed Advanced disclosure', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(ModelsTaskRow, {
			target,
			props: {
				task: TASK,
				providers: [CLAUDE_ON_CLI],
				selection: { provider: 'claude', route: 'cli', model: 'opus' },
				save: vi.fn().mockResolvedValue({ ok: true }),
				advanced: createRawSnippet(() => ({
					render: () => '<span>History tail (tokens)</span>'
				}))
			}
		});
		await flush();

		const details = requireElement<HTMLDetailsElement>(target, 'details');
		expect(details.open).toBe(false);
		expect(requireElement(details, 'summary').textContent?.trim()).toBe(MODELS_ADVANCED_LABEL);
		expect(target.textContent).toContain('History tail (tokens)');
	});
});
