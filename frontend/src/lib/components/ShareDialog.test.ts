import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeBackClosesOverlay } from '$lib/test-utils/library-history';
import ShareDialog from './ShareDialog.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

function defaultProps() {
	return {
		songs: [
			{ id: 's1', title: 'Ballad Without a Take' },
			{ id: 's2', title: 'Second Silent Song' }
		],
		onclose: vi.fn()
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(ShareDialog, { target, props }));
	await tick();
	return { target, props };
}

describe('ShareDialog', () => {
	it('lists the title of every song without a playable take', async () => {
		const { target } = await render();
		const items = Array.from(target.querySelectorAll('li')).map((li) => li.textContent);
		expect(items).toEqual(['Ballad Without a Take', 'Second Silent Song']);
	});

	it('hides the block entirely when there are no missing songs', async () => {
		const { target } = await render({ songs: [] });
		expect(target.querySelector('[role="dialog"]')).toBeNull();
	});

	it('closes on the primary action, the backdrop, and Escape', async () => {
		const { target, props } = await render();
		target.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
		expect(props.onclose).toHaveBeenCalledTimes(1);

		target.querySelector<HTMLButtonElement>('.overlay-backdrop')?.click();
		expect(props.onclose).toHaveBeenCalledTimes(2);

		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		expect(props.onclose).toHaveBeenCalledTimes(3);
	});

	it('marks the dialog aria-modal', async () => {
		const { target } = await render();
		const dialog = target.querySelector('[role="dialog"]');
		expect(dialog?.getAttribute('aria-modal')).toBe('true');
	});

	it('focuses the first focusable element on open', async () => {
		const { target } = await render();
		await tick();
		expect(document.activeElement).toBe(target.querySelector('.confirm-btn'));
	});
});

// CollectionMenu empties the missing songs on close, which hides the warning.
const shareWarning = {
	closes: 0,
	shown: null as ReturnType<typeof mount> | null,
	open(target: HTMLElement): void {
		shareWarning.closes = 0;
		shareWarning.shown = mount(ShareDialog, {
			target,
			props: { songs: defaultProps().songs, onclose: shareWarning.close }
		});
		mounted.push(shareWarning.shown);
	},
	close(): void {
		shareWarning.closes += 1;
		if (shareWarning.shown) void unmount(shareWarning.shown);
		shareWarning.shown = null;
	}
};

describeBackClosesOverlay({
	name: 'the share warning',
	render: async () => {
		const target = document.createElement('div');
		document.body.append(target);
		return target;
	},
	open: shareWarning.open,
	isShown: (target) => target.querySelector('[role="dialog"]') !== null,
	afterBack: () => expect(shareWarning.closes).toBe(1),
	closeWays: [
		{
			way: 'Got it',
			close: (target) => target.querySelector<HTMLButtonElement>('.confirm-btn')?.click()
		},
		{
			way: 'the backdrop',
			close: (target) => target.querySelector<HTMLButtonElement>('.overlay-backdrop')?.click()
		},
		{
			way: 'Escape',
			close: () =>
				window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
		}
	]
});
