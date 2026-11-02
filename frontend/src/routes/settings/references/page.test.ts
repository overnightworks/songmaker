import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { ReferenceRecordingResponse, ReferenceUsageResponse } from '#lib/api/types.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';

const mocks = vi.hoisted(() => ({ listReferences: vi.fn(), uploadReference: vi.fn() }));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	uploadReference: (...args: unknown[]) => mocks.uploadReference(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import ReferencesPage from './+page.svelte';

let mounted: ReturnType<typeof mount> | undefined;

function referenceRecording(
	overrides: Partial<ReferenceRecordingResponse>
): ReferenceRecordingResponse {
	return {
		id: 'reference-1',
		filename: 'voice-memo.mp3',
		size_bytes: 1000,
		duration_sec: 31.4,
		created_at: '2026-10-27T10:00:00Z',
		...overrides
	};
}

function listAnswer(
	references: ReferenceRecordingResponse[],
	usage: Partial<ReferenceUsageResponse> = {}
) {
	return {
		references,
		usage: { files: references.length, bytes: 0, file_limit: 50, byte_limit: 500_000_000, ...usage }
	};
}

async function renderReferencesPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(ReferencesPage, { target });
	await tick();
	return target;
}

function listedReferences(target: HTMLElement): { name: string; meta: string }[] {
	return Array.from(target.querySelectorAll('.reference-row')).map((row) => ({
		name: row.querySelector('.reference-name')?.textContent ?? '',
		meta: row.querySelector('.reference-meta')?.textContent ?? ''
	}));
}

let playSpy: MockInstance<HTMLMediaElement['play']>;
let playOutcome: Promise<void>;

function referenceElement(): HTMLAudioElement | undefined {
	return playSpy.mock.contexts.find((element: unknown) =>
		(element as HTMLAudioElement).src.includes('/api/references/')
	) as HTMLAudioElement | undefined;
}

function referencePlayButton(target: HTMLElement, filename: string): HTMLButtonElement {
	const row = Array.from(target.querySelectorAll('.reference-row')).find((candidate) =>
		candidate.textContent?.includes(filename)
	);
	return row?.querySelector('button') as HTMLButtonElement;
}

function referenceButtonLabels(target: HTMLElement): string[] {
	return Array.from(target.querySelectorAll('.reference-row button')).map(
		(button) => button.getAttribute('aria-label') ?? ''
	);
}

async function renderTwoReferences(): Promise<HTMLElement> {
	mocks.listReferences.mockResolvedValue(
		listAnswer([
			referenceRecording({ id: 'a', filename: 'voice-memo.mp3' }),
			referenceRecording({ id: 'b', filename: 'storytime-drums.wav' })
		])
	);
	const target = await renderReferencesPage();
	await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));
	return target;
}

async function pressReferenceControl(button: Element): Promise<void> {
	(button as HTMLElement).click();
	await tick();
}

beforeEach(() => {
	playOutcome = Promise.resolve();
	playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => playOutcome);
	vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
		this: HTMLMediaElement
	) {
		this.dispatchEvent(new Event('pause'));
	});
	vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
	vi.stubEnv('TZ', 'UTC');
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(new Date('2026-11-02T09:00:00Z'));
	mocks.listReferences.mockReset();
	mocks.uploadReference.mockReset();
});

afterEach(async () => {
	vi.restoreAllMocks();
	audioPlayer.destroy();
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	resetConnectivityForTests();
	vi.useRealTimers();
	vi.unstubAllEnvs();
});

