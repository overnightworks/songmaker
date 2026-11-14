import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { ReferenceRecordingResponse, ReferenceUsageResponse } from '#lib/api/types.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { words } from '#lib/words/en.ts';

const mocks = vi.hoisted(() => ({ listReferences: vi.fn(), uploadReference: vi.fn() }));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	uploadReference: (...args: unknown[]) => mocks.uploadReference(...args)
}));

import {
	chooseFile,
	listAnswer,
	listedReferences,
	renderReferencesPage,
	referenceRecording,
	unmountReferencesPage
} from '#lib/test-utils/references.ts';

beforeEach(() => {
	vi.stubEnv('TZ', 'UTC');
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(new Date('2026-11-02T09:00:00Z'));
	mocks.listReferences.mockReset();
	mocks.uploadReference.mockReset();
});

afterEach(async () => {
	vi.restoreAllMocks();
	await unmountReferencesPage();
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllEnvs();
});

describe('references page uploads', () => {
	async function renderReady(usage: Partial<ReferenceUsageResponse> = {}): Promise<HTMLElement> {
		mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({ id: 'a' })], usage));
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));
		return target;
	}

	describe('storage meter', () => {
		const MB = 1_000_000;
		const meterFigures = (target: HTMLElement) =>
			Array.from(target.querySelectorAll('.quota span'), (figure) => figure.textContent);

		it.each([
			{ case: 'files below 80 %', usage: { files: 39 } },
			{ case: 'bytes below 80 %', usage: { bytes: 399 * MB } }
		])('stays away with $case of its limit', async ({ usage }) => {
			const target = await renderReady(usage);

			expect(target.querySelector('.quota')).toBeNull();
		});

		it.each([
			{
				case: 'files',
				usage: { files: 40, bytes: 10 * MB },
				figures: [
					words['referencesPage.filesFigure'](50, { files: '40' }),
					words['referencesPage.sizeFigure']({ used: '10', limit: '500' })
				]
			},
			{
				case: 'bytes',
				usage: { files: 3, bytes: 400 * MB },
				figures: [
					words['referencesPage.filesFigure'](50, { files: '3' }),
					words['referencesPage.sizeFigure']({ used: '400', limit: '500' })
				]
			},
			{
				case: 'a single-file limit',
				usage: { files: 1, file_limit: 1 },
				figures: [
					words['referencesPage.filesFigure'](1, { files: '1' }),
					words['referencesPage.sizeFigure']({ used: '0', limit: '500' })
				]
			}
		])('shows both figures from 80 % of the limit on $case alone', async ({ usage, figures }) => {
			const target = await renderReady(usage);

			expect(meterFigures(target)).toEqual(figures);
			expect(
				target
					.querySelector('.quota')
					?.compareDocumentPosition(target.querySelector('.reference-list') as Element)
			).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
		});

		it('draws no red for a meter below 100 %', async () => {
			const target = await renderReady({ files: 49 });

			expect(target.querySelector('.quota')).not.toBeNull();
			expect(target.querySelector('.upload-button.failed')).toBeNull();
			expect(target.querySelector('.upload-reason')).toBeNull();
		});

		it.each([
			{
				limit: 'files',
				usage: { files: 50 },
				reason: words['referencesPage.storageFullFiles'](50, { files: '50' })
			},
			{
				limit: 'bytes',
				usage: { bytes: 500 * MB },
				reason: words['referencesPage.storageFullSize']({ used: '500', limit: '500' })
			}
		])(
			'says at the button that storage is full at 100 % of $limit, and the button stays pressable',
			async ({ usage, reason }) => {
				const target = await renderReady(usage);

				const button = target.querySelector<HTMLButtonElement>('.upload-button');
				expect(button?.classList.contains('failed')).toBe(true);
				expect(button?.disabled).toBe(false);
				expect(target.querySelector('.upload-reason')?.textContent?.trim()).toBe(reason);
			}
		);
	});

	describe('uploading', () => {
		const NEW_FILE = new File(['x'.repeat(200)], 'synth-hook.wav', { type: 'audio/wav' });

		function uploadButton(target: HTMLElement): HTMLButtonElement {
			return target.querySelector('.upload-button') as HTMLButtonElement;
		}

		async function choose(target: HTMLElement, file = NEW_FILE): Promise<void> {
			await chooseFile(target, file);
		}

		it('offers Upload as one button, for the same file types as the recipe picker', async () => {
			const target = await renderReady();

			expect(uploadButton(target).textContent?.trim()).toBe(words['referencesPage.upload']);
			expect(target.querySelector('input[type="file"]')?.getAttribute('accept')).toBe(
				'.mp3,.wav,.flac,.ogg'
			);
		});

		it('shows the name and the share sent on the button while the file travels', async () => {
			const sent = Promise.withResolvers<ReferenceRecordingResponse>();
			let report: (fraction: number) => void = () => undefined;
			mocks.uploadReference.mockImplementation((_file: File, onProgress: typeof report) => {
				report = onProgress;
				return sent.promise;
			});
			const target = await renderReady();

			await choose(target);
			report(0.64);
			await tick();

			expect(uploadButton(target).textContent?.trim()).toBe(
				`${words['referencesPage.uploadingName']({ name: 'synth-hook.wav' })} · 64%`
			);
			expect(uploadButton(target).style.getPropertyValue('--progress')).toBe('64%');
			expect(uploadButton(target).disabled).toBe(true);
			expect(mocks.uploadReference.mock.calls[0][0]).toBe(NEW_FILE);
		});

		it('puts the new row first and refreshes the meter once the upload is done', async () => {
			mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
			const target = await renderReady();
			expect(target.querySelector('.quota')).toBeNull();
			mocks.listReferences.mockResolvedValue(
				listAnswer(
					[
						referenceRecording({ id: 'new', filename: 'synth-hook.wav' }),
						referenceRecording({ id: 'a' })
					],
					{ files: 41 }
				)
			);

			await choose(target);

			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));
			expect(listedReferences(target)[0].name).toBe('synth-hook.wav');
			expect(target.querySelector('.quota')?.textContent).toContain(
				words['referencesPage.filesFigure'](50, { files: '41' })
			);
			expect(uploadButton(target).textContent?.trim()).toBe(words['referencesPage.upload']);
		});

		const STORAGE_FULL = new ApiError(
			409,
			'Reference audio storage limit reached.',
			'/api/references'
		);

		it.each([
			{
				case: 'the file limit',
				known: { files: 50 },
				reloaded: { files: 50 } as Partial<ReferenceUsageResponse> | null,
				reason: words['referencesPage.storageFullFiles'](50, { files: '50' })
			},
			{
				case: 'the byte limit',
				known: { bytes: 500_000_000 },
				reloaded: { bytes: 500_000_000 } as Partial<ReferenceUsageResponse> | null,
				reason: words['referencesPage.storageFullSize']({ used: '500', limit: '500' })
			},
			{
				case: 'a stale 49 whose reload answers 50',
				known: { files: 49 },
				reloaded: { files: 50 } as Partial<ReferenceUsageResponse> | null,
				reason: words['referencesPage.storageFullFiles'](50, { files: '50' })
			},
			{
				case: 'room left',
				known: { files: 5, bytes: 431_900_000 },
				reloaded: { files: 5, bytes: 431_900_000 } as Partial<ReferenceUsageResponse> | null,
				reason: words['referencesPage.doesNotFit']({ used: '431', limit: '500' })
			},
			{
				case: 'room left when the reload fails',
				known: { files: 5, bytes: 431_900_000 },
				reloaded: null,
				reason: words['referencesPage.doesNotFit']({ used: '431', limit: '500' })
			}
		])(
			'words a 409 from the usage the reload brings back: $case',
			async ({ known, reloaded, reason }) => {
				mocks.uploadReference.mockRejectedValue(STORAGE_FULL);
				const target = await renderReady(known);
				if (reloaded === null) {
					mocks.listReferences.mockRejectedValue(new ApiError(500, 'down', '/api/references'));
				} else {
					mocks.listReferences.mockResolvedValue(
						listAnswer([referenceRecording({ id: 'a' })], reloaded)
					);
				}

				await choose(target);
				await vi.waitFor(() => expect(target.querySelector('.upload-reason')).not.toBeNull());

				expect(target.querySelector('.upload-reason')?.textContent?.trim()).toBe(reason);
				expect(uploadButton(target).classList.contains('failed')).toBe(true);
				expect(listedReferences(target)).toHaveLength(1);
			}
		);

		it('lets a full figure found by a later retry win over a refusal worded from stale usage', async () => {
			mocks.uploadReference.mockRejectedValue(STORAGE_FULL);
			const target = await renderReady({ files: 49 });
			mocks.listReferences.mockRejectedValue(new ApiError(500, 'down', '/api/references'));

			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.load-error')).not.toBeNull());
			mocks.listReferences.mockResolvedValue(
				listAnswer([referenceRecording({ id: 'a' })], { files: 50 })
			);
			(target.querySelector('.retry-btn') as HTMLButtonElement).click();

			await vi.waitFor(() =>
				expect(target.querySelector('.upload-reason')?.textContent?.trim()).toBe(
					words['referencesPage.storageFullFiles'](50, { files: '50' })
				)
			);
		});

		it('offers Upload on an empty list', async () => {
			mocks.listReferences.mockResolvedValue(listAnswer([]));
			const target = await renderReferencesPage();
			await vi.waitFor(() => expect(target.querySelector('.empty')).not.toBeNull());

			expect(uploadButton(target).textContent?.trim()).toBe(words['referencesPage.upload']);
		});

		it('claims the list empty no longer, and keeps Upload, once the reload after a first upload fails', async () => {
			mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
			mocks.listReferences.mockResolvedValue(listAnswer([]));
			const target = await renderReferencesPage();
			await vi.waitFor(() => expect(target.querySelector('.empty')).not.toBeNull());
			mocks.listReferences.mockRejectedValue(new ApiError(500, 'down', '/api/references'));

			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.load-error')).not.toBeNull());

			expect(target.querySelector('.empty')).toBeNull();
			expect(uploadButton(target).textContent?.trim()).toBe(words['referencesPage.upload']);
		});

		it('shows the load failure with its retry beside the kept rows when the reload after a stored upload fails', async () => {
			mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
			const target = await renderReady();
			mocks.listReferences.mockRejectedValue(new ApiError(500, 'down', '/api/references'));

			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.load-error')).not.toBeNull());

			expect(target.querySelector('.load-error')?.textContent).toContain(
				words['referencesPage.loadFailed']
			);
			expect(target.querySelector('.retry-btn')).not.toBeNull();
			expect(listedReferences(target).map((row) => row.name)).toEqual(['voice-memo.mp3']);

			mocks.listReferences.mockResolvedValue(
				listAnswer([
					referenceRecording({ id: 'new', filename: 'synth-hook.wav' }),
					referenceRecording({ id: 'a' })
				])
			);
			(target.querySelector('.retry-btn') as HTMLButtonElement).click();
			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));
			expect(target.querySelector('.load-error')).toBeNull();
		});

		it('clears the file input after a choice, so the same file can be chosen again', async () => {
			mocks.uploadReference.mockReturnValue(new Promise(() => {}));
			const target = await renderReady();
			const input = target.querySelector<HTMLInputElement>(
				'input[type="file"]'
			) as HTMLInputElement;
			const assigned: string[] = [];
			Object.defineProperty(input, 'value', {
				get: () => assigned.at(-1) ?? '',
				set: (value: string) => assigned.push(value),
				configurable: true
			});

			await choose(target);

			expect(assigned.at(-1)).toBe('');
		});

		it.each([
			{
				case: "the server's detail",
				error: new ApiError(400, 'Unsupported format', '/api/references'),
				reason: 'Unsupported format'
			},
			{
				case: 'the page words of the key a refusal names',
				error: new ApiError(400, 'Unsupported format', '/api/references', null, '', null, null, {
					key: 'referenceRefusal.formatUnsupported',
					values: { extension: '.exe', accepted: '.mp3' }
				}),
				reason: words['referenceRefusal.formatUnsupported']({ extension: '.exe', accepted: '.mp3' })
			},
			{
				case: 'the fallback for a server without detail',
				error: new ApiError(500, '', '/api/references'),
				reason: words['referencesPage.uploadFailed']
			},
			{
				case: 'the fallback for a lost connection',
				error: new NetworkError('/api/references', new TypeError('x')),
				reason: words['referencesPage.uploadFailed']
			}
		])(
			'stands at the button with $case when the upload fails, and the list stays',
			async ({ error, reason }) => {
				mocks.uploadReference.mockRejectedValue(error);
				const target = await renderReady();

				await choose(target);
				await vi.waitFor(() => expect(target.querySelector('.upload-reason')).not.toBeNull());

				expect(target.querySelector('.upload-reason')?.textContent?.trim()).toBe(reason);
				expect(uploadButton(target).classList.contains('failed')).toBe(true);
				expect(listedReferences(target).map((row) => row.name)).toEqual(['voice-memo.mp3']);
			}
		);

		it.each([
			{
				case: 'the detail of a 400',
				error: new ApiError(400, 'File too large', '/api/references'),
				reason: 'File too large'
			},
			{
				case: 'the detail of a 500',
				error: new ApiError(500, 'Disk error', '/api/references'),
				reason: 'Disk error'
			},
			{
				case: 'the fallback for a lost connection',
				error: new NetworkError('/api/references', new TypeError('x')),
				reason: words['referencesPage.uploadFailed']
			}
		])(
			'shows $case at the button, not the full reason, when the upload fails at 50 of 50 files',
			async ({ error, reason }) => {
				mocks.uploadReference.mockRejectedValue(error);
				const target = await renderReady({ files: 50 });

				await choose(target);
				await vi.waitFor(() =>
					expect(target.querySelector('.upload-reason')?.textContent?.trim()).toBe(reason)
				);
			}
		);

		it('clears an earlier failure once the next upload is stored', async () => {
			mocks.uploadReference.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/references'));
			const target = await renderReady();
			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.upload-reason')).not.toBeNull());

			mocks.uploadReference.mockResolvedValue(
				referenceRecording({ id: 'new', filename: 'synth-hook.wav' })
			);
			mocks.listReferences.mockResolvedValue(
				listAnswer([
					referenceRecording({ id: 'new', filename: 'synth-hook.wav' }),
					referenceRecording({ id: 'a' })
				])
			);
			await choose(target);
			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));

			expect(target.querySelector('.upload-reason')).toBeNull();
			expect(uploadButton(target).classList.contains('failed')).toBe(false);
		});
	});
});
