import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ listReferences: vi.fn(), keepReference: vi.fn() }));

vi.mock('#lib/api/references.ts', async (importActual) => ({
	...(await importActual<typeof import('#lib/api/references.ts')>()),
	listReferences: (...args: unknown[]) => mocks.listReferences(...args),
	keepReference: (...args: unknown[]) => mocks.keepReference(...args)
}));
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);

import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { fakePage } from '#lib/test-utils/app-navigation.ts';
import {
	listAnswer,
	listedReferences,
	referenceRecording,
	renderReferencesPage,
	unmountReferencesPage
} from '#lib/test-utils/references.ts';

const HIGHLIGHTED_ROW = '.reference-row.highlighted';

let scrolled: Element[];

beforeEach(() => {
	scrolled = [];
	Element.prototype.scrollIntoView = function (this: Element) {
		scrolled.push(this);
	};
	mocks.listReferences.mockReset();
	mocks.keepReference.mockReset().mockResolvedValue(undefined);
	mocks.listReferences.mockResolvedValue(
		listAnswer([
			referenceRecording({ id: 'a', filename: 'voice-memo.mp3' }),
			referenceRecording({ id: 'b', filename: 'storytime-drums.wav' })
		])
	);
});

afterEach(async () => {
	audioPlayer.destroy();
	await unmountReferencesPage();
	document.body.replaceChildren();
	resetConnectivityForTests();
	fakePage.url = new URL('http://localhost/settings/references');
});

async function openListedPage(query: string): Promise<HTMLElement> {
	fakePage.url = new URL(`http://localhost/settings/references${query}`);
	const target = await renderReferencesPage();
	await vi.waitFor(() => expect(listedReferences(target)).toHaveLength(2));
	return target;
}

function filenameOf(row: Element | null | undefined): string | undefined {
	return row?.querySelector('.reference-name')?.textContent ?? undefined;
}

describe('a references page opened with a reference in its query', () => {
	it('highlights the row it names and scrolls it into view', async () => {
		const target = await openListedPage('?reference=b');

		const highlighted = target.querySelectorAll(HIGHLIGHTED_ROW);
		expect(highlighted).toHaveLength(1);
		expect(filenameOf(highlighted[0])).toBe('storytime-drums.wav');
		expect(scrolled.map(filenameOf)).toEqual(['storytime-drums.wav']);
	});

	it('shows the plain list for a reference the list does not hold', async () => {
		const target = await openListedPage('?reference=gone');

		expect(target.querySelector(HIGHLIGHTED_ROW)).toBeNull();
		expect(target.querySelector('[role="alert"]')).toBeNull();
		expect(scrolled).toEqual([]);
	});

	it('shows the plain list without a query', async () => {
		const target = await openListedPage('');

		expect(target.querySelector(HIGHLIGHTED_ROW)).toBeNull();
		expect(scrolled).toEqual([]);
	});

	it('does not scroll again when the list reloads', async () => {
		const target = await openListedPage('?reference=b');
		target.querySelector<HTMLElement>('.reference-keep')?.click();
		await vi.waitFor(() => expect(mocks.listReferences).toHaveBeenCalledTimes(2));
		await tick();

		expect(scrolled).toHaveLength(1);
	});

	it('keeps the highlight while the row is played', async () => {
		vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
		const target = await openListedPage('?reference=b');

		target.querySelector<HTMLElement>(`${HIGHLIGHTED_ROW} .reference-play`)?.click();

		expect(filenameOf(target.querySelector(HIGHLIGHTED_ROW))).toBe('storytime-drums.wav');
	});
});
