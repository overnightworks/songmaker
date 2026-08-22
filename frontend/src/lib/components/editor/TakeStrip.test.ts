import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem } from '$lib/api/types';
import TakeStrip from './TakeStrip.svelte';

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
		generation_number: 3,
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

async function render(generations: GenerationItem[], onselect = vi.fn()) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(TakeStrip, { target, props: { generations, onselect } }));
	await tick();
	return { target, onselect };
}

describe('TakeStrip', () => {
	it('renders one chip per take, newest version and take first', async () => {
		const { target } = await render([
			gen({ id: 'g1', version_number: 2, generation_number: 1 }),
			gen({ id: 'g2', version_number: 3, generation_number: 2 }),
			gen({ id: 'g3', version_number: 3, generation_number: 1 })
		]);
		const labels = Array.from(target.querySelectorAll('.take-chip-label')).map(
			(el) => el.textContent
		);
		expect(labels).toEqual(['v3-2', 'v3-1', 'v2-1']);
	});

	it('shows a pick or keep badge and plays the take on click', async () => {
		const onselect = vi.fn();
		const picked = gen({ id: 'g1', is_picked: true });
		const { target } = await render([picked], onselect);
		expect(target.querySelector('.badge.picked')).not.toBeNull();
		target.querySelector<HTMLButtonElement>('.take-chip')?.click();
		expect(onselect).toHaveBeenCalledWith(picked);
	});

	it('renders nothing when there are no takes', async () => {
		const { target } = await render([]);
		expect(target.querySelector('.take-strip')).toBeNull();
	});
});
