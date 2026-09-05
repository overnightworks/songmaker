import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const listLoras = vi.fn();

vi.mock('$lib/api/loras', () => ({
	listLoras: (...args: unknown[]) => listLoras(...args)
}));

import type { UserLoraItem } from '$lib/api/types';
import { editGenParams, setDraftGenParams } from '$lib/stores/editor';
import { loras } from '$lib/stores/loras';
import { recipeModel } from '$lib/stores/recipe';
import VoicePicker from './VoicePicker.svelte';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	listLoras.mockReset().mockResolvedValue([]);
	loras.set([]);
	setDraftGenParams(null);
	recipeModel.set('sft');
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(VoicePicker, { target });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

function lora(overrides: Partial<UserLoraItem> = {}): UserLoraItem {
	return {
		id: 'lora-sft',
		user_id: 'user-1',
		name: 'My Tenor',
		slug: 'my-tenor',
		status: 'ready',
		model_mode: 'sft',
		created_at: '2026-09-05T00:00:00Z',
		deleted_at: null,
		samples: [],
		...overrides
	};
}

async function openOptions(target: HTMLElement): Promise<HTMLButtonElement[]> {
	target.querySelector<HTMLButtonElement>('.picker')?.click();
	await tick();
	return Array.from(target.querySelectorAll<HTMLButtonElement>('.option'));
}

describe('VoicePicker', () => {
	it('links "Create a voice" to the Settings Voices route', async () => {
		const target = await render();
		const hint = target.querySelector<HTMLAnchorElement>('.hint');
		expect(hint?.getAttribute('href')).toBe('/settings/voices');
	});

	it('selects ready voices only when their mode exactly matches the sft model', async () => {
		loras.set([lora(), lora({ id: 'lora-turbo', name: 'Spoken Word', model_mode: 'turbo' })]);
		const target = await render();
		const [none, sft, turbo] = await openOptions(target);

		expect(none.disabled).toBe(false);
		expect(sft.disabled).toBe(false);
		expect(turbo.disabled).toBe(true);
		expect(turbo.textContent).toContain('not available for this model');

		sft.click();
		expect(get(editGenParams)?.user_lora_id).toBe('lora-sft');
	});

	it('selects turbo voices only for the turbo model', async () => {
		recipeModel.set('turbo');
		loras.set([lora(), lora({ id: 'lora-turbo', name: 'Spoken Word', model_mode: 'turbo' })]);
		const target = await render();
		const [, sft, turbo] = await openOptions(target);

		expect(sft.disabled).toBe(true);
		expect(turbo.disabled).toBe(false);
	});

	it.each(['xl-sft', 'xl-turbo', 'xl-base'])('%s has no selectable voice', async (modelMode) => {
		recipeModel.set(modelMode);
		loras.set([lora(), lora({ id: 'lora-turbo', name: 'Spoken Word', model_mode: 'turbo' })]);
		const target = await render();
		const [, ...voices] = await openOptions(target);

		for (const voice of voices) expect(voice.disabled).toBe(true);
	});

	it('keeps a referenced deleted voice visible but disabled', async () => {
		setDraftGenParams({ user_lora_id: 'deleted-lora' });
		loras.set([
			lora({ id: 'deleted-lora', name: 'Folk Alto', deleted_at: '2026-09-05T00:00:00Z' })
		]);
		const target = await render();
		const [, deleted] = await openOptions(target);

		expect(deleted.disabled).toBe(true);
		expect(deleted.textContent).toContain('voice deleted');
		expect(target.querySelector('.picker')?.textContent).toContain('voice deleted');
	});

	it('uses the picture labels and mode chips without a target-model chip', async () => {
		loras.set([lora()]);
		const target = await render();
		const options = await openOptions(target);

		expect(target.querySelector('.desktop-label')?.textContent).toBe('Your Voice');
		expect(target.querySelector('.mobile-label')?.textContent).toBe('Your Voice · sft model');
		expect(options[1].querySelector('.mode-chip')?.textContent).toBe('sft');
		expect(target.querySelector('.picker .mode-chip')).toBeNull();
	});
});
