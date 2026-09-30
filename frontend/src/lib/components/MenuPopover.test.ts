import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeBackClosesOverlay } from '$lib/test-utils/library-history';
import MenuPopover from './MenuPopover.svelte';

const PANEL_WIDTH = 220;
const PANEL_HEIGHT = 300;
const TRIGGER_SIZE = 34;

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	vi.restoreAllMocks();
	document.body.replaceChildren();
});

interface Viewport {
	width: number;
	height: number;
}

interface Placement {
	left: number;
	top: number;
}

function setViewport({ width, height }: Viewport): void {
	Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
	Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
}

function layOut(trigger: Placement, panelHeight = PANEL_HEIGHT): void {
	vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
		this: HTMLElement
	) {
		if (this.classList.contains('menu-trigger'))
			return new DOMRect(trigger.left, trigger.top, TRIGGER_SIZE, TRIGGER_SIZE);
		if (this.classList.contains('menu-panel')) return new DOMRect(0, 0, PANEL_WIDTH, panelHeight);
		return new DOMRect();
	});
}

const ONE_ITEM = '<button>Rename</button>';
const TWO_ITEMS = '<div><button>Rename</button><button>Delete</button></div>';

async function renderClosed(items = ONE_ITEM): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(MenuPopover, {
		target,
		props: {
			layer: 'test-menu',
			label: 'More',
			closeLabel: 'Close menu',
			trigger: createRawSnippet(() => ({ render: () => '<span>⋯</span>' })),
			children: createRawSnippet(() => ({ render: () => items }))
		}
	});
	await tick();
	return target;
}

function triggerOf(target: ParentNode): HTMLButtonElement {
	const trigger = target.querySelector<HTMLButtonElement>('.menu-trigger');
	if (!trigger) throw new Error('Expected the popover trigger');
	return trigger;
}

async function openIn(target: HTMLElement): Promise<HTMLElement> {
	triggerOf(target).click();
	await tick();
	await tick();
	const panel = target.querySelector<HTMLElement>('.menu-panel');
	if (!panel) throw new Error('Expected the popover panel to open');
	return panel;
}

async function openPopover(items = ONE_ITEM): Promise<HTMLElement> {
	return openIn(await renderClosed(items));
}

function pressOnWindow(key: string, shiftKey = false): void {
	window.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
}

async function focusReturned(): Promise<void> {
	await Promise.resolve();
	await tick();
}

function placementOf(panel: HTMLElement): Placement {
	return { left: parseFloat(panel.style.left), top: parseFloat(panel.style.top) };
}

describe('MenuPopover placement', () => {
	it.each([
		{
			case: 'under a trigger at the left edge of a phone, pulled 8 px inside instead of past the edge',
			viewport: { width: 390, height: 844 },
			trigger: { left: 16, top: 120 },
			expected: { left: 8, top: 162 }
		},
		{
			case: 'right-aligned to a trigger with room on the left',
			viewport: { width: 1280, height: 800 },
			trigger: { left: 900, top: 120 },
			expected: { left: 900 + TRIGGER_SIZE - PANEL_WIDTH, top: 162 }
		},
		{
			case: 'pulled 8 px inside the right edge when the trigger sits past it',
			viewport: { width: 390, height: 844 },
			trigger: { left: 380, top: 120 },
			expected: { left: 390 - 8 - PANEL_WIDTH, top: 162 }
		},
		{
			case: 'at the right screen edge, 8 px inside, under a trigger at the right of a phone',
			viewport: { width: 390, height: 844 },
			trigger: { left: 390 - 12 - TRIGGER_SIZE, top: 120 },
			expected: { left: 390 - 8 - PANEL_WIDTH, top: 162 }
		},
		{
			case: 'above the trigger when there is no room below',
			viewport: { width: 1280, height: 800 },
			trigger: { left: 900, top: 700 },
			expected: { left: 900 + TRIGGER_SIZE - PANEL_WIDTH, top: 700 - 8 - PANEL_HEIGHT }
		},
		{
			case: 'pulled 8 px inside the bottom edge when neither below nor above fits',
			viewport: { width: 390, height: 400 },
			trigger: { left: 16, top: 200 },
			expected: { left: 8, top: 400 - 8 - PANEL_HEIGHT }
		}
	])('opens $case', async ({ viewport, trigger, expected }) => {
		setViewport(viewport);
		layOut(trigger);

		const panel = await openPopover();

		expect(placementOf(panel)).toEqual(expected);
	});

	it('keeps a panel taller than the viewport 8 px inside the top edge', async () => {
		setViewport({ width: 390, height: 200 });
		layOut({ left: 16, top: 80 }, 500);

		const panel = await openPopover();

		expect(placementOf(panel).top).toBe(8);
	});

	it('places itself again when the viewport changes while open', async () => {
		setViewport({ width: 1280, height: 800 });
		layOut({ left: 900, top: 120 });
		const panel = await openPopover();

		setViewport({ width: 390, height: 844 });
		layOut({ left: 16, top: 120 });
		window.dispatchEvent(new Event('resize'));
		await tick();

		expect(placementOf(panel)).toEqual({ left: 8, top: 162 });
	});
});

describe('MenuPopover keyboard', () => {
	it('shows pressed while open and moves focus to its first item', async () => {
		const panel = await openPopover(TWO_ITEMS);

		expect(triggerOf(document).getAttribute('aria-expanded')).toBe('true');
		expect(document.activeElement?.textContent).toBe('Rename');
		expect(panel.contains(document.activeElement)).toBe(true);
	});

	it.each([
		{ case: 'Tab on the last item wraps to the first', from: 'Delete', shift: false, to: 'Rename' },
		{
			case: 'Shift+Tab on the first item wraps to the last',
			from: 'Rename',
			shift: true,
			to: 'Delete'
		}
	])('keeps focus inside: $case', async ({ from, shift, to }) => {
		const panel = await openPopover(TWO_ITEMS);
		[...panel.querySelectorAll('button')].find((item) => item.textContent === from)?.focus();

		pressOnWindow('Tab', shift);

		expect(document.activeElement?.textContent).toBe(to);
	});

	it('Escape closes it and hands focus back to its trigger', async () => {
		const target = await renderClosed();
		await openIn(target);

		pressOnWindow('Escape');
		await focusReturned();

		expect(target.querySelector('.menu-panel')).toBeNull();
		expect(triggerOf(target).getAttribute('aria-expanded')).toBe('false');
		expect(document.activeElement).toBe(triggerOf(target));
	});
});

describeBackClosesOverlay({
	name: 'the menu popover',
	render: () => renderClosed(),
	open: async (target) => {
		await openIn(target);
	},
	isShown: (target) => target.querySelector('.menu-panel') !== null,
	closeWays: [
		{ way: 'its trigger', close: (target) => triggerOf(target).click() },
		{
			way: 'a tap outside it',
			close: (target) => target.querySelector<HTMLButtonElement>('.menu-backdrop')?.click()
		},
		{ way: 'Escape', close: () => pressOnWindow('Escape') }
	]
});
