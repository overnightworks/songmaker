import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { ReferenceListRowResponse } from '#lib/api/types.ts';

const mocks = vi.hoisted(() => ({ listReferences: vi.fn(), uploadReference: vi.fn() }));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	uploadReference: (...args: unknown[]) => mocks.uploadReference(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import { listAnswer, referenceRecording } from '#lib/test-utils/references.ts';
import ReferencePicker from './ReferencePicker.svelte';

const onchange = vi.fn();
let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLElement;

async function mountPicker(
	reference: ComponentProps<typeof ReferencePicker>['reference'] = null
): Promise<void> {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ReferencePicker, { target, props: { reference, onchange } });
	await tick();
}

async function openPicker(): Promise<void> {
	target.querySelector<HTMLButtonElement>('.trigger')?.click();
	await vi.waitFor(() => expect(target.querySelector('.choices')).not.toBeNull());
}

async function afterAction(action: () => void): Promise<void> {
	action();
	await tick();
}

function choice(name: string): HTMLInputElement {
	const label = Array.from(target.querySelectorAll('label.fn')).find(
		(candidate) => candidate.textContent === name
	) as HTMLLabelElement;
	return target.querySelector<HTMLInputElement>(
		`#${CSS.escape(label.htmlFor)}`
	) as HTMLInputElement;
}

function previewButton(filename: string): HTMLButtonElement {
	return Array.from(target.querySelectorAll<HTMLButtonElement>('button.face')).find((button) =>
		button.getAttribute('aria-label')?.endsWith(filename)
	) as HTMLButtonElement;
}

function servedReferences(): ReferenceListRowResponse[] {
	return [
		referenceRecording({ id: 'a', filename: 'newest.wav', duration_sec: 42 }),
		referenceRecording({
			id: 'b',
			filename: 'older.mp3',
			duration_sec: 31,
			deletes_at: '2026-11-30T09:00:00Z'
		}),
		referenceRecording({ id: 'c', filename: 'oldest.flac', duration_sec: null })
	];
}

beforeEach(() => {
	vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
	vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
		this: HTMLMediaElement
	) {
		this.dispatchEvent(new Event('pause'));
	});
	vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
	vi.stubEnv('TZ', 'UTC');
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(new Date('2026-11-02T09:00:00Z'));
	onchange.mockReset();
	mocks.listReferences.mockReset().mockResolvedValue(listAnswer(servedReferences()));
	mocks.uploadReference.mockReset();
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	vi.restoreAllMocks();
	audioPlayer.destroy();
	document.body.replaceChildren();
	vi.useRealTimers();
	vi.unstubAllEnvs();
});

