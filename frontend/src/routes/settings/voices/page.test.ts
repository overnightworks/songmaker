import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/fetch';

const mocks = vi.hoisted(() => ({
	loadLoras: vi.fn(),
	createLora: vi.fn(),
	softDeleteLora: vi.fn(),
	refreshLora: vi.fn(),
	listOwnPlayableTakes: vi.fn(),
	addLoraSampleFromGeneration: vi.fn()
}));

vi.mock('$lib/stores/loras', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/loras')>();
	return {
		...actual,
		loadLoras: (...args: unknown[]) => mocks.loadLoras(...args),
		createLora: (...args: unknown[]) => mocks.createLora(...args),
		softDeleteLora: (...args: unknown[]) => mocks.softDeleteLora(...args),
		refreshLora: (...args: unknown[]) => mocks.refreshLora(...args)
	};
});

vi.mock('$lib/api/loras', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/loras')>();
	return {
		...actual,
		listOwnPlayableTakes: (...args: unknown[]) => mocks.listOwnPlayableTakes(...args),
		addLoraSampleFromGeneration: (...args: unknown[]) => mocks.addLoraSampleFromGeneration(...args)
	};
});

vi.mock('$lib/stores/toast', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/toast')>();
	return { ...actual, addToast: vi.fn() };
});

import VoicesPage from './+page.svelte';
import { loras, lorasError, lorasLoading } from '$lib/stores/loras';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	mocks.loadLoras.mockReset().mockResolvedValue([]);
	mocks.createLora.mockReset();
	mocks.softDeleteLora.mockReset();
	mocks.refreshLora.mockReset();
	mocks.listOwnPlayableTakes.mockReset();
	mocks.addLoraSampleFromGeneration.mockReset();
	loras.set([]);
	lorasLoading.set(false);
	lorasError.set(null);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('voices page', () => {
	it('shows the copied take metadata after the voice refreshes', async () => {
		const voice = {
			id: 'l1',
			user_id: 'u1',
			name: 'My Tenor',
			slug: 'my-tenor',
			status: 'draft',
			created_at: '2026-09-05T00:00:00Z',
			deleted_at: null,
			samples: []
		};
		const copiedSample = {
			id: 's1',
			user_lora_id: voice.id,
			audio_path: 'user_loras/u1/l1/samples/s1.mp3',
			caption: 'warm tenor',
			lyrics: 'A line from the take',
			position: 0,
			created_at: '2026-09-05T00:00:00Z',
			updated_at: '2026-09-05T00:00:00Z'
		};
		const refreshedVoice = { ...voice, samples: [copiedSample] };
		mocks.listOwnPlayableTakes.mockResolvedValueOnce([
			{
				generation_id: 'g1',
				song_title: 'Glass River',
				generation_number: 4,
				audio_url: '/audio/u1/g1.mp3',
				caption: copiedSample.caption,
				lyrics: copiedSample.lyrics
			}
		]);
		mocks.addLoraSampleFromGeneration.mockResolvedValueOnce(copiedSample);
		mocks.refreshLora.mockImplementationOnce(async () => {
			loras.set([refreshedVoice]);
			return refreshedVoice;
		});
		loras.set([voice]);
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(VoicesPage, { target });
		await tick();

		target.querySelector<HTMLButtonElement>('.lora-row')?.click();
		await tick();
		target.querySelector<HTMLButtonElement>('.own-takes-toggle')?.click();
		await vi.waitFor(() => expect(target.textContent).toContain('Glass River'));
		target.querySelector<HTMLButtonElement>('.use-take-btn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelectorAll<HTMLTextAreaElement>('.sample-list textarea')).toHaveLength(2)
		);
		const fields = target.querySelectorAll<HTMLTextAreaElement>('.sample-list textarea');
		expect(fields[0]?.value).toBe(copiedSample.caption);
		expect(fields[1]?.value).toBe(copiedSample.lyrics);
	});

	it('shows the unchanged server 409 detail when creating a voice reaches its limit', async () => {
		const detail =
			'You have reached the limit of 10 voices. Delete a voice before creating another.';
		mocks.createLora.mockRejectedValueOnce(new ApiError(409, detail, '/api/loras'));
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(VoicesPage, { target });
		await tick();

		target.querySelector<HTMLButtonElement>('.create-btn')?.click();
		await tick();
		const input = target.querySelector<HTMLInputElement>('.create-panel input');
		if (!input) throw new Error('Expected voice name input');
		input.value = 'My Tenor';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		target.querySelector<HTMLButtonElement>('.create-panel .primary')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toBe(detail)
		);
		expect(mocks.createLora).toHaveBeenCalledWith('My Tenor');
	});
});
