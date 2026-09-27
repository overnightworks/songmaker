import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError } from '$lib/api/fetch';

vi.mock('$lib/api/client', () => ({
	fetchAlbums: vi.fn(),
	createAlbum: vi.fn(),
	createSong: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import { createAlbum, createSong } from '$lib/api/client';
import { addToast } from '$lib/stores/toast';
import { makeAlbum } from '$lib/test-utils/factories';
import CreateForm from './CreateForm.svelte';

const offlineFailure = new NetworkError('/api/x', new TypeError('Failed to fetch'));
const mounted: ReturnType<typeof mount>[] = [];

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	document.body.innerHTML = '';
	vi.clearAllMocks();
});

function renderForm(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(CreateForm, { target, props: { albums: [makeAlbum({ id: 'a1' })] } }));
	return target;
}

function fill(target: HTMLElement, selector: string, value: string): void {
	const field = target.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
	if (!field) throw new Error(`missing ${selector}`);
	field.value = value;
	field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? 'change' : 'input'));
	flushSync();
}

function submitNewAlbum(target: HTMLElement): void {
	fill(target, 'input[placeholder="Album title"]', 'Nachtstrom');
	target.querySelectorAll<HTMLButtonElement>('button')[0].click();
}

function submitNewSong(target: HTMLElement): void {
	fill(target, 'input[placeholder="Song title"]', 'Tide');
	fill(target, 'select', 'a1');
	target.querySelectorAll<HTMLButtonElement>('button')[1].click();
}

describe('CreateForm failures', () => {
	it.each([
		{
			action: 'a new album',
			submit: submitNewAlbum,
			failure: offlineFailure,
			toast: 'Album creation failed'
		},
		{
			action: 'a new album',
			submit: submitNewAlbum,
			failure: new ApiError(409, 'An album with this title exists', '/api/albums'),
			toast: 'An album with this title exists'
		},
		{ action: 'a new song', submit: submitNewSong, failure: offlineFailure, toast: 'Create failed' }
	])('toasts $toast when $action fails', async ({ submit, failure, toast }) => {
		vi.mocked(createAlbum).mockRejectedValue(failure);
		vi.mocked(createSong).mockRejectedValue(failure);

		submit(renderForm());

		await vi.waitFor(() => expect(addToast).toHaveBeenCalledWith(toast, 'error'));
	});
});
