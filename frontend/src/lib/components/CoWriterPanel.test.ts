import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchConversationMessages: vi.fn().mockResolvedValue({ messages: [] }),
		startNewConversation: vi.fn(async () => ({
			id: 'c1',
			title: null,
			message_count: 0,
			archived_at: null,
			created_at: '2026-01-01T00:00:00+00:00'
		})),
		deleteConversation: vi.fn(),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchCowriterSettings: vi.fn().mockResolvedValue({ provider: 'claude', model: 'sonnet' })
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';
import { startNewConversation } from '$lib/api/client';

const mounted: Array<ReturnType<typeof mount>> = [];

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function render() {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(CoWriterPanel, {
			target,
			props: { currentSongId: 's1', currentAlbumId: 'a1', currentAlbumTitle: 'Album' }
		})
	);
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('CoWriterPanel', () => {
	it('renders without a Close button (its lifecycle is owned by the Editor header toggle)', async () => {
		const target = await render();
		expect(target.querySelector('.close-btn')).toBeNull();
		expect(target.querySelector('.new-btn')).not.toBeNull();
	});

	it('starts a new conversation from the header action', async () => {
		const target = await render();
		target.querySelector<HTMLButtonElement>('.new-btn')?.click();
		await tick();
		expect(startNewConversation).toHaveBeenCalledTimes(1);
	});

	it('has no left border now that it fills the Write column instead of a side panel', async () => {
		const target = await render();
		const root = target.querySelector('.cowriter');
		expect(root).not.toBeNull();
		expect(getComputedStyle(root as Element).borderLeftWidth).not.toBe('1px');
	});
});
