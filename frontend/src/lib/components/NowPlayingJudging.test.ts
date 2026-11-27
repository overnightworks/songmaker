import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '#lib/api/types.ts';

vi.mock('#lib/stores/takeActions.ts', () => ({
	togglePick: vi.fn().mockResolvedValue(undefined),
	toggleKeep: vi.fn().mockResolvedValue(undefined),
	rate: vi.fn().mockResolvedValue(undefined)
}));

import { rate, toggleKeep, togglePick } from '#lib/stores/takeActions.ts';
import { reactiveProps } from '#lib/test-utils/reactive-props.svelte.ts';
import { queryButtonByLabel } from '#lib/test-utils/accessible-name.ts';
import { words } from '#lib/words/en.ts';
import NowPlayingJudging, { NOTE_SAVE_PAUSE_MS } from './NowPlayingJudging.svelte';

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;
let props: { generation: GenerationItem; song: SongItem };

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.clearAllMocks();
	vi.useRealTimers();
});

async function renderJudging(take: GenerationItem = generation()): Promise<void> {
	target = document.createElement('div');
	document.body.append(target);
	props = reactiveProps({ generation: take, song: song() });
	mounted = mount(NowPlayingJudging, { target, props });
	await tick();
}

function ratingSlider(): HTMLInputElement {
	const found = target.querySelector<HTMLInputElement>('input[type="range"]');
	if (!found) throw new Error('Expected the rating slider');
	return found;
}

function note(): HTMLTextAreaElement {
	const found = target.querySelector<HTMLTextAreaElement>('textarea');
	if (!found) throw new Error('Expected the note field');
	return found;
}

function typeNote(text: string): void {
	note().value = text;
	note().dispatchEvent(new Event('input', { bubbles: true }));
}

describe('NowPlayingJudging', () => {
	it.each([
		{ name: 'Pick', field: 'is_picked', off: 'pick', on: 'unpick', toggle: togglePick },
		{ name: 'Keep', field: 'is_kept', off: 'keep', on: 'unkeep', toggle: toggleKeep }
	] as const)('$name flips the take it shows', async ({ field, off, on, toggle }) => {
		const take = generation({ [field]: true });
		await renderJudging(take);

		queryButtonByLabel(target, words[`nowPlayingJudging.${on}`])?.click();

		expect(toggle).toHaveBeenCalledWith('s1', take);
		expect(queryButtonByLabel(target, words[`nowPlayingJudging.${on}`])?.ariaPressed).toBe('true');
		expect(queryButtonByLabel(target, words[`nowPlayingJudging.${off}`])).toBeNull();
	});

	it.each(['pick', 'keep', 'rating'] as const)('writes the word %s on the card', async (word) => {
		await renderJudging();

		expect(target).toHaveTextContent(words[`nowPlayingJudging.${word}`]);
	});

	it('opts its buttons into the frequent hitbox', async () => {
		await renderJudging();

		for (const button of target.querySelectorAll<HTMLElement>('button')) {
			expect(button.dataset.hitbox).toBe('frequent');
		}
	});

	it('starts an unrated take at 50 and saves nothing yet', async () => {
		await renderJudging(generation({ scores: null }));

		expect(ratingSlider().value).toBe('50');
		expect(rate).not.toHaveBeenCalled();
	});

	it('shows the saved rating and note', async () => {
		await renderJudging(generation({ scores: { user_rating: 82, user_notes: 'Warm bridge' } }));

		expect(ratingSlider().value).toBe('82');
		expect(note().value).toBe('Warm bridge');
	});

	it('saves the rating with the note when the slider is released, and not while dragging', async () => {
		await renderJudging(generation({ scores: { user_rating: 50, user_notes: 'Warm bridge' } }));

		ratingSlider().value = '80';
		ratingSlider().dispatchEvent(new Event('input', { bubbles: true }));
		expect(rate).not.toHaveBeenCalled();
		ratingSlider().dispatchEvent(new Event('change', { bubbles: true }));

		expect(rate).toHaveBeenCalledExactlyOnceWith('s1', 'g1', 80, 'Warm bridge');
	});

	it('saves the note after a pause in typing, not before', async () => {
		await renderJudging(generation({ scores: { user_rating: 70, user_notes: '' } }));

		typeNote('Loved');
		typeNote('Loved the bridge');
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS - 1);
		expect(rate).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);

		expect(rate).toHaveBeenCalledExactlyOnceWith('s1', 'g1', 70, 'Loved the bridge');
	});

	it('saves an unrated take with a note at the slider start', async () => {
		await renderJudging(generation({ scores: null }));

		typeNote('Needs a second verse');
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS);

		expect(rate).toHaveBeenCalledExactlyOnceWith('s1', 'g1', 50, 'Needs a second verse');
	});

	it('saves the note once when the field is left before the pause ends', async () => {
		await renderJudging(generation({ scores: { user_rating: 70, user_notes: '' } }));

		typeNote('Loved it');
		note().dispatchEvent(new Event('blur'));
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS);

		expect(rate).toHaveBeenCalledExactlyOnceWith('s1', 'g1', 70, 'Loved it');
	});

	it('saves a pending note when the card goes away', async () => {
		await renderJudging(generation({ scores: { user_rating: 70, user_notes: '' } }));

		typeNote('Typed then gone');
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS - 1);
		if (mounted) await unmount(mounted);
		mounted = undefined;

		expect(rate).toHaveBeenCalledExactlyOnceWith('s1', 'g1', 70, 'Typed then gone');
	});

	it('saves nothing when the field is left unchanged', async () => {
		await renderJudging(generation({ scores: { user_rating: 70, user_notes: 'Same' } }));

		note().dispatchEvent(new Event('blur'));
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS);

		expect(rate).not.toHaveBeenCalled();
	});

	it('keeps the typed note after its save', async () => {
		await renderJudging(generation({ scores: { user_rating: 70, user_notes: '' } }));

		typeNote('Still mine');
		vi.advanceTimersByTime(NOTE_SAVE_PAUSE_MS);
		await tick();

		expect(note().value).toBe('Still mine');
	});

	it('fills an untouched field when the saved scores arrive late, but not a typed one', async () => {
		await renderJudging(generation({ scores: null }));
		typeNote('Typed first');

		props.generation = generation({ scores: { user_rating: 90, user_notes: 'From the server' } });
		await tick();

		expect(ratingSlider().value).toBe('90');
		expect(note().value).toBe('Typed first');
	});
});