describe('reference picker', () => {
	it('shows None closed when nothing is chosen and the chosen name when one is', async () => {
		await mountPicker();
		expect(target.querySelector('.trigger')?.textContent).toContain('None');
		await unmount(mounted as object);
		await mountPicker({ id: 'a', filename: 'storytime-drums.wav' });
		expect(target.querySelector('.trigger')?.textContent).toContain('storytime-drums.wav');
	});

	it('loads nothing until it opens, then lists None, the references in the order served, Upload audio and All references', async () => {
		await mountPicker();
		expect(mocks.listReferences).not.toHaveBeenCalled();
		await openPicker();

		const labels = Array.from(target.querySelectorAll('.choices > li')).map((item) =>
			item.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(labels).toEqual([
			'None',
			'newest.wav 0:42',
			'older.mp3 ⏳ 28d 0:31',
			'oldest.flac',
			'Upload audio',
			'All references'
		]);
	});

	it('marks the chosen reference and sets the draft when another row is chosen', async () => {
		await mountPicker({ id: 'a', filename: 'newest.wav' });
		await openPicker();
		expect(choice('newest.wav').checked).toBe(true);

		await afterAction(() => choice('older.mp3').click());

		expect(onchange).toHaveBeenCalledWith({ id: 'b', filename: 'older.mp3' });
	});

	it('clears the draft with None', async () => {
		await mountPicker({ id: 'a', filename: 'newest.wav' });
		await openPicker();

		await afterAction(() => choice('None').click());

		expect(onchange).toHaveBeenCalledWith(null);
	});

	it('pauses the global player when a preview starts and does not start one by choosing', async () => {
		await mountPicker();
		await openPicker();
		audioPlayer.load(
			{
				generation: makeGeneration({ mp3_path: 'take.mp3' }),
				songId: 's1',
				songTitle: 'Opening Move',
				artist: 'Artist',
				albumTitle: 'Album',
				lyrics: null
			},
			{ autoplay: false }
		);
		audioPlayer.play();
		(audioPlayer.getElement() as HTMLAudioElement).dispatchEvent(new Event('playing'));
		await afterAction(() => choice('older.mp3').click());
		expect(audioPlayer.transport).toBe('playing');

		await afterAction(() => previewButton('older.mp3').click());

		expect(audioPlayer.transport).toBe('paused');
		expect(previewButton('older.mp3').getAttribute('aria-label')).toBe('Pause older.mp3');
	});

	it('stops a preview when the picker closes', async () => {
		await mountPicker();
		await openPicker();
		await afterAction(() => previewButton('newest.wav').click());
		expect(previewButton('newest.wav').getAttribute('aria-label')).toBe('Pause newest.wav');

		await afterAction(() => target.querySelector<HTMLButtonElement>('.trigger')?.click());
		await openPicker();

		expect(previewButton('newest.wav').getAttribute('aria-label')).toBe('Play newest.wav');
	});

	it('uploads from the picker, sets the draft and shows the file in the list', async () => {
		mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'n', filename: 'new.wav' }));
		await mountPicker();
		await openPicker();
		const input = target.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
		Object.defineProperty(input, 'files', { value: [new File(['x'], 'new.wav')] });
		input.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		expect(input.disabled).toBe(true);

		await vi.waitFor(() => expect(onchange).toHaveBeenCalledWith({ id: 'n', filename: 'new.wav' }));
		await vi.waitFor(() => expect(input.disabled).toBe(false));
		expect(mocks.listReferences).toHaveBeenCalledTimes(2);
	});

	it.each([
		{
			failure: 'with no network answer',
			error: new NetworkError('/api/references', new TypeError('Failed to fetch')),
			shown: 'Upload failed'
		},
		{
			failure: 'over the storage quota',
			error: new ApiError(409, 'Reference audio storage limit reached.', '/api/references'),
			shown: 'Reference audio storage limit reached.'
		}
	])('says $shown under the row when the upload fails $failure', async ({ error, shown }) => {
		mocks.uploadReference.mockRejectedValue(error);
		await mountPicker();
		await openPicker();
		const input = target.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
		Object.defineProperty(input, 'files', { value: [new File(['x'], 'new.wav')] });
		input.dispatchEvent(new Event('change', { bubbles: true }));

		await vi.waitFor(() =>
			expect(
				Array.from(target.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim())
			).toEqual([shown])
		);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('names the failure and offers a retry when the list cannot load, with the rest still usable', async () => {
		mocks.listReferences.mockRejectedValueOnce(
			new NetworkError('/api/references', new TypeError('Failed to fetch'))
		);
		await mountPicker({ id: 'x', filename: 'x.wav' });
		target.querySelector<HTMLButtonElement>('.trigger')?.click();
		await vi.waitFor(() => expect(target.querySelector('[role="alert"]')).not.toBeNull());
		expect(target.querySelector('input[type="file"]')).not.toBeNull();
		expect(target.querySelector('a[href="/settings/references"]')).not.toBeNull();
		await afterAction(() => choice('None').click());
		expect(onchange).toHaveBeenCalledWith(null);

		await afterAction(() => target.querySelector<HTMLButtonElement>('.load-error button')?.click());

		await vi.waitFor(() => expect(target.querySelector('label.fn[for]')).not.toBeNull());
		expect(choice('newest.wav')).not.toBeNull();
	});

	it('links All references to the settings page', async () => {
		await mountPicker();
		await openPicker();

		expect(target.querySelector('a[href="/settings/references"]')?.textContent).toContain(
			'All references'
		);
	});
});
