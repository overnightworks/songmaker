import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ShareResult } from '$lib/api/types';
import { COLLECTION_MENU_RENAME_LABEL } from '$lib/constants';
import { menuRow, menuRowLabels } from '$lib/test-utils/collection-menu';
import { describeBackClosesOverlay, plannedHistoryIndex } from '$lib/test-utils/library-history';
import CollectionMenu from './CollectionMenu.svelte';
import { openCollectionMenu } from './shell/rail-test-fixtures';

const mounted: Array<ReturnType<typeof mount>> = [];
const SHARE_WARNING_LABEL = 'Missing from the share page';

beforeEach(() => {
	Object.defineProperty(navigator, 'clipboard', {
		value: { writeText: vi.fn().mockResolvedValue(undefined) },
		configurable: true
	});
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function shareResult(overrides: Partial<ShareResult> = {}): ShareResult {
	return {
		status: 'ok',
		share_url: 'https://example.test/share/abc',
		share_slug: 'abc',
		songs_without_playable_take: [],
		...overrides
	};
}

function defaultProps() {
	return {
		kind: 'album' as 'album' | 'playlist',
		title: 'Test Album',
		isShared: false,
		shareSlug: null,
		onshare: vi.fn<() => Promise<ShareResult>>().mockResolvedValue(shareResult()),
		onunshare: vi.fn(),
		onrename: vi.fn(),
		oneditdetails: undefined as (() => void) | undefined,
		ondelete: vi.fn()
	};
}

async function render(overrides: Partial<ComponentProps<typeof CollectionMenu>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(CollectionMenu, { target, props }));
	await tick();
	return { target, props };
}

async function openMenuAndShare(target: HTMLElement, shareLabel = 'Share') {
	await openCollectionMenu(target);
	menuRow(target, shareLabel).click();
	await tick();
	await tick();
}

function shareWarningDialog(target: HTMLElement): Element | null {
	return target.querySelector(`[role="dialog"][aria-label="${SHARE_WARNING_LABEL}"]`);
}

describe('CollectionMenu share warning', () => {
	it('opens a warning dialog listing songs without a playable take after sharing an album, closing the menu behind it', async () => {
		const { target } = await render({
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target);

		const dialog = shareWarningDialog(target);
		expect(dialog).not.toBeNull();
		expect(dialog?.textContent).toContain('No Take Song');
		expect(target.querySelector('.menu-panel')).toBeNull();
	});

	it('closes only the warning dialog on Escape, leaving no stacked modal behind', async () => {
		const { target } = await render({
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target);
		expect(shareWarningDialog(target)).not.toBeNull();

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();

		expect(shareWarningDialog(target)).toBeNull();
		expect(target.querySelector('.menu-panel')).toBeNull();
		expect(target.querySelectorAll('[role="dialog"]')).toHaveLength(0);
	});

	it('does not open a warning dialog when every song has a playable take', async () => {
		const { target } = await render();

		await openMenuAndShare(target);

		expect(shareWarningDialog(target)).toBeNull();
	});

	it('does not warn for playlist shares', async () => {
		const { target } = await render({
			kind: 'playlist',
			onshare: vi
				.fn<() => Promise<ShareResult>>()
				.mockResolvedValue(
					shareResult({ songs_without_playable_take: [{ id: 's1', title: 'No Take Song' }] })
				)
		});

		await openMenuAndShare(target, 'Share playlist');

		expect(shareWarningDialog(target)).toBeNull();
	});
});

describe('CollectionMenu Share row', () => {
	const shareRowKinds = [
		{ kind: 'album', label: 'Share' },
		{ kind: 'playlist', label: 'Share playlist' }
	] as const;

	it.each([
		{ isShared: false, state: 'off' },
		{ isShared: true, state: 'on' }
	])(
		'1480_R2: shows $state in words on the one Share control when isShared is $isShared',
		async (row) => {
			const { target } = await render({ isShared: row.isShared });
			await openCollectionMenu(target);

			const share = menuRow(target, 'Share');

			expect(share.querySelector('.menu-item-hint')?.textContent).toBe(row.state);
			expect(share.getAttribute('aria-pressed')).toBe(String(row.isShared));
			expect(share.querySelector('svg')).not.toBeNull();
		}
	);

	it.each([
		{ kind: 'album', label: 'Share', path: '/share/abc' },
		{ kind: 'playlist', label: 'Share playlist', path: '/share/playlist/abc' }
	] as const)('names the $kind share page in the shared tooltip', async (row) => {
		const { target } = await render({ kind: row.kind, isShared: true, shareSlug: 'abc' });
		await openCollectionMenu(target);

		expect(menuRow(target, row.label).title).toBe(`Shared: ${row.path}`);
	});

	it('1480_R2: draws a different icon once shared, so the state is not colour alone', async () => {
		const iconOf = async (isShared: boolean) => {
			const { target } = await render({ isShared });
			await openCollectionMenu(target);
			const icon = menuRow(target, 'Share').querySelector('svg')?.innerHTML;
			await unmount(mounted.pop() as ReturnType<typeof mount>);
			return icon;
		};

		expect(await iconOf(true)).not.toBe(await iconOf(false));
	});

	it.each(shareRowKinds)(
		'1480_R3: shares and copies the link from a tap on the $kind row, keeping the menu open',
		async ({ kind, label }) => {
			const { target, props } = await render({ kind });
			await openCollectionMenu(target);

			menuRow(target, label).click();

			await vi.waitFor(() =>
				expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://example.test/share/abc')
			);
			expect(props.onshare).toHaveBeenCalledTimes(1);
			expect(target.querySelector('.menu-panel')).not.toBeNull();
		}
	);

	it.each(shareRowKinds)(
		'1480_R3: unshares a shared $kind from a tap on its row, without copying a link',
		async ({ kind, label }) => {
			const { target, props } = await render({ kind, isShared: true, shareSlug: 'abc' });
			await openCollectionMenu(target);

			menuRow(target, label).click();

			await vi.waitFor(() => expect(props.onunshare).toHaveBeenCalledTimes(1));
			expect(props.onshare).not.toHaveBeenCalled();
			expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
		}
	);

	it('1480_R3: ignores a second tap while the first share is still under way', async () => {
		let finishShare: (result: ShareResult) => void = () => {};
		const onshare = vi.fn<() => Promise<ShareResult>>(
			() => new Promise((resolve) => (finishShare = resolve))
		);
		const { target } = await render({ onshare });
		await openCollectionMenu(target);

		menuRow(target, 'Share').click();
		menuRow(target, 'Share').click();
		finishShare(shareResult());

		await vi.waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
		expect(onshare).toHaveBeenCalledTimes(1);
	});
});

function albumMenuProps() {
	return {
		oneditdetails: vi.fn(),
		oncoveredit: vi.fn(),
		oncover: vi.fn(),
		onremovecover: vi.fn(),
		hasCover: true,
		oncurate: vi.fn(),
		onaddtoplaylist: vi.fn(),
		onarchive: vi.fn()
	};
}

describe('CollectionMenu album rows', () => {
	it('915_C3: lists exactly Edit details · Cover · Pick album takes · Add to playlist · Share · Archive · Delete, Delete red and last', async () => {
		const { target } = await render(albumMenuProps());
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();

		expect(menuRowLabels(target)).toEqual([
			'Edit details',
			'Cover',
			'Pick album takes',
			'Add to playlist',
			'Share',
			'Archive',
			'Delete'
		]);
		const items = target.querySelectorAll('.menu-item');
		expect(items[items.length - 1].classList.contains('destructive')).toBe(true);
	});

	it('tells on the Cover row what the cover editor offers: upload · suggest', async () => {
		const { target } = await render(albumMenuProps());
		await openCollectionMenu(target);

		expect(menuRow(target, 'Cover').querySelector('.menu-item-hint')?.textContent).toBe(
			'upload · suggest'
		);
	});

	it('opens the cover editor from Cover and closes the menu, leaving upload and remove to it', async () => {
		const handlers = albumMenuProps();
		const { target } = await render(handlers);
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();

		Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'))
			.find((item) => item.textContent?.trim().startsWith('Cover'))
			?.click();
		await tick();

		expect(handlers.oncoveredit).toHaveBeenCalledTimes(1);
		expect(handlers.oncover).not.toHaveBeenCalled();
		expect(handlers.onremovecover).not.toHaveBeenCalled();
		expect(target.querySelector('.menu-panel')).toBeNull();
	});
});

describe('CollectionMenu Edit details', () => {
	it('offers Edit details in place of Rename and hands the tap over, closing the menu', async () => {
		const oneditdetails = vi.fn();
		const { target, props } = await render({ oneditdetails });
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();

		expect(menuRowLabels(target)).toContain('Edit details');
		expect(menuRowLabels(target)).not.toContain('Rename');

		Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'))
			.find((item) => item.textContent?.trim() === 'Edit details')
			?.click();
		await tick();

		expect(oneditdetails).toHaveBeenCalledTimes(1);
		expect(props.onrename).not.toHaveBeenCalled();
		expect(target.querySelector('.menu-panel')).toBeNull();
	});

	it('keeps Rename where no details editing is offered, as for a playlist', async () => {
		const { target } = await render({ kind: 'playlist' });
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();

		expect(menuRowLabels(target)).toContain('Rename');
		expect(menuRowLabels(target)).not.toContain('Edit details');
	});
});

let renameSawHistoryAt: number | undefined;

describeBackClosesOverlay({
	name: 'the collection menu',
	render: async () =>
		(
			await render({
				kind: 'playlist',
				onrename: vi.fn(() => {
					renameSawHistoryAt = plannedHistoryIndex();
				})
			})
		).target,
	open: (target) => target.querySelector<HTMLButtonElement>('.menu-trigger')?.click(),
	isShown: (target) => target.querySelector('.menu-panel') !== null,
	closeWays: [
		{
			way: 'a tap outside',
			close: (target) => target.querySelector<HTMLButtonElement>('.menu-backdrop')?.click()
		},
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		},
		{
			way: 'choosing Rename',
			close: (target) =>
				Array.from(target.querySelectorAll<HTMLButtonElement>('.menu-item'))
					.find((item) => item.textContent?.trim() === COLLECTION_MENU_RENAME_LABEL)
					?.click(),
			actionSawHistoryAt: () => renameSawHistoryAt
		}
	]
});
