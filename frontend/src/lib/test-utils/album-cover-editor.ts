import { tick } from 'svelte';
import { expect, vi, type Mock } from 'vitest';

import { makeAlbum as album } from '#lib/test-utils/factories.ts';
import { announcedText, getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { requireElement } from '#lib/components/shell/rail-test-fixtures.ts';
import type { CoverSuggestionsResponse, JobItem } from '#lib/api/types.ts';

// What the album cover editor tests share: the editor is reached through the
// album header, so these helpers drive the page as a person does.

export class FakeJobEventSource {
	static readonly sources: FakeJobEventSource[] = [];
	onmessage: ((event: MessageEvent) => void) | null = null;
	onerror: ((event: Event) => void) | null = null;

	constructor(readonly url: string) {
		FakeJobEventSource.sources.push(this);
	}

	close(): void {
		// The fake holds no connection, so there is nothing to release.
	}

	emit(job: JobItem): void {
		this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(job) }));
	}
}

export function coverSuggestions(
	overrides: Partial<CoverSuggestionsResponse> = {}
): CoverSuggestionsResponse {
	return { job: null, suggestions: [], used_today: 0, daily_limit: 10, ...overrides };
}

export function coverJob(overrides: Partial<JobItem> = {}): JobItem {
	return { id: 'cover-job', type: 'cover', status: 'queued', progress: 0, ...overrides };
}

export const ONE_SUGGESTION = { suggestions: [{ id: 'one', url: '/suggestion-one.png' }] };

export const THREE_SUGGESTIONS = {
	suggestions: [
		{ id: 'one', url: '/suggestion-one.png' },
		{ id: 'two', url: '/suggestion-two.png' },
		{ id: 'three', url: '/suggestion-three.png' }
	]
};

/** What a discard names while the editor shows THREE_SUGGESTIONS and follows no run. */
export const THREE_SHOWN = { suggestionIds: ['one', 'two', 'three'], jobIds: [] };

export const COVERED = { card: '/cover-card.jpg', detail: '/cover-detail.jpg' };

export const UPLOADED = { card: '/uploaded-card.jpg', detail: '/uploaded-detail.jpg' };

export function coveredAlbum(cover = COVERED) {
	return album({ id: 'a-local', title: 'Night Drive', cover });
}

export function editor(target: HTMLElement): HTMLElement | null {
	return target.querySelector('.cover-editor');
}

export async function openCoverEditing(target: HTMLElement): Promise<HTMLElement> {
	await vi.waitFor(() => expect(target.querySelector('button.header-cover')).not.toBeNull());
	requireElement<HTMLButtonElement>(target, 'button.header-cover').click();
	await vi.waitFor(() => expect(editor(target)).not.toBeNull());
	return editor(target) as HTMLElement;
}

export async function editingClosed(target: HTMLElement): Promise<void> {
	await vi.waitFor(() => expect(editor(target)).toBeNull());
}

export function countLine(target: HTMLElement): string {
	return (target.querySelector('.cover-count')?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

export function stageText(target: HTMLElement): string {
	return target.querySelector('.cover-stage')?.textContent ?? '';
}

export function stageAnnouncement(target: HTMLElement): string {
	return announcedText(requireElement(target, '.cover-stage [role="status"]'));
}

export function shownImage(target: HTMLElement): string | null {
	return target.querySelector('.cover-stage img')?.getAttribute('src') ?? null;
}

export async function pressSuggestOnceLoaded(target: HTMLElement): Promise<void> {
	await vi.waitFor(() =>
		expect(getByRoleButton(requireElement(target, '.cover-editor'), 'Suggest').disabled).toBe(false)
	);
	pressEditorButton(target, 'Suggest');
}

export function pressEditorButton(target: HTMLElement, name: string): void {
	getByRoleButton(requireElement(target, '.cover-editor'), name).click();
}

export function uploadCoverFile(target: HTMLElement): void {
	const input = requireElement<HTMLInputElement>(target, '.cover-file-input');
	vi.spyOn(input, 'click').mockImplementation(() => undefined);
	pressEditorButton(target, 'Upload');
	const file = new File([new Uint8Array([1])], 'cover.jpg', { type: 'image/jpeg' });
	Object.defineProperty(input, 'files', { configurable: true, value: [file] });
	input.dispatchEvent(new Event('change', { bubbles: true }));
}

export function deferred<T>(): {
	promise: Promise<T>;
	resolve: (value: T | PromiseLike<T>) => void;
	reject: (reason: unknown) => void;
} {
	let resolve!: (value: T | PromiseLike<T>) => void;
	let reject!: (reason: unknown) => void;
	const promise = new Promise<T>((done, fail) => {
		resolve = done;
		reject = fail;
	});
	return { promise, resolve, reject };
}

/**
 * Renders the album page and lets its first cover-state read finish, so a test
 * arranges the answers of the reads that follow, from the editor opening on.
 */
export async function afterPageRead(
	render: () => Promise<HTMLElement>,
	readSuggestions: Mock
): Promise<HTMLElement> {
	const target = await render();
	await vi.waitFor(() => expect(readSuggestions).toHaveBeenCalledTimes(1));
	await tick();
	readSuggestions.mockClear();
	return target;
}