describe('references page', () => {
	it('lists each reference with its filename, length and upload day, in the order served', async () => {
		mocks.listReferences.mockResolvedValue(
			listAnswer([
				referenceRecording({ id: 'a', filename: 'voice-memo.mp3', duration_sec: 31.4 }),
				referenceRecording({
					id: 'b',
					filename: 'storytime-drums.wav',
					duration_sec: 62,
					created_at: '2026-10-14T08:00:00Z'
				})
			])
		);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));

		expect(listedReferences(target)).toEqual([
			{ name: 'voice-memo.mp3', meta: '0:31 · 27 Oct' },
			{ name: 'storytime-drums.wav', meta: '1:02 · 14 Oct' }
		]);
	});

	it('titles the page References', async () => {
		mocks.listReferences.mockReturnValue(new Promise(() => {}));
		const target = await renderReferencesPage();

		expect(target.querySelector('h1')?.textContent).toBe('References');
	});

	it('shows a dash for a reference whose length is unknown', async () => {
		mocks.listReferences.mockResolvedValue(
			listAnswer([referenceRecording({ duration_sec: null })])
		);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));

		expect(listedReferences(target)[0].meta).toBe('— · 27 Oct');
	});

	it('shows skeleton rows with the loading caption until the read answers', async () => {
		mocks.listReferences.mockReturnValue(new Promise(() => {}));
		const target = await renderReferencesPage();

		const status = target.querySelector('[role="status"]');
		expect(status?.textContent?.trim()).toBe('Loading references…');
		expect(status?.querySelectorAll('.skeleton-row').length).toBeGreaterThan(0);
		expect(target.querySelector('.empty')).toBeNull();
	});

	it('says what references are for once the read answered with none', async () => {
		mocks.listReferences.mockResolvedValue(listAnswer([]));
		const target = await renderReferencesPage();

		await vi.waitFor(() =>
			expect(target.querySelector('.empty')?.textContent?.trim()).toBe(
				"No references yet — upload a recording to guide a song's sound."
			)
		);
		expect(target.querySelector('[role="status"]')).toBeNull();
	});

	it('names a refused read with the fixed sentence, not the server text, and claims no empty list', async () => {
		mocks.listReferences.mockRejectedValue(new ApiError(500, 'boom', '/api/references'));
		const target = await renderReferencesPage();

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
				'Failed to load references'
			)
		);
		expect(target.textContent).not.toContain('boom');
		expect(target.querySelector('.empty')).toBeNull();
	});

	it('reloads on "Try again", stays usable after a failed retry and lists once the read answers', async () => {
		mocks.listReferences.mockRejectedValue(new ApiError(500, 'boom', '/api/references'));
		const target = await renderReferencesPage();
		const retry = () => target.querySelector<HTMLButtonElement>('button[aria-label="Try again"]');
		const clickRetry = () => retry()?.click();
		await vi.waitFor(() => expect(retry()).not.toBeNull());

		let refuseRetry: (reason: Error) => void = () => {};
		mocks.listReferences.mockReturnValueOnce(
			new Promise((_, reject) => {
				refuseRetry = reject;
			})
		);
		clickRetry();
		await tick();
		expect(target.querySelector('[role="status"]')).not.toBeNull();
		expect(target.querySelector('[role="alert"]')).toBeNull();

		refuseRetry(new ApiError(500, 'boom', '/api/references'));
		await vi.waitFor(() => expect(retry()).not.toBeNull());

		mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({})]));
		clickRetry();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));

		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('names the failed read when the server stays unreachable, then lists once back online', async () => {
		vi.useFakeTimers();
		mocks.listReferences.mockRejectedValue(
			new NetworkError('/api/references', new TypeError('Failed to fetch'))
		);
		const target = await renderReferencesPage();
		for (const delay of UNREACHABLE_RELOAD_DELAYS_MS) await vi.advanceTimersByTimeAsync(delay);

		expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			'Failed to load references'
		);
		expect(target.querySelector('.empty')).toBeNull();

		mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({})]));
		reportResourceStreamReachable(false);
		reportResourceStreamReachable(true);
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));

		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	describe('playing a reference', () => {
		it('plays a reference from its button and pauses it from the same button', async () => {
			const target = await renderTwoReferences();

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(referenceElement()?.src).toMatch(/\/api\/references\/a\/audio$/);
			expect(referenceButtonLabels(target)).toEqual([
				'Pause voice-memo.mp3',
				'Play storytime-drums.wav'
			]);
			expect(target.querySelector('.reference-row.playing .reference-name')?.textContent).toBe(
				'voice-memo.mp3'
			);

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(referenceButtonLabels(target)).toEqual([
				'Play voice-memo.mp3',
				'Play storytime-drums.wav'
			]);
			expect(target.querySelector('.reference-row.playing')).toBeNull();
		});

		it('plays a reference when its row is tapped, and a button press does not toggle twice', async () => {
			const target = await renderTwoReferences();
			const row = target.querySelectorAll('.reference-row')[1];

			await pressReferenceControl(row);
			expect(referenceButtonLabels(target)).toEqual([
				'Play voice-memo.mp3',
				'Pause storytime-drums.wav'
			]);
			await pressReferenceControl(row);
			expect(referenceButtonLabels(target)).toEqual([
				'Play voice-memo.mp3',
				'Play storytime-drums.wav'
			]);

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(referenceButtonLabels(target)).toEqual([
				'Pause voice-memo.mp3',
				'Play storytime-drums.wav'
			]);
			expect(playSpy).toHaveBeenCalledTimes(2);
		});

		it('gives the row no focus stop of its own beside the play button', async () => {
			const target = await renderTwoReferences();

			for (const row of target.querySelectorAll('.reference-row')) {
				expect(row.hasAttribute('tabindex')).toBe(false);
				expect(row.querySelectorAll('button')).toHaveLength(1);
			}
		});

		it('stops the first reference when a second one starts', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			await pressReferenceControl(referencePlayButton(target, 'storytime-drums.wav'));

			expect(referenceButtonLabels(target)).toEqual([
				'Play voice-memo.mp3',
				'Pause storytime-drums.wav'
			]);
			expect(referenceElement()?.src).toMatch(/\/api\/references\/b\/audio$/);
			expect(target.querySelectorAll('.reference-row.playing')).toHaveLength(1);
		});

		it('resets the row when the recording ends', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			referenceElement()?.dispatchEvent(new Event('ended'));
			await tick();

			expect(referenceButtonLabels(target)[0]).toBe('Play voice-memo.mp3');
			expect(target.querySelector('.reference-row.playing')).toBeNull();
		});

		it('resets the row and says it cannot play when the file fails to load', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			referenceElement()?.dispatchEvent(new Event('error'));
			await tick();

			const rows = target.querySelectorAll('.reference-row');
			expect(referenceButtonLabels(target)[0]).toBe('Play voice-memo.mp3');
			expect(rows[0].textContent).toContain("Can't play this recording");
			expect(rows[1].textContent).not.toContain("Can't play this recording");
		});

		it('resets the row and says it cannot play when the browser refuses to start it', async () => {
			playOutcome = Promise.reject(new DOMException('refused', 'NotSupportedError'));
			playOutcome.catch(() => {});
			const target = await renderTwoReferences();

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			await vi.waitFor(() =>
				expect(target.querySelector('.reference-row')?.textContent).toContain(
					"Can't play this recording"
				)
			);

			expect(referenceButtonLabels(target)[0]).toBe('Play voice-memo.mp3');
		});

		it('loads the source again when a failed row is tried again', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			referenceElement()?.dispatchEvent(new Event('error'));
			await tick();
			const sourceSet = vi.spyOn(HTMLMediaElement.prototype, 'src', 'set');

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(sourceSet).toHaveBeenCalledWith(expect.stringMatching(/\/api\/references\/a\/audio$/));
			expect(target.textContent).not.toContain("Can't play this recording");
			expect(referenceButtonLabels(target)[0]).toBe('Pause voice-memo.mp3');
		});

		it('loads the source again when a load fails after the person paused', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			referenceElement()?.dispatchEvent(new Event('error'));
			await tick();
			const sourceSet = vi.spyOn(HTMLMediaElement.prototype, 'src', 'set');

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(sourceSet).toHaveBeenCalledWith(expect.stringMatching(/\/api\/references\/a\/audio$/));
			expect(referenceButtonLabels(target)[0]).toBe('Pause voice-memo.mp3');
		});

		it('keeps the new row loaded when the play of the row before it is rejected late', async () => {
			const target = await renderTwoReferences();
			let rejectFirstPlay: (reason: Error) => void = () => {};
			playSpy.mockImplementationOnce(
				() => new Promise<void>((_resolve, reject) => (rejectFirstPlay = reject))
			);
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			await pressReferenceControl(referencePlayButton(target, 'storytime-drums.wav'));
			rejectFirstPlay(new DOMException('interrupted by a new load', 'AbortError'));
			await tick();
			const sourceSet = vi.spyOn(HTMLMediaElement.prototype, 'src', 'set');

			await pressReferenceControl(referencePlayButton(target, 'storytime-drums.wav'));
			await pressReferenceControl(referencePlayButton(target, 'storytime-drums.wav'));

			expect(sourceSet).not.toHaveBeenCalled();
			expect(referenceButtonLabels(target)[1]).toBe('Pause storytime-drums.wav');
		});

		it('stops the sound when the person leaves the page', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			const element = referenceElement() as HTMLAudioElement;
			const stopped = vi.fn();
			element.addEventListener('pause', stopped);

			await unmount(mounted as ReturnType<typeof mount>);
			mounted = undefined;

			expect(stopped).toHaveBeenCalled();
			expect(element.getAttribute('src')).toBeNull();
		});
	});

	describe('beside the global player', () => {
		function startGlobalPlayer(): HTMLAudioElement {
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
			const element = audioPlayer.getElement() as HTMLAudioElement;
			audioPlayer.play();
			element.dispatchEvent(new Event('playing'));
			return element;
		}

		it('pauses the global player when a reference starts', async () => {
			const target = await renderTwoReferences();
			startGlobalPlayer();
			expect(audioPlayer.transport).toBe('playing');

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			expect(audioPlayer.transport).toBe('paused');
			expect(referenceButtonLabels(target)[0]).toBe('Pause voice-memo.mp3');
		});

		it('stops the reference when the global player starts', async () => {
			const target = await renderTwoReferences();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));

			startGlobalPlayer();
			await tick();

			expect(referenceButtonLabels(target)[0]).toBe('Play voice-memo.mp3');
			expect(target.querySelector('.reference-row.playing')).toBeNull();
		});
	});

	describe('storage meter', () => {
		const MB = 1_000_000;
		const meterFigures = (target: HTMLElement) =>
			Array.from(target.querySelectorAll('.quota span'), (figure) => figure.textContent);

		async function renderWithUsage(usage: Partial<ReferenceUsageResponse>): Promise<HTMLElement> {
			mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({})], usage));
			const target = await renderReferencesPage();
			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));
			return target;
		}

		it.each([
			{ case: 'files below 80 %', usage: { files: 39 } },
			{ case: 'bytes below 80 %', usage: { bytes: 399 * MB } }
		])('stays away with $case of its limit', async ({ usage }) => {
			const target = await renderWithUsage(usage);

			expect(target.querySelector('.quota')).toBeNull();
		});

		it.each([
			{
				case: 'files',
				usage: { files: 40, bytes: 10 * MB },
				figures: ['40 of 50 files', '10 of 500 MB']
			},
			{
				case: 'bytes',
				usage: { files: 3, bytes: 400 * MB },
				figures: ['3 of 50 files', '400 of 500 MB']
			}
		])('shows both figures from 80 % of the limit on $case alone', async ({ usage, figures }) => {
			const target = await renderWithUsage(usage);

			expect(meterFigures(target)).toEqual(figures);
			expect(
				target
					.querySelector('.quota')
					?.compareDocumentPosition(target.querySelector('.reference-list') as Element)
			).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
		});

		it('draws no red for a meter below 100 %', async () => {
			const target = await renderWithUsage({ files: 49 });

			expect(target.querySelector('.quota')).not.toBeNull();
			expect(target.querySelector('.upload-button.failed')).toBeNull();
			expect(target.querySelector('.upload-reason')).toBeNull();
		});

		it.each([
			{
				limit: 'files',
				usage: { files: 50 },
				reason: 'Reference storage is full (50 of 50 files) — delete one first.'
			},
			{
				limit: 'bytes',
				usage: { bytes: 500 * MB },
				reason: 'Reference storage is full (500 of 500 MB) — delete one first.'
			}
		])(
			'says at the button that storage is full at 100 % of $limit, and the button stays pressable',
			async ({ usage, reason }) => {
				const target = await renderWithUsage(usage);

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
			const input = target.querySelector<HTMLInputElement>(
				'input[type="file"]'
			) as HTMLInputElement;
			Object.defineProperty(input, 'files', { value: [file], configurable: true });
			input.dispatchEvent(new Event('change', { bubbles: true }));
			await tick();
		}

		async function renderReady(usage: Partial<ReferenceUsageResponse> = {}): Promise<HTMLElement> {
			mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({ id: 'a' })], usage));
			const target = await renderReferencesPage();
			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));
			return target;
		}

		it('offers Upload as one button, for the same file types as the recipe picker', async () => {
			const target = await renderReady();

			expect(uploadButton(target).textContent?.trim()).toBe('Upload');
			expect(target.querySelector('input[type="file"]')?.getAttribute('accept')).toBe(
				'.mp3,.wav,.flac,.ogg'
			);
		});

		it('offers Upload on an empty list too', async () => {
			mocks.listReferences.mockResolvedValue(listAnswer([]));
			const target = await renderReferencesPage();
			await vi.waitFor(() => expect(target.querySelector('.empty')).not.toBeNull());

			expect(uploadButton(target).textContent?.trim()).toBe('Upload');
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

			expect(uploadButton(target).textContent?.trim()).toBe('Uploading synth-hook.wav · 64%');
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
			expect(target.querySelector('.quota')?.textContent).toContain('41 of 50 files');
			expect(uploadButton(target).textContent?.trim()).toBe('Upload');
		});

		it('keeps a playing preview and its source through the reload that follows an upload', async () => {
			mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
			const target = await renderReady();
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			const preview = referenceElement() as HTMLAudioElement;
			const playingSource = preview.src;
			const pauses = vi.mocked(HTMLMediaElement.prototype.pause).mock.calls.length;
			mocks.listReferences.mockResolvedValue(
				listAnswer([
					referenceRecording({ id: 'new', filename: 'synth-hook.wav' }),
					referenceRecording({ id: 'a' })
				])
			);

			await choose(target);
			await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));

			expect(vi.mocked(HTMLMediaElement.prototype.pause).mock.calls.length).toBe(pauses);
			expect(target.querySelector('.reference-row.playing .reference-name')?.textContent).toBe(
				'voice-memo.mp3'
			);
			expect(preview.src).toBe(playingSource);

			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
			expect(preview.src).toBe(playingSource);

			await pressReferenceControl(referencePlayButton(target, 'synth-hook.wav'));
			expect(preview.src).toMatch(/\/api\/references\/new\/audio$/);
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
				reason: 'Reference storage is full (50 of 50 files) — delete one first.'
			},
			{
				case: 'the byte limit',
				known: { bytes: 500_000_000 },
				reloaded: { bytes: 500_000_000 } as Partial<ReferenceUsageResponse> | null,
				reason: 'Reference storage is full (500 of 500 MB) — delete one first.'
			},
			{
				case: 'a stale 49 whose reload answers 50',
				known: { files: 49 },
				reloaded: { files: 50 } as Partial<ReferenceUsageResponse> | null,
				reason: 'Reference storage is full (50 of 50 files) — delete one first.'
			},
			{
				case: 'room left',
				known: { files: 5, bytes: 431_900_000 },
				reloaded: { files: 5, bytes: 431_900_000 } as Partial<ReferenceUsageResponse> | null,
				reason: "That file doesn't fit (431 of 500 MB used) — delete one first."
			},
			{
				case: 'room left when the reload fails',
				known: { files: 5, bytes: 431_900_000 },
				reloaded: null,
				reason: "That file doesn't fit (431 of 500 MB used) — delete one first."
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

		it('shows the load failure with its retry beside the kept rows when the reload after a stored upload fails', async () => {
			mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
			const target = await renderReady();
			mocks.listReferences.mockRejectedValue(new ApiError(500, 'down', '/api/references'));

			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.load-error')).not.toBeNull());

			expect(target.querySelector('.load-error')?.textContent).toContain(
				'Failed to load references'
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
				case: 'the fallback for a server without detail',
				error: new ApiError(500, '', '/api/references'),
				reason: "Couldn't upload this file"
			},
			{
				case: 'the fallback for a lost connection',
				error: new NetworkError('/api/references', new TypeError('x')),
				reason: "Couldn't upload this file"
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

		it('clears an earlier failure when the next upload starts', async () => {
			mocks.uploadReference.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/references'));
			const target = await renderReady();
			await choose(target);
			await vi.waitFor(() => expect(target.querySelector('.upload-reason')).not.toBeNull());

			mocks.uploadReference.mockReturnValue(new Promise(() => {}));
			await choose(target);

			expect(target.querySelector('.upload-reason')).toBeNull();
			expect(uploadButton(target).classList.contains('failed')).toBe(false);
		});
	});
});
