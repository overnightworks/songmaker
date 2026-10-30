import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '#lib/api/fetch.ts';
import { lostNetwork } from '#lib/test-utils/network.ts';
import { COMPACT_LAYOUT_MEDIA, MODEL_REGISTRY_LOAD_FAILED } from '#lib/constants.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { COMPACT_STACK_CLASS } from '#lib/styles/compact-ui.ts';

const api = vi.hoisted(() => ({
	getRegistry: vi.fn(),
	downloadModel: vi.fn()
}));

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return { ...actual, ...api };
});

import ModelRegistryPanel from './ModelRegistryPanel.svelte';

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

async function flush(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
	await Promise.resolve();
	await tick();
}

async function renderPanel(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ModelRegistryPanel, { target });
	await flush();
	return target;
}

beforeEach(() => {
	api.getRegistry.mockReset();
	api.downloadModel.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	vi.unstubAllGlobals();
	resetConnectivityForTests();
});

describe('ModelRegistryPanel compact layout', () => {
	it('restyles registry rows so Download stays in the card', async () => {
		api.getRegistry.mockResolvedValue({
			models: [
				{ mode: 'turbo', availability: 'not_downloaded', loaded_on: [], loading_on: [] },
				{ mode: 'sft', availability: 'downloaded', loaded_on: ['acestep-worker-0'], loading_on: [] }
			]
		});
		const target = await renderPanel(true);
		const table = requireElement<HTMLTableElement>(
			target,
			`.registry-table.${COMPACT_STACK_CLASS}`
		);
		const row = requireElement<HTMLTableRowElement>(table, 'tbody tr');
		const actions = requireElement<HTMLTableCellElement>(table, 'td.actions-col');

		expect(getComputedStyle(table).display).toBe('block');
		expect(getComputedStyle(requireElement(table, 'thead')).display).toBe('none');
		expect(getComputedStyle(row).display).toBe('flex');
		expect(getComputedStyle(actions).flexWrap).toBe('wrap');
		expect(target.textContent).toContain('turbo');
		expect(target.textContent).toContain('Download');
		expect(target.querySelector('.registry-table tbody tr:nth-child(2)')?.textContent).toContain(
			'sft'
		);
	});

	it('still renders empty and error states', async () => {
		api.getRegistry.mockResolvedValue({ models: [] });
		const empty = await renderPanel(true);
		expect(empty.textContent).toContain('Loading registry…');
		if (mounted) await unmount(mounted);
		mounted = undefined;
		document.body.replaceChildren();

		api.getRegistry.mockRejectedValue(new Error('registry down'));
		const failed = await renderPanel(true);
		expect(failed.textContent).toContain('Cannot reach the registry API');
		expect(failed.querySelector('.registry-table')).toBeNull();
	});

	it('keeps a desktop table when not compact', async () => {
		api.getRegistry.mockResolvedValue({
			models: [{ mode: 'turbo', availability: 'not_downloaded', loaded_on: [], loading_on: [] }]
		});
		const target = await renderPanel(false);
		expect(getComputedStyle(requireElement(target, '.registry-table')).display).not.toBe('block');
		expect(target.textContent).toContain('Download');
	});
});

describe('ModelRegistryPanel with no worker online', () => {
	it('names the unknown state instead of claiming the model is missing', async () => {
		// The GPU worker sat on "Created" for five days without ever
		// starting (issue #252's live incident). With no worker online, the
		// registry cannot know whether a model's files are on disk, so the
		// panel must say that -- not claim "not downloaded" as if the files
		// were confirmed missing, and not offer a Download button that the
		// backend would reject with 503 anyway.
		api.getRegistry.mockResolvedValue({
			models: [{ mode: 'turbo', availability: 'unknown_no_worker', loaded_on: [], loading_on: [] }]
		});
		const target = await renderPanel(false);

		expect(target.textContent).toContain('no worker running');
		expect(target.textContent).not.toContain('not downloaded');
		expect(target.querySelector('button.action-btn')).toBeNull();
	});
});

describe('ModelRegistryPanel failures', () => {
	it.each([
		{
			failure: 'a server reason',
			err: new ApiError(503, 'Registry is rebuilding', '/api/admin/registry'),
			shown: 'Registry is rebuilding'
		},
		{
			failure: 'a lost network with no strip',
			err: lostNetwork(),
			shown: MODEL_REGISTRY_LOAD_FAILED
		}
	])('names $failure without browser text', async ({ err, shown }) => {
		api.getRegistry.mockRejectedValue(err);
		const target = await renderPanel(false);

		expect(requireElement(target, '.panel-error').textContent).toBe(shown);
		expect(target.textContent).not.toContain('Failed to fetch');
	});

	it.each([false, true])(
		'[1160-F27-banner, 1160-F28-return] hides offline and stale failures with existing data=%s',
		async (hasData) => {
			const registry = {
				models: [{ mode: 'turbo', availability: 'downloaded', loaded_on: [], loading_on: [] }]
			};
			api.getRegistry.mockRejectedValue(lostNetwork());
			if (hasData) api.getRegistry.mockResolvedValueOnce(registry);
			const target = await renderPanel(false);
			if (hasData) {
				reportResourceStreamReachable(false);
				reportResourceStreamReachable(true);
				await flush();
			}
			const failureSelector = hasData ? '.banner-error' : '.panel-error';
			expect(target.querySelector(failureSelector)).not.toBeNull();

			reportResourceStreamReachable(false);
			await flush();
			expect(target.querySelector('.banner-error, .panel-error')).toBeNull();
			expect(target.querySelector('.registry-table') !== null).toBe(hasData);

			const reload = Promise.withResolvers<typeof registry>();
			api.getRegistry.mockReturnValueOnce(reload.promise);
			reportResourceStreamReachable(true);
			await flush();
			expect(target.querySelector('.banner-error, .panel-error')).toBeNull();
			expect(target.querySelector('.registry-table') !== null).toBe(hasData);
			if (!hasData) expect(target.textContent).toContain('Loading registry…');

			reload.reject(new ApiError(403, 'Forbidden', '/api/admin/registry'));
			await flush();
			expect(requireElement(target, '.panel-error').textContent).toBe('Admin access required.');
			expect(target.querySelector('.registry-table')).toBeNull();
		}
	);

	it('under the offline strip shows no failure of its own and loads again once back online', async () => {
		reportResourceStreamReachable(false);
		api.getRegistry.mockRejectedValue(lostNetwork());
		const target = await renderPanel(false);
		expect(target.querySelector('.panel-error')).toBeNull();

		api.getRegistry.mockResolvedValue({
			models: [{ mode: 'turbo', availability: 'downloaded', loaded_on: [], loading_on: [] }]
		});
		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(target.querySelector('.registry-table')).not.toBeNull());
	});
});
