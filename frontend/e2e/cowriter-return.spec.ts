// Leaving the co-writer mid-reply and coming back (issue #1014, operator
// ruling 26.09.2026: "Wechseln sollte keinen Einfluss darauf haben"). The
// message sent stays on screen with the thinking line, and the reply appears
// once the turn completes — without sending again. Mobile project only: the
// co-writer is a screen of its own on the phone (#990), so Back really tears
// the panel down and opening it again mounts a fresh one, which is exactly
// the return this pins.
//
// CI's e2e stack configures no co-writer provider, so a real turn ends at
// once with its route failure and cannot be left while it runs. The turn and
// the conversation it writes are therefore answered by `page.route`, playing
// the backend contract tests/test_conversation_api.py pins: the user message
// is in the conversation from the moment the turn starts, and the reply joins
// it when the turn completes.
//
// The message is sent with Enter from the composer, not a tap on Send: with
// the composer focused, the tap's own focus change brings the mini-player
// back (#999) and moves Send before the tap completes, so the tap never
// sends. That is a defect of its own, not of the return path pinned here.

import { expect, test, type Route } from '@playwright/test';
import {
	COWRITER_TURN_PATH,
	EDITOR_COWRITER_BACK_LABEL,
	EDITOR_TAB_WRITE_LABEL,
	EDITOR_VIEW_COWRITER_LABEL
} from '../src/lib/constants';
import { nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

const CONVERSATION_ID = 'e2e-cowriter-return';
const SENT = 'Ja bitte, schreib den Refrain neu';
const REPLY = 'Erledigt. Der neue Refrain steht als neue Version.';
const THINKING = /is thinking/;

type TurnState = 'idle' | 'running' | 'answered';

function chatMessage(id: string, role: 'user' | 'assistant', content: string) {
	return { id, role, content, created_at: '2026-09-26T15:21:00+00:00' };
}

const sentMessage = chatMessage('e2e-sent', 'user', SENT);
const replyMessage = chatMessage('e2e-reply', 'assistant', REPLY);

function historyFor(state: TurnState) {
	if (state === 'idle') return [];
	if (state === 'running') return [sentMessage];
	return [sentMessage, replyMessage];
}

test.describe('co-writer return at phone width', () => {
	test('leaving mid-reply and coming back shows the message sent, then the reply', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is its own screen only on the phone; see the file header.');
		const library = readSeededLibrary();
		let turnState: TurnState = 'idle';
		let completeTurn = (): void => {};
		const turnCompleted = new Promise<void>((resolve) => {
			completeTurn = resolve;
		});

		await page.route('**/api/conversations', (route: Route) =>
			route.fulfill({
				json: {
					conversations:
						turnState === 'idle'
							? []
							: [
									{
										id: CONVERSATION_ID,
										title: null,
										message_count: historyFor(turnState).length,
										archived_at: null,
										created_at: '2026-09-26T15:20:00+00:00'
									}
								]
				}
			})
		);
		await page.route(`**/api/conversations/${CONVERSATION_ID}`, (route: Route) =>
			route.fulfill({
				json: {
					conversation_id: CONVERSATION_ID,
					title: null,
					archived_at: null,
					messages: historyFor(turnState)
				}
			})
		);
		await page.route(`**${COWRITER_TURN_PATH}`, async (route: Route) => {
			turnState = 'running';
			await turnCompleted;
			const final = {
				type: 'final',
				conversation_id: CONVERSATION_ID,
				user_message: sentMessage,
				assistant_message: replyMessage
			};
			await route.fulfill({
				contentType: 'text/event-stream',
				body: `data: ${JSON.stringify(final)}\n\n`
			});
		});

		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) })
			.click();
		await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();

		await page.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
		const composer = page.getByPlaceholder(/Ask the co-writer/);
		await composer.fill(SENT);
		await composer.press('Enter');
		await expect(page.getByText(THINKING)).toBeVisible();
		await expect.poll(() => turnState).toBe('running');

		await page.getByRole('button', { name: EDITOR_COWRITER_BACK_LABEL }).click();
		await expect(page.getByRole('tab', { name: EDITOR_TAB_WRITE_LABEL })).toBeVisible();

		await page.getByRole('button', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
		await expect(page.getByText(SENT)).toBeVisible();
		await expect(page.getByText(THINKING)).toBeVisible();
		await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();

		turnState = 'answered';
		completeTurn();

		await expect(page.getByText(REPLY)).toBeVisible();
		await expect(page.getByText(THINKING)).toHaveCount(0);
		await expect(page.getByText(SENT)).toHaveCount(1);
	});
});
