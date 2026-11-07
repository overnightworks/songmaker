import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/fetch.ts';
import {
	REFERENCE_KEEP_FAILED,
	REFERENCE_KEEP_LABEL,
	REFERENCE_UNKEEP_FAILED,
	REFERENCE_UNKEEP_LABEL
} from '#lib/constants.ts';

const mocks = vi.hoisted(() => ({
	listReferences: vi.fn(),
	keepReference: vi.fn(),
	unkeepReference: vi.fn()
}));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	keepReference: (...args: unknown[]) => mocks.keepReference(...args),
	unkeepReference: (...args: unknown[]) => mocks.unkeepReference(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import {
	listAnswer,
	referenceRecording,
	renderReferencesPage,
	unmountReferencesPage
} from '#lib/test-utils/references.ts';

const FILENAME = 'voice-memo.mp3';

function heartOf(target: HTMLElement): HTMLButtonElement {
	return target.querySelector('.reference-row .reference-keep') as HTMLButtonElement;
}

function faultOf(target: HTMLElement): string | undefined {
	return target.querySelector('.reference-fault')?.textContent?.trim();
}

async function renderWith(isKept: boolean): Promise<HTMLElement> {
	mocks.listReferences.mockResolvedValue(
		listAnswer([referenceRecording({ id: 'a', filename: FILENAME, is_kept: isKept })])
	);
	const target = await renderReferencesPage();
	await vi.waitFor(() => expect(heartOf(target)).not.toBeNull());
	return target;
}

beforeEach(() => {
	vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
	vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
	vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
	mocks.listReferences.mockReset();
	mocks.keepReference.mockReset();
	mocks.unkeepReference.mockReset();
});

afterEach(async () => {
	vi.restoreAllMocks();
	audioPlayer.destroy();
	await unmountReferencesPage();
	document.body.replaceChildren();
	resetConnectivityForTests();
});

describe('the reference row heart', () => {
	it('keeps an unkept reference and shows it pressed after the reload', async () => {
		const target = await renderWith(false);
		expect(heartOf(target).getAttribute('aria-label')).toBe(`${REFERENCE_KEEP_LABEL} ${FILENAME}`);
		expect(heartOf(target).getAttribute('aria-pressed')).toBe('false');
		mocks.keepReference.mockResolvedValue(undefined);
		mocks.listReferences.mockResolvedValue(
			listAnswer([referenceRecording({ id: 'a', filename: FILENAME, is_kept: true })])
		);

		heartOf(target).click();
		await tick();

		await vi.waitFor(() => expect(heartOf(target).getAttribute('aria-pressed')).toBe('true'));
		expect(mocks.keepReference).toHaveBeenCalledWith('a');
		expect(heartOf(target).getAttribute('aria-label')).toBe(
			`${REFERENCE_UNKEEP_LABEL} ${FILENAME}`
		);
	});

	it('unkeeps a kept reference and shows it released after the reload', async () => {
		const target = await renderWith(true);
		mocks.unkeepReference.mockResolvedValue(undefined);
		mocks.listReferences.mockResolvedValue(
			listAnswer([referenceRecording({ id: 'a', filename: FILENAME, is_kept: false })])
		);

		heartOf(target).click();
		await tick();

		await vi.waitFor(() => expect(heartOf(target).getAttribute('aria-pressed')).toBe('false'));
		expect(mocks.unkeepReference).toHaveBeenCalledWith('a');
		expect(mocks.keepReference).not.toHaveBeenCalled();
	});

	it.each([
		['keep', false, REFERENCE_KEEP_FAILED, 'keepReference'],
		['unkeep', true, REFERENCE_UNKEEP_FAILED, 'unkeepReference']
	] as const)(
		'shows the row fault and leaves the heart as it was when %s fails',
		async (_action, isKept, sentence, call) => {
			const target = await renderWith(isKept);
			mocks[call].mockRejectedValue(new ApiError(404, '', '/api/references/a'));

			heartOf(target).click();
			await tick();

			await vi.waitFor(() => expect(faultOf(target)).toContain(sentence));
			expect(heartOf(target).getAttribute('aria-pressed')).toBe(String(isKept));
		}
	);

	it('never starts the preview when the heart is pressed', async () => {
		const target = await renderWith(false);
		mocks.keepReference.mockResolvedValue(undefined);

		heartOf(target).click();
		await tick();

		await vi.waitFor(() => expect(mocks.keepReference).toHaveBeenCalled());
		expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
	});
});
