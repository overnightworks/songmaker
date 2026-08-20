import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/state', () => ({ page: { params: { slug: 'shared-album' } } }));

import Page from './+page.svelte';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

let component: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	mockFetch.mockReset();
});

describe('shared album recovery', () => {
	it('shows loading during retry and can recover into the album', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });
		const target = document.createElement('div');
		document.body.appendChild(target);
		component = mount(Page, { target });

		await vi.waitFor(() => {
			expect(target.querySelector('h1')?.textContent).toBe('Could not load this album');
		});

		let finishRetry: ((response: unknown) => void) | undefined;
		mockFetch.mockReturnValueOnce(new Promise((resolve) => (finishRetry = resolve)));
		target.querySelector<HTMLButtonElement>('button')?.click();
		await tick();
		expect(target.querySelector('h1')?.textContent).toBe('Loading album');

		finishRetry?.({
			ok: true,
			status: 200,
			json: async () => ({
				title: 'Recovered album',
				artist: 'Artist',
				subtitle: '',
				year: '',
				songs: []
			})
		});
		await vi.waitFor(() => {
			expect(target.querySelector('h1')?.textContent).toBe('Recovered album');
		});
	});
});
