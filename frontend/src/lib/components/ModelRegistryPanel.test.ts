import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';
import { COMPACT_STACK_CLASS } from '$lib/styles/compact-ui';

const api = vi.hoisted(() => ({
	getRegistry: vi.fn(),
	downloadModel: vi.fn()
}));

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
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
});

describe('ModelRegistryPanel compact layout', () => {
	it('restyles registry rows so Download stays in the card', async () => {
		api.getRegistry.mockResolvedValue({
			models: [
				{ mode: 'turbo', downloaded: false, loaded_on: [], loading_on: [] },
				{ mode: 'sft', downloaded: true, loaded_on: ['acestep-worker-0'], loading_on: [] }
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
			models: [{ mode: 'turbo', downloaded: false, loaded_on: [], loading_on: [] }]
		});
		const target = await renderPanel(false);
		expect(getComputedStyle(requireElement(target, '.registry-table')).display).not.toBe('block');
		expect(target.textContent).toContain('Download');
	});
});
