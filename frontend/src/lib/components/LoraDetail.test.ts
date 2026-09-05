import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/fetch';

const addLoraSample = vi.fn();
const patchLoraSample = vi.fn();
const deleteLoraSample = vi.fn();
const listOwnPlayableTakes = vi.fn();
const addLoraSampleFromGeneration = vi.fn();
const refreshLora = vi.fn();
const trainLora = vi.fn();
const addToast = vi.fn();

vi.mock('$lib/api/client', () => ({
	ApiError,
	addLoraSample: (...args: unknown[]) => addLoraSample(...args),
	patchLoraSample: (...args: unknown[]) => patchLoraSample(...args),
	deleteLoraSample: (...args: unknown[]) => deleteLoraSample(...args)
}));

vi.mock('$lib/api/loras', () => ({
	listOwnPlayableTakes: (...args: unknown[]) => listOwnPlayableTakes(...args),
	addLoraSampleFromGeneration: (...args: unknown[]) => addLoraSampleFromGeneration(...args)
}));

vi.mock('$lib/stores/loras', () => ({
	refreshLora: (...args: unknown[]) => refreshLora(...args),
	trainLora: (...args: unknown[]) => trainLora(...args),
	isLoraActive: () => false
}));

vi.mock('$lib/stores/toast', () => ({ addToast: (...args: unknown[]) => addToast(...args) }));

import LoraDetail from './LoraDetail.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function lora() {
	return {
		id: 'l1',
		user_id: 'u1',
		name: 'My Tenor',
		slug: 'my-tenor',
		status: 'draft',
		created_at: '2026-09-05T00:00:00Z',
		deleted_at: null,
		samples: []
	};
}

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(LoraDetail, { target, props: { lora: lora() } });
	await tick();
	return target;
}

beforeEach(() => {
	addLoraSample.mockReset();
	patchLoraSample.mockReset();
	deleteLoraSample.mockReset();
	listOwnPlayableTakes.mockReset();
	addLoraSampleFromGeneration.mockReset();
	refreshLora.mockReset();
	trainLora.mockReset();
	addToast.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('LoraDetail', () => {
	it('copies a selected own take and refreshes its owner', async () => {
		listOwnPlayableTakes.mockResolvedValueOnce([
			{
				generation_id: 'g1',
				song_title: 'Glass River',
				generation_number: 4,
				audio_url: '/audio/u1/g1.mp3',
				caption: 'warm tenor',
				lyrics: 'A line from the take'
			}
		]);
		addLoraSampleFromGeneration.mockResolvedValueOnce({ id: 's1' });
		refreshLora.mockResolvedValueOnce({
			...lora(),
			samples: [{ id: 's1', caption: 'warm tenor', lyrics: 'A line from the take', position: 0 }]
		});
		const target = await render();

		target.querySelector<HTMLButtonElement>('.own-takes-toggle')?.click();
		await vi.waitFor(() => expect(target.textContent).toContain('Glass River'));
		target.querySelector<HTMLButtonElement>('.use-take-btn')?.click();

		await vi.waitFor(() => expect(addLoraSampleFromGeneration).toHaveBeenCalledWith('l1', 'g1'));
		await vi.waitFor(() => expect(refreshLora).toHaveBeenCalledWith('l1'));
		expect(addLoraSample).not.toHaveBeenCalled();
	});

	it('keeps the server 409 sentence visible when copying a take is rejected', async () => {
		listOwnPlayableTakes.mockResolvedValueOnce([
			{
				generation_id: 'g1',
				song_title: 'Glass River',
				generation_number: 4,
				audio_url: '/audio/u1/g1.mp3',
				caption: 'warm tenor',
				lyrics: 'A line from the take'
			}
		]);
		const detail = 'LoRA already has the maximum of 20 samples';
		addLoraSampleFromGeneration.mockRejectedValueOnce(new ApiError(409, detail, '/api/loras/l1'));
		const target = await render();

		target.querySelector<HTMLButtonElement>('.own-takes-toggle')?.click();
		await vi.waitFor(() => expect(target.querySelector('.use-take-btn')).not.toBeNull());
		target.querySelector<HTMLButtonElement>('.use-take-btn')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toBe(detail)
		);
		expect(addToast).toHaveBeenCalledWith(detail, 'error');
	});

	it('uploads an audio file with the entered caption and lyrics', async () => {
		addLoraSample.mockResolvedValueOnce({ id: 's1' });
		refreshLora.mockResolvedValueOnce(lora());
		const target = await render();
		const file = new File(['audio'], 'sample.wav', { type: 'audio/wav' });
		const input = target.querySelector<HTMLInputElement>('input[type="file"]');
		if (!input) throw new Error('Expected sample file input');
		Object.defineProperty(input, 'files', { value: [file] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		const fields = target.querySelectorAll<HTMLTextAreaElement>('.drop-zone textarea');
		const caption = fields[0];
		const lyrics = fields[1];
		if (!caption || !lyrics) throw new Error('Expected sample metadata fields');
		caption.value = 'warm tenor';
		caption.dispatchEvent(new Event('input', { bubbles: true }));
		lyrics.value = 'A line';
		lyrics.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		const button = target.querySelector<HTMLButtonElement>('.add-sample-btn');
		expect(button).not.toBeDisabled();
		button?.click();
		await vi.waitFor(() =>
			expect(addLoraSample).toHaveBeenCalledWith('l1', file, 'warm tenor', 'A line')
		);
	});
});
