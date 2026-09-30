import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { goto } from '$app/navigation';
import { discardDraft, setDraftLyrics } from '$lib/stores/editor';
import { pendingDirtyNavigation } from '$lib/stores/navigation';
import UserRow from './UserRow.svelte';

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', async () => (await import('./rail-test-fixtures')).railPathsMock());

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
	mounted = mount(UserRow, { target, props: { username: 'felix', onlogout } });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	onlogout.mockReset();
	discardDraft();
	pendingDirtyNavigation.set(null);
	vi.mocked(goto).mockClear();
});

function dirtyTheOpenSong(): void {
	setDraftLyrics('unsaved edit');
}

function logoutButton(target: HTMLElement): HTMLButtonElement {
	return requireElement<HTMLButtonElement>(target, 'button.logout');
}

describe('UserRow', () => {
	it('shows the username, a theme toggle, and a Logout action inline, with no popup', async () => {
		const target = await renderRow();
		expect(target.textContent).toContain('felix');
		expect(requireElement<HTMLButtonElement>(target, '[aria-label="Toggle theme"]')).toBeTruthy();
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('links the username to Account settings', async () => {
		const target = await renderRow();
		const link = requireElement<HTMLAnchorElement>(target, 'a.username');
		expect(link.textContent).toBe('felix');
		expect(link.getAttribute('href')).toBe('/settings/account');

		link.click();
		expect(vi.mocked(goto)).toHaveBeenCalledWith('/settings/account', { replaceState: false });
	});

	it('calls onlogout when Logout is clicked', async () => {
		const target = await renderRow();
		logoutButton(target).click();
		expect(onlogout).toHaveBeenCalledTimes(1);
	});

	describe('while the open song has a dirty draft (issue #1143)', () => {
		it('holds the Account link for the unsaved-changes dialog', async () => {
			dirtyTheOpenSong();
			const target = await renderRow();

			requireElement<HTMLAnchorElement>(target, 'a.username').click();

			expect(get(pendingDirtyNavigation)).not.toBeNull();
			expect(vi.mocked(goto)).not.toHaveBeenCalled();
		});

		it('holds Logout for the unsaved-changes dialog', async () => {
			dirtyTheOpenSong();
			const target = await renderRow();

			logoutButton(target).click();

			expect(get(pendingDirtyNavigation)).not.toBeNull();
			expect(onlogout).not.toHaveBeenCalled();
		});
	});
});
