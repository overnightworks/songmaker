// Leaving the co-writer mid-reply and coming back (issue #1014, operator
// ruling 26.09.2026: "Wechseln sollte keinen Einfluss darauf haben"). The
// message sent stays on screen with the thinking line, and the reply appears
// once the turn completes — without sending again; an unsent draft is still
// in the composer. Mobile project only: the co-writer is the phone song
// page's middle tab (#1016), and switching to Edit and Takes and back is the
// return this pins.
//
// CI's e2e stack configures no co-writer provider, so a real turn ends at
// once with its route failure and cannot be left while it runs. The turn and
// the conversation it writes are therefore answered by `page.route`, playing
// the backend contract tests/test_conversation_api.py pins: the user message
// is in the conversation from the moment the turn starts, the conversation
// reports the turn running until it ends, and the reply joins it then.
//
// The message is sent with Enter from the composer, not a tap on Send: with
// the composer focused, the tap's own focus change brings the mini-player
// back (#999) and moves Send before the tap completes, so the tap never
// sends. That is a defect of its own, not of the return path pinned here.
//
// Coming back to a turn that ended unanswered shows the retained message with
// Try again; the server answers that message when it is sent again instead of
// storing it twice, so a retry that fails too still shows it once. Only the
// newest message offers Try again: an older one sent again would be stored a
// second time.
//
// Once a newer message is answered, the chat shows what the conversation
// holds: an older failed message the server stored stays, without Try again,
// exactly as a reload shows it.

import { expect, test, type Page, type Route } from '@playwright/test';
import {
	COWRITER_TURN_PATH,
	EDITOR_TAB_EDIT_LABEL,
	EDITOR_TAB_TAKES_LABEL,
	EDITOR_VIEW_COWRITER_LABEL
} from '../src/lib/constants';
import { nameStartingWith, workspace } from './helpers';
import { readSeededLibrary } from './seed';

const CONVERSATION_ID = 'e2e-cowriter-return';
const SENT = 'Ja bitte, schreib den Refrain neu';
const REPLY = 'Erledigt. Der neue Refrain steht als neue Version.';
const THINKING = /is thinking/;

const RETRY_FAILURE = 'CLI is unavailable.';

type TurnState = 'idle' | 'running' | 'answered';
type ChatMessage = ReturnType<typeof chatMessage>;

interface ConversationState {
	messages: ChatMessage[];
	turnRunning: boolean;
}

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

async function answerConversation(page: Page, read: () => ConversationState): Promise<void> {
	await page.route('**/api/conversations', (route: Route) => {
		const { messages } = read();
		return route.fulfill({
			json: {
				conversations:
					messages.length === 0
						? []
						: [
								{
									id: CONVERSATION_ID,
									title: null,
									message_count: messages.length,
									archived_at: null,
									created_at: '2026-09-26T15:20:00+00:00'
								}
							]
			}
		});
	});
	await page.route(`**/api/conversations/${CONVERSATION_ID}`, (route: Route) => {
		const { messages, turnRunning } = read();
		return route.fulfill({
			json: {
				conversation_id: CONVERSATION_ID,
				title: null,
				archived_at: null,
				messages,
				turn_running: turnRunning
			}
		});
	});
}

function turnStream(event: object): string {
	return `data: ${JSON.stringify(event)}\n\n`;
}

async function openCowriterOnPickedSong(page: Page): Promise<void> {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	await workspace(page)
		.getByRole('button', { name: nameStartingWith(library.pickedSongTitle) })
		.click();
	await expect(page.getByRole('heading', { name: library.pickedSongTitle })).toBeVisible();
	await showCowriterTab(page);
}

async function showCowriterTab(page: Page): Promise<void> {
	await page.getByRole('tab', { name: EDITOR_VIEW_COWRITER_LABEL, exact: true }).click();
}

async function lookAtEditAndTakes(page: Page): Promise<void> {
	await page.getByRole('tab', { name: EDITOR_TAB_EDIT_LABEL, exact: true }).click();
	await expect(page.getByPlaceholder(/Ask the co-writer/)).toBeHidden();
	await page.getByRole('tab', { name: nameStartingWith(EDITOR_TAB_TAKES_LABEL) }).click();
	await expect(page.getByPlaceholder(/Ask the co-writer/)).toBeHidden();
}

