import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '#lib/constants.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';

const mocks = vi.hoisted(() => ({
	listReferences: vi.fn(),
	uploadReference: vi.fn(),
	deleteReference: vi.fn()
}));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	uploadReference: (...args: unknown[]) => mocks.uploadReference(...args),
	deleteReference: (...args: unknown[]) => mocks.deleteReference(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import {
	chooseFile,
	listAnswer,
	listedReferences,
	renderReferencesPage,
	referenceRecording,
	unmountReferencesPage
} from '#lib/test-utils/references.ts';

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
	return Array.from(target.querySelectorAll('.reference-row .reference-play')).map(
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
	mocks.deleteReference.mockReset();
});

afterEach(async () => {
	vi.restoreAllMocks();
	audioPlayer.destroy();
	await unmountReferencesPage();
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

		it('gives the row no focus stop of its own beside the play button and the menu', async () => {
			const target = await renderTwoReferences();

			for (const row of target.querySelectorAll('.reference-row')) {
				expect(row.hasAttribute('tabindex')).toBe(false);
				expect(row.querySelectorAll('button')).toHaveLength(2);
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

			await unmountReferencesPage();

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

	it('keeps a playing preview and its source through the reload that follows an upload', async () => {
		mocks.uploadReference.mockResolvedValue(referenceRecording({ id: 'new' }));
		mocks.listReferences.mockResolvedValue(listAnswer([referenceRecording({ id: 'a' })]));
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));
		await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
		const preview = referenceElement() as HTMLAudioElement;
		const playingSource = preview.src;
		mocks.listReferences.mockResolvedValue(
			listAnswer([
				referenceRecording({ id: 'new', filename: 'synth-hook.wav' }),
				referenceRecording({ id: 'a' })
			])
		);

		await chooseFile(target, new File(['x'], 'synth-hook.wav', { type: 'audio/wav' }));
		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));

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
});

describe('deleting a reference', () => {
	function rowOf(target: HTMLElement, filename: string): HTMLElement {
		return Array.from(target.querySelectorAll<HTMLElement>('.reference-row')).find((row) =>
			row.textContent?.includes(filename)
		) as HTMLElement;
	}

	function buttonNamed(root: ParentNode, text: string): HTMLButtonElement {
		return Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
			button.textContent?.includes(text)
		) as HTMLButtonElement;
	}

	function menuPanel(): HTMLElement {
		return document.body.querySelector('.menu-panel') as HTMLElement;
	}

	function menuBackdrop(): HTMLElement {
		return document.body.querySelector('.menu-backdrop') as HTMLElement;
	}

	async function openMenuOf(target: HTMLElement, filename: string): Promise<void> {
		await pressReferenceControl(
			rowOf(target, filename).querySelector('[aria-haspopup="dialog"]') as HTMLElement
		);
	}

	async function chooseDelete(target: HTMLElement, filename: string): Promise<void> {
		await openMenuOf(target, filename);
		await pressReferenceControl(buttonNamed(menuPanel(), 'Delete'));
	}

	async function confirmDelete(): Promise<void> {
		const dialog = document.body.querySelector('[role="dialog"][aria-labelledby]') as HTMLElement;
		await pressReferenceControl(buttonNamed(dialog, 'Delete'));
	}

	function faultOf(row: HTMLElement): string | undefined {
		return row.querySelector('.reference-fault')?.textContent?.trim();
	}

	it('asks first, naming the reference and its audio file', async () => {
		const target = await renderTwoReferences();

		await chooseDelete(target, 'voice-memo.mp3');

		const text = document.body.textContent ?? '';
		expect(text).toContain('Delete reference?');
		expect(text).toContain('voice-memo.mp3');
		expect(text).toContain('its audio file');
		expect(text).toContain('This cannot be undone.');
		expect(mocks.deleteReference).not.toHaveBeenCalled();
	});

	it('removes the row and refreshes the usage once the delete is confirmed', async () => {
		const target = await renderTwoReferences();
		mocks.deleteReference.mockResolvedValue(undefined);
		mocks.listReferences.mockResolvedValue(
			listAnswer([referenceRecording({ id: 'b', filename: 'storytime-drums.wav' })], {
				files: 49
			})
		);

		await chooseDelete(target, 'voice-memo.mp3');
		await confirmDelete();

		expect(mocks.deleteReference).toHaveBeenCalledWith('a');
		await vi.waitFor(() =>
			expect(listedReferences(target).map((row) => row.name)).toEqual(['storytime-drums.wav'])
		);
		expect(mocks.listReferences).toHaveBeenCalledTimes(2);
	});

	it('shows the in-use notice on the row and greys Delete when the server refuses with 409', async () => {
		const target = await renderTwoReferences();
		mocks.deleteReference.mockRejectedValue(
			new ApiError(409, 'Reference audio is in use.', '/api/references/a')
		);

		await chooseDelete(target, 'voice-memo.mp3');
		await confirmDelete();

		await vi.waitFor(() =>
			expect(faultOf(rowOf(target, 'voice-memo.mp3'))).toBe('In use — not deleted.')
		);
		expect(faultOf(rowOf(target, 'storytime-drums.wav'))).toBeUndefined();
		await openMenuOf(target, 'voice-memo.mp3');
		expect(buttonNamed(menuPanel(), 'Delete').disabled).toBe(true);
	});

	it('shows another failure in the same row slot and keeps the row', async () => {
		const target = await renderTwoReferences();
		mocks.deleteReference.mockRejectedValue(
			new ApiError(500, 'Reference audio storage could not be checked.', '/api/references/a')
		);

		await chooseDelete(target, 'voice-memo.mp3');
		await confirmDelete();

		await vi.waitFor(() =>
			expect(faultOf(rowOf(target, 'voice-memo.mp3'))).toContain('could not be checked')
		);
		expect(listedReferences(target)).toHaveLength(2);
	});

	it('leaves the Upload button in its normal state through a refused delete', async () => {
		const target = await renderTwoReferences();
		mocks.deleteReference.mockRejectedValue(new ApiError(409, 'in use', '/api/references/a'));

		await chooseDelete(target, 'voice-memo.mp3');
		await confirmDelete();
		await vi.waitFor(() => expect(faultOf(rowOf(target, 'voice-memo.mp3'))).toBeDefined());

		expect(target.querySelector('.upload-button.failed')).toBeNull();
		expect(target.querySelector('.upload-reason')).toBeNull();
	});

	it('does not start or stop the preview when the menu opens, closes or Delete is chosen', async () => {
		const target = await renderTwoReferences();
		await openMenuOf(target, 'voice-memo.mp3');
		await pressReferenceControl(menuBackdrop());
		await chooseDelete(target, 'voice-memo.mp3');

		expect(referenceElement()).toBeUndefined();

		await pressReferenceControl(referencePlayButton(target, 'storytime-drums.wav'));
		await openMenuOf(target, 'storytime-drums.wav');
		await pressReferenceControl(menuBackdrop());

		expect(target.querySelector('.reference-row.playing .reference-name')?.textContent).toBe(
			'storytime-drums.wav'
		);
	});

	it('stops the preview of a reference that is deleted while playing', async () => {
		const target = await renderTwoReferences();
		mocks.deleteReference.mockResolvedValue(undefined);
		mocks.listReferences.mockResolvedValue(
			listAnswer([referenceRecording({ id: 'b', filename: 'storytime-drums.wav' })])
		);
		await pressReferenceControl(referencePlayButton(target, 'voice-memo.mp3'));
		const preview = referenceElement() as HTMLAudioElement;
		expect(target.querySelector('.reference-row.playing')).not.toBeNull();

		await chooseDelete(target, 'voice-memo.mp3');
		await confirmDelete();

		await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(1));
		expect(target.querySelector('.reference-row.playing')).toBeNull();
		expect(preview.getAttribute('src')).toBeNull();
	});
});
