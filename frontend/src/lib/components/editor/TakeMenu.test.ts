import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem } from '$lib/api/types';
import TakeMenu from './TakeMenu.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
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

	it('closes on Escape', async () => {
		const { target } = await render();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.overflow-menu')).toBeNull();
	});
});