test.describe('co-writer return at phone width', () => {
	test('leaving mid-reply and coming back shows the message sent, then the reply', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is a tab only on the phone; see the file header.');
		let turnState: TurnState = 'idle';
		let completeTurn = (): void => {};
		const turnCompleted = new Promise<void>((resolve) => {
			completeTurn = resolve;
		});

		await answerConversation(page, () => ({
			messages: historyFor(turnState),
			turnRunning: turnState === 'running'
		}));
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

		await openCowriterOnPickedSong(page);
		const composer = page.getByPlaceholder(/Ask the co-writer/);
		await composer.fill(SENT);
		await composer.press('Enter');
		await expect(page.getByText(THINKING)).toBeVisible();
		await expect.poll(() => turnState).toBe('running');

		await lookAtEditAndTakes(page);

		await showCowriterTab(page);
		await expect(page.getByText(SENT)).toBeVisible();
		await expect(page.getByText(THINKING)).toBeVisible();
		await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();

		turnState = 'answered';
		completeTurn();

		await expect(page.getByText(REPLY)).toBeVisible();
		await expect(page.getByText(THINKING)).toHaveCount(0);
		await expect(page.getByText(SENT)).toHaveCount(1);
	});

	test('an unsent message waits in the composer while Edit and Takes are looked at', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is a tab only on the phone; see the file header.');
		const draft = 'Noch nicht gesendet: der zweite Vers';
		await answerConversation(page, () => ({ messages: [], turnRunning: false }));

		await openCowriterOnPickedSong(page);
		await page.getByPlaceholder(/Ask the co-writer/).fill(draft);
		await lookAtEditAndTakes(page);
		await showCowriterTab(page);

		await expect(page.getByPlaceholder(/Ask the co-writer/)).toHaveValue(draft);
	});

	test('retrying the unanswered message it came back to shows it once when the retry fails too', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is a tab only on the phone; see the file header.');
		let retried = false;
		await answerConversation(page, () => ({ messages: [sentMessage], turnRunning: false }));
		await page.route(`**${COWRITER_TURN_PATH}`, (route: Route) => {
			retried = true;
			const failure = { type: 'error', status: 503, message: RETRY_FAILURE };
			return route.fulfill({
				contentType: 'text/event-stream',
				body: `data: ${JSON.stringify(failure)}\n\n`
			});
		});

		await openCowriterOnPickedSong(page);
		await expect(page.getByText(SENT)).toHaveCount(1);
		await page.getByRole('button', { name: 'Try again' }).click();

		await expect.poll(() => retried).toBe(true);
		await expect(page.getByText(RETRY_FAILURE)).toBeVisible();
		await expect(page.getByText(SENT)).toHaveCount(1);
		await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(1);
	});

	test('a failed message followed by a newer failed one no longer offers Try again', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is a tab only on the phone; see the file header.');
		const older = 'Erste Nachricht, die scheitert';
		const newer = 'Zweite Nachricht, die auch scheitert';
		await answerConversation(page, () => ({ messages: [], turnRunning: false }));
		await page.route(`**${COWRITER_TURN_PATH}`, (route: Route) => {
			const failure = { type: 'error', status: 503, message: RETRY_FAILURE };
			return route.fulfill({
				contentType: 'text/event-stream',
				body: `data: ${JSON.stringify(failure)}\n\n`
			});
		});

		await openCowriterOnPickedSong(page);
		const composer = page.getByPlaceholder(/Ask the co-writer/);
		const tryAgain = page.getByRole('button', { name: 'Try again' });
		await composer.fill(older);
		await composer.press('Enter');
		await expect(tryAgain).toHaveCount(1);
		await composer.fill(newer);
		await composer.press('Enter');

		await expect(
			page.locator('.message', { hasText: newer }).getByRole('button', { name: 'Try again' })
		).toHaveCount(1);
		await expect(tryAgain).toHaveCount(1);
	});

	test('a failed message stays once a newer one is answered, the same after a reload', async ({
		page,
		isMobile
	}) => {
		test.skip(!isMobile, 'The co-writer is a tab only on the phone; see the file header.');
		const failed = 'Erste Nachricht, die scheitert';
		const stored: ChatMessage[] = [];
		await answerConversation(page, () => ({ messages: stored, turnRunning: false }));
		await page.route(`**${COWRITER_TURN_PATH}`, (route: Route) => {
			const { message } = route.request().postDataJSON() as { message: string };
			const userMessage = chatMessage(`e2e-user-${stored.length}`, 'user', message);
			stored.push(userMessage);
			if (message === failed) {
				return route.fulfill({
					contentType: 'text/event-stream',
					body: turnStream({ type: 'error', status: 503, message: RETRY_FAILURE })
				});
			}
			stored.push(replyMessage);
			return route.fulfill({
				contentType: 'text/event-stream',
				body: turnStream({
					type: 'final',
					conversation_id: CONVERSATION_ID,
					user_message: userMessage,
					assistant_message: replyMessage
				})
			});
		});

		await openCowriterOnPickedSong(page);
		const composer = page.getByPlaceholder(/Ask the co-writer/);
		const tryAgain = page.getByRole('button', { name: 'Try again' });
		await composer.fill(failed);
		await composer.press('Enter');
		await expect(tryAgain).toHaveCount(1);
		await composer.fill(SENT);
		await composer.press('Enter');

		const chat = page.locator('.cowriter .message');
		const shown = [failed, SENT, REPLY];
		await expect(chat).toHaveText(shown);
		await expect(tryAgain).toHaveCount(0);

		await openCowriterOnPickedSong(page);
		await expect(chat).toHaveText(shown);
		await expect(tryAgain).toHaveCount(0);
	});
});
