import { createRawSnippet, mount, tick, unmount, type Snippet } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { reactiveProps } from '../../../tests/reactive-fixtures.svelte';
import { requireElement } from './rail-test-fixtures';
import RailGroup from './RailGroup.svelte';

const STORAGE_KEY = 'songmaker.rail-group-test-open';
const GROUP_ID = 'rail-group-test';

const contentSnippet = createRawSnippet(() => ({
	render: () => `<ul><li>Section one</li><li>Section two</li></ul>`
}));

const iconSnippet = createRawSnippet(() => ({
	render: () => `<svg data-testid="group-icon" viewBox="0 0 24 24"><circle r="3"/></svg>`
}));

let mounted: ReturnType<typeof mount> | undefined;

interface RenderOverrides {
	label?: string;
	icon?: Snippet;
	count?: number;
	expandTrigger?: boolean;
	onTitleClick?: () => void;
}

async function render(overrides: RenderOverrides = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const live = reactiveProps({
		label: 'Playlists',
		groupId: GROUP_ID,
		storageKey: STORAGE_KEY,
		children: contentSnippet,
		...overrides
	});
	mounted = mount(RailGroup, { target, props: live });
	await tick();
	return { target, live };
}

/** Flushes an edge-triggered prop mutation through to the effect that reacts to it. */
async function flush(): Promise<void> {
	await tick();
	await Promise.resolve();
	await tick();
}

beforeEach(() => {
	localStorage.clear();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('RailGroup', () => {
	it('starts collapsed and expands and collapses on toggle click', async () => {
		const { target } = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		const panel = requireElement<HTMLDivElement>(target, `#${GROUP_ID}`);
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(toggle.getAttribute('aria-controls')).toBe(GROUP_ID);
		expect(panel.inert).toBe(true);

		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(panel.inert).toBe(false);
		expect(target.textContent).toContain('Section one');

		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(panel.inert).toBe(true);
	});

	it('renders the label, an optional leading icon, and an optional count', async () => {
		const { target } = await render({ label: 'Library', icon: iconSnippet, count: 42 });
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.textContent).toContain('Library');
		expect(target.querySelector('[data-testid="group-icon"]')).not.toBeNull();
		expect(target.querySelector('.meta')?.textContent).toBe('42');
	});

	it('omits the count badge when none is given', async () => {
		const { target } = await render();
		expect(target.querySelector('.meta')).toBeNull();
	});

	it('remembers an open disclosure across a fresh mount via its storage key', async () => {
		const { target: first } = await render();
		requireElement<HTMLButtonElement>(first, 'button.disclose').click();
		await tick();
		const firstInstance = mounted;
		if (firstInstance) await unmount(firstInstance);
		mounted = undefined;
		document.body.replaceChildren();

		expect(localStorage.getItem(STORAGE_KEY)).toBe('true');

		const { target: second } = await render();
		expect(
			requireElement<HTMLButtonElement>(second, 'button.disclose').getAttribute('aria-expanded')
		).toBe('true');
	});

	it('still renders and toggles when localStorage throws', async () => {
		const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked in private mode');
		});
		const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked in private mode');
		});

		const { target } = await render();
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');

		getItem.mockRestore();
		setItem.mockRestore();
	});

	it('force-opens on a rising expandTrigger edge, not merely while it stays true', async () => {
		const { target, live } = await render({ expandTrigger: false });
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		expect(toggle.getAttribute('aria-expanded')).toBe('false');

		live.expandTrigger = true;
		await flush();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');

		toggle.click();
		await flush();
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('renders onTitleClick as a button sibling of the toggle, which still expands and collapses on its own', async () => {
		const onTitleClick = vi.fn();
		const { target } = await render({ onTitleClick });
		const toggle = requireElement<HTMLButtonElement>(target, 'button.disclose');
		const titleButton = requireElement<HTMLButtonElement>(
			target,
			'.disclose-row > button.group-title'
		);
		expect(toggle.querySelector('.group-title')).toBeNull();

		titleButton.click();
		expect(onTitleClick).toHaveBeenCalledOnce();
		expect(toggle.getAttribute('aria-expanded')).toBe('false');

		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		toggle.click();
		await tick();
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
	});

	it('renders the title as plain text inside the toggle when no onTitleClick is given', async () => {
		const { target } = await render();
		expect(target.querySelector('.disclose-row > button.group-title')).toBeNull();
		expect(requireElement(target, 'button.disclose span.group-title').tagName).toBe('SPAN');
	});
});
