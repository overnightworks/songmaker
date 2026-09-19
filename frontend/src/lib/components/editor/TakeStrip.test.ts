import { makeGeneration as gen, makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem } from '$lib/api/types';

vi.mock('$lib/stores/player', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/player')>();
	return {
		...actual,
		playTake: vi.fn(async () => undefined)
	};
});

import { playTake } from '$lib/stores/player';
import TakeStrip from './TakeStrip.svelte';

const genDefaults = { version_number: 3, generation_number: 3 } satisfies Partial<GenerationItem>;

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.mocked(playTake).mockClear();
});

async function render(generations: GenerationItem[]) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(TakeStrip, {
			target,
			props: {
				song: song({
					slug: 'test',
					title: 'Test',
					bpm: 120,
					audio_duration: 180,
					key_scale: 'Am',
					generation_params: null,
					best_scores: null,
					best_rating: null,
					share_slug: null,
					generations
				})
			}
		})
	);
	await tick();
	return { target };
}

describe('TakeStrip', () => {
	it('renders one chip per take, newest version and take first', async () => {
		const { target } = await render([
			gen({ ...genDefaults, version_number: 2, generation_number: 1 }),
			gen({ ...genDefaults, id: 'g2', generation_number: 2 }),
			gen({ ...genDefaults, id: 'g3', generation_number: 1 })
		]);
		const labels = Array.from(target.querySelectorAll('.take-chip-label')).map(
			(el) => el.textContent
		);
		expect(labels).toEqual(['v3 · take 2', 'v3 · take 1', 'v2 · take 1']);
	});

	it('shows a pick or keep badge', async () => {
		const picked = gen({ ...genDefaults, is_picked: true });
		const { target } = await render([picked]);
		expect(target.querySelector('.badge.picked')).not.toBeNull();
	});

	it('plays the take on click instead of opening Now Playing', async () => {
		const picked = gen({ ...genDefaults, is_picked: true });
		const { target } = await render([picked]);
		target.querySelector<HTMLButtonElement>('.take-chip')?.click();
		await tick();
		await Promise.resolve();
		expect(playTake).toHaveBeenCalledWith(picked, expect.objectContaining({ id: 's1' }));
	});

	it('renders nothing when there are no takes', async () => {
		const { target } = await render([]);
		expect(target.querySelector('.take-strip')).toBeNull();
	});
});
