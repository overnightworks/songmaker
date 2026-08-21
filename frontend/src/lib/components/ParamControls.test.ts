import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { VersionGenerationParams } from '$lib/api/types';
import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';

import ParamControls from './ParamControls.svelte';

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

async function renderControls(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	target.style.width = '320px';
	document.body.append(target);
	mounted = mount(ParamControls, {
		target,
		props: {
			values: {},
			placeholders: {} as Required<VersionGenerationParams>,
			onchange: vi.fn()
		}
	});
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-compact-ui]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
	vi.unstubAllGlobals();
});

describe('ParamControls compact layout', () => {
	it('stacks generation fields to one column at 320px', async () => {
		const target = await renderControls(true);
		const grid = target.querySelector('.settings-grid');
		if (!(grid instanceof HTMLElement)) throw new Error('Expected settings grid');
		expect(target.querySelector('.param-controls')?.classList.contains('compact')).toBe(true);
		expect(getComputedStyle(grid).gridTemplateColumns).toBe('minmax(0, 1fr)');
		expect(target.scrollWidth).toBeLessThanOrEqual(target.clientWidth);
	});

	it('does not apply the compact one-column override on a wide fine pointer', async () => {
		const target = await renderControls(false);
		const grid = target.querySelector('.settings-grid');
		if (!(grid instanceof HTMLElement)) throw new Error('Expected settings grid');
		expect(target.querySelector('.param-controls')?.classList.contains('compact')).toBe(false);
		expect(getComputedStyle(grid).gridTemplateColumns).not.toBe('minmax(0, 1fr)');
	});
});
