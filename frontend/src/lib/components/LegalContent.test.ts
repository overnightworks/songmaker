import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';

import LegalContent from './LegalContent.svelte';

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

async function renderLegal(compact: boolean): Promise<HTMLElement> {
	stubMatchMedia(compact);
	if (compact) document.documentElement.dataset.pointer = 'coarse';
	else delete document.documentElement.dataset.pointer;
	const target = document.createElement('div');
	target.style.width = '320px';
	document.body.append(target);
	mounted = mount(LegalContent, { target });
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

describe('LegalContent compact layout', () => {
	it('wraps legal tabs and stays inside 320px', async () => {
		const target = await renderLegal(true);
		const tabs = target.querySelector('.legal-tabs');
		const content = target.querySelector('.legal-content');
		if (!(tabs instanceof HTMLElement) || !(content instanceof HTMLElement)) {
			throw new Error('Expected legal tabs');
		}
		expect(content.classList.contains('compact')).toBe(true);
		expect(getComputedStyle(tabs).flexWrap).toBe('wrap');
		expect(target.textContent).toContain('Impressum');
		expect(target.textContent).toContain('Datenschutz');
		expect(target.textContent).toContain('Nutzungsbedingungen');
		expect(target.scrollWidth).toBeLessThanOrEqual(target.clientWidth);
	});
});
