import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeHealthResponse } from '#lib/test-utils/factories.ts';

const fetchConversations = vi.hoisted(() => vi.fn());
const fetchConversationMessages = vi.hoisted(() => vi.fn());
const fetchHealth = vi.hoisted(() => vi.fn());

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		fetchConversations: (...args: Parameters<typeof fetchConversations>) =>
			fetchConversations(...args),
		fetchConversationMessages: (...args: Parameters<typeof fetchConversationMessages>) =>
			fetchConversationMessages(...args),
		fetchHealth: (...args: Parameters<typeof fetchHealth>) => fetchHealth(...args)
	};
});

import CoWriterPanel from './CoWriterPanel.svelte';
import { startHealthPolling, stopHealthPolling } from '#lib/stores/health.ts';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	fetchConversations.mockReset().mockResolvedValue([]);
	fetchConversationMessages.mockReset().mockResolvedValue({ messages: [] });
	fetchHealth.mockReset().mockResolvedValue(makeHealthResponse());
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	stopHealthPolling();
});

describe('1906_E3 CoWriterPanel (Art. 50 AI Act)', () => {
	it('1906_E3: says in its own row under the header that the musician writes with an AI', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		startHealthPolling();
		await Promise.resolve();
		mounted = mount(CoWriterPanel, {
			target,
			props: { currentSongId: 's1', currentAlbumId: 'a1' }
		});
		await tick();
		await Promise.resolve();
		await tick();

		const header = target.querySelector('.convo');
		const notice = target.querySelector('.ai-notice');
		expect(notice).toHaveTextContent('Du schreibst mit einer KI');
		expect(notice).toHaveAttribute('lang', 'de');
		expect(header?.nextElementSibling).toBe(notice);
		expect(header).not.toContainElement(notice as HTMLElement);
	});
});
