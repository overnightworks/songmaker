import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

const MENU_ITEMS = '<div><button>Rename</button><button>Delete</button></div>';

async function openPopover(items = MENU_ITEMS): Promise<HTMLElement> {
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
	target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
	await tick();
	await tick();
	const panel = target.querySelector<HTMLElement>('.menu-panel');
	if (!panel) throw new Error('Expected the popover panel to open');
	return panel;
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

describe('MenuPopover focus', () => {
	function button(name: string): HTMLButtonElement {
		const found = Array.from(document.querySelectorAll('button')).find(
			(candidate) => (candidate.getAttribute('aria-label') ?? candidate.textContent) === name
		);
		if (!found) throw new Error(`Expected a button named ${name}`);
		return found;
	}

	function press(key: string, shiftKey = false): void {
		window.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
	}

	function isOpen(): boolean {
		return document.querySelector('.menu-panel') !== null;
	}

	async function focusSettles(): Promise<void> {
		await Promise.resolve();
		await tick();
	}

	it('moves focus to the first item when it opens', async () => {
		await openPopover();

		expect(document.activeElement).toBe(button('Rename'));
	});

	it.each([
		{ from: 'Delete', shiftKey: false, to: 'Rename', way: 'Tab past the last item' },
		{ from: 'Rename', shiftKey: true, to: 'Delete', way: 'Shift+Tab before the first item' }
	])('keeps focus inside: $way wraps to $to', async ({ from, shiftKey, to }) => {
		await openPopover();
		button(from).focus();

		press('Tab', shiftKey);

		expect(document.activeElement).toBe(button(to));
	});

	it.each([
		{ way: 'Escape', close: () => press('Escape') },
		{ way: 'a tap outside', close: () => button('Close menu').click() },
		{ way: 'the trigger again', close: () => button('More').click() }
	])('closing it by $way hands focus back to the trigger', async ({ close }) => {
		await openPopover();

		close();
		await focusSettles();

		expect(isOpen()).toBe(false);
		expect(document.activeElement).toBe(button('More'));
	});
});
