import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/fetch.ts';

const mocks = vi.hoisted(() => ({
	listReferences: vi.fn(),
	acknowledgeCountdown: vi.fn(),
	keepReference: vi.fn()
}));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	acknowledgeCountdown: (...args: unknown[]) => mocks.acknowledgeCountdown(...args),
	keepReference: (...args: unknown[]) => mocks.keepReference(...args)
}));

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import {
	listAnswer,
	referenceRecording,
	renderReferencesPage,
	unmountReferencesPage
} from '#lib/test-utils/references.ts';

const NOW = new Date('2026-11-08T12:00:00Z');
const EPOCH = 'epoch-1';

function deletesInDays(days: number): string {
	return new Date(NOW.getTime() + days * 86_400_000).toISOString();
}

function answerWith(rows: Parameters<typeof referenceRecording>[0][], epoch: string | null) {
	return { ...listAnswer(rows.map((row) => referenceRecording(row))), countdown_epoch: epoch };
}

function badgeOf(target: HTMLElement): HTMLElement | null {
	return target.querySelector('.reference-meta .exp');
}

async function settle(): Promise<void> {
	await tick();
	await tick();
}

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(NOW);
	mocks.listReferences.mockReset();
	mocks.acknowledgeCountdown.mockReset();
	mocks.acknowledgeCountdown.mockResolvedValue(undefined);
	mocks.keepReference.mockReset();
	mocks.keepReference.mockResolvedValue(undefined);
});

afterEach(async () => {
	vi.useRealTimers();
	vi.restoreAllMocks();
	audioPlayer.destroy();
	await unmountReferencesPage();
	document.body.replaceChildren();
	resetConnectivityForTests();
});

describe('the reference row countdown', () => {
	it('shows a grey countdown after the date with the day it deletes in the tooltip', async () => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);

		const target = await renderReferencesPage();

		await vi.waitFor(() => expect(badgeOf(target)).not.toBeNull());
		const badge = badgeOf(target) as HTMLElement;
		expect(badge.textContent?.trim()).toBe('⏳ 10d');
		expect(badge.title).toBe('Deleted on 18 Nov — keep to preserve');
		expect(badge.classList.contains('warn')).toBe(false);
		const meta = badge.closest('.reference-meta') as HTMLElement;
		expect(meta.textContent?.indexOf('27 Oct')).toBeLessThan(meta.textContent?.indexOf('⏳') ?? -1);
	});

	it.each([
		[3, true],
		[4, false],
		[0, true]
	])('marks a countdown of %i days as amber: %s', async (days, amber) => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(days) }], EPOCH)
		);

		const target = await renderReferencesPage();

		await vi.waitFor(() => expect(badgeOf(target)).not.toBeNull());
		expect(badgeOf(target)?.classList.contains('warn')).toBe(amber);
	});

	it('reads 0d for a date already past', async () => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(-2) }], EPOCH)
		);

		const target = await renderReferencesPage();

		await vi.waitFor(() => expect(badgeOf(target)?.textContent?.trim()).toBe('⏳ 0d'));
	});

	it('shows no countdown when the row has no deletion date', async () => {
		mocks.listReferences.mockResolvedValue(answerWith([{ id: 'a', deletes_at: null }], null));

		const target = await renderReferencesPage();

		await vi.waitFor(() => expect(target.querySelector('.reference-row')).not.toBeNull());
		expect(badgeOf(target)).toBeNull();
	});
});

describe('the countdown acknowledgement', () => {
	it('posts the epoch once, only after the countdown is on screen', async () => {
		const shownAtPost: (boolean | undefined)[] = [];
		mocks.acknowledgeCountdown.mockImplementation(async () => {
			shownAtPost.push(document.querySelector('.reference-meta .exp') !== null);
		});
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);

		await renderReferencesPage();

		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledWith(EPOCH));
		expect(shownAtPost).toEqual([true]);
	});

	it('posts once per page load however often the list reloads', async () => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(1));

		(target.querySelector('.reference-keep') as HTMLButtonElement).click();
		await vi.waitFor(() => expect(mocks.keepReference).toHaveBeenCalled());
		await settle();

		expect(mocks.listReferences.mock.calls.length).toBeGreaterThan(1);
		expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(1);
	});

	it.each([
		['a null epoch', () => answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], null)],
		['an empty list', () => answerWith([], EPOCH)],
		['no row with a deletion date', () => answerWith([{ id: 'a', deletes_at: null }], EPOCH)]
	])('posts nothing for %s', async (_name, answer) => {
		mocks.listReferences.mockResolvedValue(answer());

		await renderReferencesPage();
		await settle();

		expect(mocks.acknowledgeCountdown).not.toHaveBeenCalled();
	});

	it('posts nothing when the load failed', async () => {
		mocks.listReferences.mockRejectedValue(new ApiError(500, '', '/api/references'));

		await renderReferencesPage();
		await settle();

		expect(mocks.acknowledgeCountdown).not.toHaveBeenCalled();
	});

	it('changes nothing visible when the post fails', async () => {
		mocks.acknowledgeCountdown.mockRejectedValue(
			new ApiError(409, '', '/api/references/countdown-shown')
		);
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);

		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalled());
		await settle();

		expect(badgeOf(target)?.textContent?.trim()).toBe('⏳ 10d');
		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('posts on a later load of the same page load when the first showed no countdown', async () => {
		mocks.listReferences.mockResolvedValueOnce(answerWith([{ id: 'a', deletes_at: null }], null));
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(target.querySelector('.reference-keep')).not.toBeNull());
		await settle();
		expect(mocks.acknowledgeCountdown).not.toHaveBeenCalled();
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);

		(target.querySelector('.reference-keep') as HTMLButtonElement).click();

		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledWith(EPOCH));
		expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(1);
	});

	it('posts nothing when the page is left before the list answers', async () => {
		let answer: (value: ReturnType<typeof answerWith>) => void = () => undefined;
		mocks.listReferences.mockReturnValue(new Promise((resolve) => (answer = resolve)));
		await renderReferencesPage();
		await unmountReferencesPage();

		answer(answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH));
		await settle();

		expect(mocks.acknowledgeCountdown).not.toHaveBeenCalled();
	});

	it('posts again when the page is left and opened anew', async () => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);
		await renderReferencesPage();
		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(1));
		await unmountReferencesPage();

		await renderReferencesPage();

		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(2));
	});

	it('posts on the next page load after a failed post', async () => {
		mocks.acknowledgeCountdown.mockRejectedValueOnce(
			new ApiError(500, '', '/api/references/countdown-shown')
		);
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);
		await renderReferencesPage();
		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(1));
		await settle();
		await unmountReferencesPage();

		await renderReferencesPage();

		await vi.waitFor(() => expect(mocks.acknowledgeCountdown).toHaveBeenCalledTimes(2));
	});
});

describe('the countdown clock', () => {
	it('counts from the time of the latest load', async () => {
		mocks.listReferences.mockResolvedValue(
			answerWith([{ id: 'a', deletes_at: deletesInDays(10) }], EPOCH)
		);
		const target = await renderReferencesPage();
		await vi.waitFor(() => expect(badgeOf(target)?.textContent?.trim()).toBe('⏳ 10d'));
		vi.setSystemTime(new Date(NOW.getTime() + 2 * 86_400_000));

		(target.querySelector('.reference-keep') as HTMLButtonElement).click();

		await vi.waitFor(() => expect(badgeOf(target)?.textContent?.trim()).toBe('⏳ 8d'));
	});
});
