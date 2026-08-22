import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import CollectionHeader from './CollectionHeader.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

type CollectionHeaderProps = ComponentProps<typeof CollectionHeader>;

function baseProps(): CollectionHeaderProps {
	return {
		kind: 'album',
		title: 'Night Drive',
		subtitle: '4 songs · 2 picks',
		coverUrl: null,
		coverAlt: 'Album Night Drive',
		initials: 'ND',
		artFill: null,
		onplay: vi.fn(),
		onrename: vi.fn().mockResolvedValue(undefined),
		isShared: false,
		shareSlug: null,
		onshare: vi.fn().mockResolvedValue({ status: 'ok', share_url: 'https://x/y', share_slug: 'y' }),
		onunshare: vi.fn().mockResolvedValue(undefined),
		ondelete: vi.fn(),
		oncover: vi.fn(),
		onremovecover: vi.fn(),
		onaddtoplaylist: vi.fn()
	};
}

async function render(props: CollectionHeaderProps): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(CollectionHeader, { target, props });
	await tick();
	return target;
}

async function openMenu(target: HTMLElement): Promise<HTMLElement> {
	requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLElement>(document.body, '.menu-panel');
}

beforeEach(() => {
	Object.defineProperty(navigator, 'clipboard', {
		configurable: true,
		value: { writeText: vi.fn().mockResolvedValue(undefined) }
	});
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('CollectionHeader', () => {
	it('shows cover, title, subtitle, and calls onplay from the Play button', async () => {
		const props = baseProps();
		const target = await render(props);
		expect(target.querySelector('.header-title')?.textContent).toContain('Night Drive');
		expect(target.querySelector('.header-subtitle')?.textContent).toBe('4 songs · 2 picks');
		requireElement<HTMLButtonElement>(target, '.play-btn').click();
		expect(props.onplay).toHaveBeenCalledTimes(1);
	});

	it('renders only Play and the … menu, no separate visible share icon', async () => {
		const target = await render(baseProps());
		expect(target.querySelector('.play-btn')).not.toBeNull();
		expect(target.querySelector('.collection-menu')).not.toBeNull();
		expect(target.querySelector('.share-btn')).toBeNull();
	});

	it('names the object first in the menu and lists album entries in order, without Remove cover when there is no cover', async () => {
		const target = await render(baseProps());
		const menu = await openMenu(target);
		expect(menu.querySelector('.menu-heading')?.textContent).toBe('Album · Night Drive');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Cover…', 'Rename', 'Add to playlist', 'Delete album']);
	});

	it('adds Remove cover once a cover exists and wires it to onremovecover', async () => {
		const props = { ...baseProps(), coverUrl: 'https://x/cover.jpg' };
		const target = await render(props);
		const menu = await openMenu(target);
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Cover…', 'Remove cover', 'Rename', 'Add to playlist', 'Delete album']);
		const removeItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Remove cover'
		);
		removeItem?.click();
		expect(props.onremovecover).toHaveBeenCalledTimes(1);
	});

	it('lists playlist entries: Share, Save offline, Rename, Delete — no Cover or Add to playlist', async () => {
		const props = { ...baseProps(), kind: 'playlist' as const, onsaveoffline: vi.fn() };
		const target = await render(props);
		const menu = await openMenu(target);
		expect(menu.querySelector('.menu-row-label')?.textContent).toBe('Share playlist');
		const items = Array.from(menu.querySelectorAll('.menu-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toEqual(['Save offline', 'Rename', 'Delete playlist']);
	});

	it('shares via the embedded ShareButton and copies the link, without duplicating the logic', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openMenu(target);
		requireElement<HTMLButtonElement>(menu, '.share-btn').click();
		await vi.waitFor(() => expect(props.onshare).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://x/y')
		);
	});

	it('calls ondelete for the destructive entry and closes the menu', async () => {
		const props = baseProps();
		const target = await render(props);
		const menu = await openMenu(target);
		requireElement<HTMLButtonElement>(menu, '.menu-item.destructive').click();
		await tick();
		expect(props.ondelete).toHaveBeenCalledTimes(1);
		expect(document.body.querySelector('.menu-panel')).toBeNull();
	});

	it('forwards Rename in the menu to the title EditableTitle interaction', async () => {
		const target = await render(baseProps());
		const menu = await openMenu(target);
		const renameItem = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
			(el) => el.textContent?.trim() === 'Rename'
		);
		renameItem?.click();
		await tick();
		expect(target.querySelector('.editable-title-input')).not.toBeNull();
	});
});
