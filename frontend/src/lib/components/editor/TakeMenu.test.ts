import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem } from '$lib/api/types';
import { HITBOX_COMPACT_PX, HITBOX_FREQUENT_PX } from '$lib/constants';
import { HITBOX_STYLE as hitboxCss } from '$lib/styles/hitbox';
import TakeMenu from './TakeMenu.svelte';

function px(value: string): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	return Number.parseFloat(resolved);
}

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	const sheet = document.createElement('style');
	sheet.dataset.hitboxStyles = 'true';
	sheet.textContent = hitboxCss;
	document.head.append(sheet);
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	document.head.querySelectorAll('[data-hitbox-styles]').forEach((el) => el.remove());
	delete document.documentElement.dataset.pointer;
});

function gen(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 3,
		generation_number: 2,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function defaultProps() {
	return {
		gen: gen(),
		onagain: vi.fn(),
		onuseasreference: vi.fn(),
		onshare: vi.fn(),
		onunshare: vi.fn(),
		oncopylink: vi.fn(),
		onpinseed: vi.fn(),
		onaddtoplaylist: vi.fn(),
		onremaster: vi.fn(),
		onrestore: vi.fn(),
		ondelete: vi.fn()
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(TakeMenu, { target, props }));
	await tick();
	target.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
	await tick();
	return { target, props };
}

describe('TakeMenu', () => {
	it('names the take on the first row', async () => {
		const { target } = await render();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Take · v3 · 2');
	});

	it('offers Share when not shared, and Unshare/Copy link when shared', async () => {
		const { target: unshared } = await render();
		const items = Array.from(unshared.querySelectorAll('.overflow-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(items).toContain('Share take');
		expect(items).not.toContain('Copy link');

		const { target: shared } = await render({ gen: gen({ is_shared: true }) });
		const sharedItems = Array.from(shared.querySelectorAll('.overflow-item')).map((el) =>
			el.textContent?.trim()
		);
		expect(sharedItems).toContain('Copy link');
		expect(sharedItems).toContain('Unshare');
	});

	it('runs the action and closes on click', async () => {
		const { target, props } = await render();
		const item = Array.from(target.querySelectorAll<HTMLButtonElement>('.overflow-item')).find(
			(el) => el.textContent?.trim() === 'Use as reference'
		);
		item?.click();
		await tick();
		expect(props.onuseasreference).toHaveBeenCalledTimes(1);
		expect(target.querySelector('.overflow-menu')).toBeNull();
	});

	it('sizes the overflow trigger to the frequent hitbox on a coarse pointer', async () => {
		const { target } = await render();
		const btn = target.querySelector<HTMLButtonElement>('.overflow-btn');
		if (!btn) throw new Error('Expected the overflow trigger button');
		document.documentElement.dataset.pointer = 'coarse';
		const coarse = getComputedStyle(btn);
		expect(px(coarse.minWidth)).toBe(HITBOX_FREQUENT_PX);
		expect(px(coarse.minHeight)).toBe(HITBOX_FREQUENT_PX);
		document.documentElement.dataset.pointer = 'fine';
		const fine = getComputedStyle(btn);
		expect(px(fine.minWidth)).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});

	it('closes on Escape', async () => {
		const { target } = await render();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.overflow-menu')).toBeNull();
	});

	it('opens downward when there is enough space below the trigger', async () => {
		vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
			bottom: 400,
			top: 0,
			left: 0,
			right: 0,
			height: 0,
			width: 0,
			x: 0,
			y: 0,
			toJSON: () => ({})
		});
		vi.stubGlobal('innerHeight', 800);
		const { target } = await render();
		await tick();
		expect(target.querySelector('.overflow-menu')?.classList.contains('flip-up')).toBe(false);
		vi.unstubAllGlobals();
	});

	it('flips upward when there is not enough space below the trigger', async () => {
		vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
			bottom: 900,
			top: 500,
			left: 0,
			right: 0,
			height: 0,
			width: 0,
			x: 0,
			y: 0,
			toJSON: () => ({})
		});
		vi.stubGlobal('innerHeight', 800);
		const { target } = await render();
		await tick();
		expect(target.querySelector('.overflow-menu')?.classList.contains('flip-up')).toBe(true);
		vi.unstubAllGlobals();
	});
});
