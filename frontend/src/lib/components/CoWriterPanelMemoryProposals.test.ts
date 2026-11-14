import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { words } from '#lib/words/en.ts';
import { sendToCowriter } from '#lib/test-utils/cowriter-composer.ts';
import { kitWords } from '#lib/utils/kit-words.ts';
import type { CoWriterStreamEvent } from '#lib/api/client.ts';

const fetchConversations = vi.hoisted(() => vi.fn());
const fetchConversationMessages = vi.hoisted(() => vi.fn());
const streamCoWriterTurn = vi.hoisted(() => vi.fn());

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		fetchConversations: (...args: Parameters<typeof fetchConversations>) =>
			fetchConversations(...args),
		fetchConversationMessages: (...args: Parameters<typeof fetchConversationMessages>) =>
			fetchConversationMessages(...args),
		streamCoWriterTurn: (...args: Parameters<typeof streamCoWriterTurn>) =>
			streamCoWriterTurn(...args),
		fetchMemory: vi.fn().mockResolvedValue({
			user: { scope: 'user', target_id: 'u1', body: 'Prefers short lines' }
		}),
		saveUserMemory: vi.fn(async (body: string) => ({ scope: 'user', target_id: 'u1', body }))
	};
});

import { saveUserMemory } from '#lib/api/client.ts';
import CoWriterPanel from './CoWriterPanel.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	vi.mocked(saveUserMemory).mockClear();
	fetchConversations.mockReset().mockResolvedValue([
		{
			id: 'c1',
			title: null,
			message_count: 2,
			archived_at: null,
			created_at: '2026-01-01T00:00:00+00:00'
		}
	]);
	fetchConversationMessages.mockReset().mockResolvedValue({
		conversation_id: 'c1',
		title: null,
		archived_at: null,
		turn_running: false,
		messages: [
			{
				id: 'm1',
				role: 'assistant',
				content:
					'Noted. <memory_proposal scope="user"><current>Prefers short lines</current>' +
					'<proposed>Prefers short lines, no rhymes</proposed></memory_proposal>',
				created_at: '2026-09-26T15:21:00+00:00'
			}
		]
	});
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

async function mountPanel(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(CoWriterPanel, {
			target,
			props: { currentSongId: 's1', currentAlbumId: 'a1', currentAlbumTitle: 'Album', allSongs: [] }
		})
	);
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

async function openPanelWithWaitingProposal(): Promise<HTMLElement> {
	const target = await mountPanel();
	target.querySelector<HTMLButtonElement>('button.convo-menu-btn')?.click();
	await tick();
	Array.from(target.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
		.find((item) => item.textContent?.trim() === words['cowriter.memory'])
		?.click();
	await tick();
	await vi.waitFor(() => expect(target.querySelector('.proposal')).not.toBeNull());
	return target;
}

describe('CoWriterPanel memory proposals', () => {
	// Spec: REQ-COWRITER-17 -- Accept saves the proposed text; nothing is saved before it.
	it('saves the proposed text when the musician accepts and not before', async () => {
		const target = await openPanelWithWaitingProposal();
		expect(saveUserMemory).not.toHaveBeenCalled();

		target.querySelector<HTMLButtonElement>('.proposal .accept')?.click();

		await vi.waitFor(() =>
			expect(saveUserMemory).toHaveBeenCalledExactlyOnceWith('Prefers short lines, no rhymes')
		);
	});

	// Spec: REQ-COWRITER-17 -- Reject saves nothing and the proposal goes away.
	it('saves nothing when the musician rejects', async () => {
		const target = await openPanelWithWaitingProposal();

		target.querySelector<HTMLButtonElement>('.proposal .reject')?.click();

		await vi.waitFor(() => expect(target.querySelector('.proposal')).toBeNull());
		expect(saveUserMemory).not.toHaveBeenCalled();
	});

	it('shows the thinking line for a reply that is only a proposal and no bubble once it ends', async () => {
		const proposalOnly =
			'<memory_proposal scope="user"><current>Prefers short lines</current>' +
			'<proposed>Prefers short lines, no rhymes</proposed></memory_proposal>';
		const stored = (id: string, role: 'user' | 'assistant', content: string) => ({
			id,
			role,
			content,
			created_at: '2026-09-26T15:21:00+00:00'
		});
		fetchConversationMessages.mockResolvedValue({
			conversation_id: 'c1',
			title: null,
			archived_at: null,
			turn_running: false,
			messages: []
		});
		let finishTurn: () => void = () => undefined;
		const turnFinished = new Promise<void>((resolve) => (finishTurn = resolve));
		streamCoWriterTurn.mockReturnValue(
			(async function* (): AsyncGenerator<CoWriterStreamEvent> {
				yield { type: 'assistant_text', text: proposalOnly } as CoWriterStreamEvent;
				await turnFinished;
				yield {
					type: 'final',
					conversation_id: 'c1',
					user_message: stored('u1', 'user', 'Remember this'),
					assistant_message: stored('a1', 'assistant', proposalOnly)
				} as CoWriterStreamEvent;
			})()
		);
		const target = await mountPanel();
		await sendToCowriter(target, 'Remember this');

		await vi.waitFor(() =>
			expect(target.querySelector('[role="status"]')?.textContent).toBe(
				kitWords()['helperChat.thinking']({ name: words['cowriter.title'] })
			)
		);
		finishTurn();
		await vi.waitFor(() => expect(target.querySelector('[role="status"]')?.textContent).toBe(''));
		expect(target.querySelectorAll('.message.assistant .bubble')).toHaveLength(0);
	});
});
