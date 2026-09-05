import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/fetch';

const mocks = vi.hoisted(() => ({
	loadLoras: vi.fn(),
	createLora: vi.fn(),
	softDeleteLora: vi.fn()
}));

vi.mock('$lib/stores/loras', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/loras')>();
	return {
		...actual,
		loadLoras: (...args: unknown[]) => mocks.loadLoras(...args),
		createLora: (...args: unknown[]) => mocks.createLora(...args),
		softDeleteLora: (...args: unknown[]) => mocks.softDeleteLora(...args)
	};
});

vi.mock('$lib/stores/toast', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/toast')>();
	return { ...actual, addToast: vi.fn() };
});

import VoicesPage from './+page.svelte';
import { loras, lorasError, lorasLoading } from '$lib/stores/loras';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	mocks.loadLoras.mockReset().mockResolvedValue([]);
	mocks.createLora.mockReset();
	mocks.softDeleteLora.mockReset();
	loras.set([]);
	lorasLoading.set(false);
	lorasError.set(null);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('voices page', () => {
	it('shows the unchanged server 409 detail when creating a voice reaches its limit', async () => {
		const detail =
			'You have reached the limit of 10 voices. Delete a voice before creating another.';
		mocks.createLora.mockRejectedValueOnce(new ApiError(409, detail, '/api/loras'));
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(VoicesPage, { target });
		await tick();

		target.querySelector<HTMLButtonElement>('.create-btn')?.click();
		await tick();
		const input = target.querySelector<HTMLInputElement>('.create-panel input');
		if (!input) throw new Error('Expected voice name input');
		input.value = 'My Tenor';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		target.querySelector<HTMLButtonElement>('.create-panel .primary')?.click();

		await vi.waitFor(() =>
			expect(target.querySelector('[role="alert"]')?.textContent).toBe(detail)
		);
		expect(mocks.createLora).toHaveBeenCalledWith('My Tenor');
	});
});
