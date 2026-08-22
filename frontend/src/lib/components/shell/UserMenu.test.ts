import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import UserMenu from './UserMenu.svelte';

let mounted: ReturnType<typeof mount> | undefined;
const onlogout = vi.fn();

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

async function renderRow(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(UserMenu, { target, props: { username: 'felix', onlogout } });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	onlogout.mockReset();
});

describe('UserMenu', () => {
	it('shows the username, a theme toggle, and a Logout action inline, with no popup', async () => {
		const target = await renderRow();
		expect(target.textContent).toContain('felix');
		expect(requireElement<HTMLButtonElement>(target, '[aria-label="Toggle theme"]')).toBeTruthy();
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('calls onlogout when Logout is clicked', async () => {
		const target = await renderRow();
		const logout = Array.from(target.querySelectorAll('button')).find(
			(button) => button.textContent === 'Logout'
		);
		logout?.click();
		expect(onlogout).toHaveBeenCalledTimes(1);
	});
});
