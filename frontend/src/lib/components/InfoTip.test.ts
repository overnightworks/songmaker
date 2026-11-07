import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import InfoTip from './InfoTip.svelte';

const TIP_TEXT = 'Plays here, details in Now Playing';
let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	vi.unstubAllGlobals();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function mountTip(): Promise<{ button: HTMLButtonElement; tip: HTMLElement }> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(InfoTip, { target, props: { label: 'About takes', text: TIP_TEXT } });
	await tick();
	const button = target.querySelector<HTMLButtonElement>('button');
	const tip = target.querySelector<HTMLElement>('[role="tooltip"]');
	if (!button || !tip) throw new Error('Expected the info tip');
	return { button, tip };
}

const VIEWPORT_WIDTH = 375;
const TIP_WIDTH = 212;

// jsdom has no layout: the tip sits at the given left edge, moved by the
// translate the component applies, the way a browser would place it.
function placeTipAt(tip: HTMLElement, left: number): void {
	tip.getBoundingClientRect = () => {
		const shift = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(tip.style.transform);
		const x = left + Number(shift?.[1] ?? 0);
		const y = 20 + Number(shift?.[2] ?? 0);
		return new DOMRect(x, y, TIP_WIDTH, 40);
	};
}

describe('InfoTip', () => {
	it.each([
		['the left edge', -59],
		['the right edge', 300]
	])('keeps its box inside the viewport near %s', async (_edge, left) => {
		vi.stubGlobal('innerWidth', VIEWPORT_WIDTH);
		const { button, tip } = await mountTip();
		placeTipAt(tip, left);
		button.click();
		await tick();
		const box = tip.getBoundingClientRect();
		expect(box.left).toBeGreaterThanOrEqual(0);
		expect(box.right).toBeLessThanOrEqual(VIEWPORT_WIDTH);
	});

	it('keeps its box below the top of the viewport', async () => {
		const { button, tip } = await mountTip();
		tip.getBoundingClientRect = () => {
			const shift = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(tip.style.transform);
			return new DOMRect(10, -30 + Number(shift?.[2] ?? 0), TIP_WIDTH, 40);
		};
		button.click();
		await tick();
		expect(tip.getBoundingClientRect().top).toBeGreaterThanOrEqual(0);
	});

	it('is closed until asked', async () => {
		const { tip } = await mountTip();
		expect(tip.hidden).toBe(true);
	});

	it('opens on hover and closes when the pointer leaves', async () => {
		const { button, tip } = await mountTip();
		button.dispatchEvent(new MouseEvent('mouseenter'));
		await tick();
		expect(tip.hidden).toBe(false);
		button.dispatchEvent(new MouseEvent('mouseleave'));
		await tick();
		expect(tip.hidden).toBe(true);
	});

	it('opens on focus and closes on blur', async () => {
		const { button, tip } = await mountTip();
		button.focus();
		await tick();
		expect(tip.hidden).toBe(false);
		button.blur();
		await tick();
		expect(tip.hidden).toBe(true);
	});

	it('opens on tap', async () => {
		const { button, tip } = await mountTip();
		button.click();
		await tick();
		expect(tip.hidden).toBe(false);
	});

	it('closes on Escape', async () => {
		const { button, tip } = await mountTip();
		button.click();
		button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(tip.hidden).toBe(true);
	});

	it('closes on a tap outside', async () => {
		const { button, tip } = await mountTip();
		button.click();
		document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
		await tick();
		expect(tip.hidden).toBe(true);
	});

	it('gives its text as the button description', async () => {
		const { button, tip } = await mountTip();
		expect(button.getAttribute('aria-describedby')).toBe(tip.id);
		expect(tip.textContent).toBe(TIP_TEXT);
		expect(button.getAttribute('aria-label')).toBe('About takes');
	});
});
