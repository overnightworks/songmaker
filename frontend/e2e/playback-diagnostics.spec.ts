import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import type { PlaybackDiagnosticsReport } from '../src/lib/api/types';
import { PLAYBACK_DIAGNOSTICS_PATH } from '../src/lib/constants';
import { accountCircle } from './helpers';

/**
 * The playback recorder (#1187, #1250) tells the server what the player and the
 * page did on the listener's phone. These flows prove the two promises its log
 * is read by: no event is lost and none arrives twice, across two tabs of one
 * listener and across a page that hides and then reloads.
 */

/** The newest events a listener's buffer keeps. */
const BUFFER_CAPACITY = 500;

/** More than a buffer keeps, so the hide fills its keepalive budget. */
const EVENTS_BEFORE_THE_HIDE = 620;

/** Three times the network goes and comes back: six events per tab. */
const NETWORK_DROPS = 3;

const SENT_TRACE_KEY = 'sentPlaybackDiagnostics';

type SentEvent = { session: string; sequence: number; kind: string };

test.beforeEach(({ isMobile }) => {
	test.skip(
		!isMobile,
		'The recorder serves the phone (#1187); the desktop shell runs the same module.'
	);
});

async function openSignedIn(page: Page): Promise<void> {
	await page.goto('/');
	await expect(accountCircle(page)).toBeVisible();
}

function reportsOf(context: BrowserContext): PlaybackDiagnosticsReport[] {
	const reports: PlaybackDiagnosticsReport[] = [];
	context.on('request', (request) => {
		const sent = new URL(request.url()).pathname === PLAYBACK_DIAGNOSTICS_PATH;
		if (sent && request.method() === 'POST') reports.push(JSON.parse(request.postData() ?? '{}'));
	});
	return reports;
}

async function setOfflineSeenByEveryTab(
	context: BrowserContext,
	tabs: Page[],
	offline: boolean
): Promise<void> {
	await context.setOffline(offline);
	for (const tab of tabs)
		await expect.poll(() => tab.evaluate(() => navigator.onLine)).toBe(!offline);
}

async function hide(page: Page): Promise<void> {
	await page.evaluate(() => {
		Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
		document.dispatchEvent(new Event('visibilitychange'));
	});
}

test('two tabs of one listener each report every time the network went and came back, once', async ({
	context
}) => {
	const reports = reportsOf(context);
	const first = await context.newPage();
	await openSignedIn(first);
	const second = await context.newPage();
	await openSignedIn(second);
	const tabs = [first, second];

	for (let drop = 0; drop < NETWORK_DROPS; drop += 1) {
		await setOfflineSeenByEveryTab(context, tabs, true);
		await setOfflineSeenByEveryTab(context, tabs, false);
	}
	for (const tab of tabs) await hide(tab);

	const networkEventsPerTab = () => {
		const perSession = new Map<string, number>();
		for (const report of reports)
			for (const event of report.events)
				if (event.kind === 'online' || event.kind === 'offline')
					perSession.set(report.session_id, (perSession.get(report.session_id) ?? 0) + 1);
		return [...perSession.values()];
	};
	await expect.poll(networkEventsPerTab).toEqual([2 * NETWORK_DROPS, 2 * NETWORK_DROPS]);
});

test('a page that hides and then reloads sends every event its buffer kept exactly once', async ({
	page
}) => {
	// The trace lives in the tab's sessionStorage, so the sends of the page that
	// reloads and of the page that follows it land in one list.
	await page.addInitScript(
		({ path, traceKey }) => {
			const send = window.fetch;
			window.fetch = function (input, init) {
				const url = new URL(input instanceof Request ? input.url : String(input), location.href);
				if (url.pathname === path && typeof init?.body === 'string') {
					const report = JSON.parse(init.body);
					const sent = JSON.parse(sessionStorage.getItem(traceKey) ?? '[]');
					for (const event of report.events)
						sent.push({ session: report.session_id, sequence: event.sequence, kind: event.kind });
					sessionStorage.setItem(traceKey, JSON.stringify(sent));
				}
				return send.call(this, input, init);
			};
		},
		{ path: PLAYBACK_DIAGNOSTICS_PATH, traceKey: SENT_TRACE_KEY }
	);
	await openSignedIn(page);
	await page.evaluate(
		({ count, traceKey }) => {
			sessionStorage.removeItem(traceKey);
			for (let index = 0; index < count; index += 1)
				window.dispatchEvent(new Event(index % 2 === 0 ? 'offline' : 'online'));
		},
		{ count: EVENTS_BEFORE_THE_HIDE, traceKey: SENT_TRACE_KEY }
	);

	// A server that has not yet answered the hide's reports when the reload
	// starts: Chromium then fails them in the leaving page and still delivers them.
	let reloadStarted!: () => void;
	const reloading = new Promise<void>((resolve) => (reloadStarted = resolve));
	const isDiagnosticsReport = (url: URL) => url.pathname === PLAYBACK_DIAGNOSTICS_PATH;
	await page.route(isDiagnosticsReport, async (route) => {
		await reloading;
		await route.continue();
	});
	await hide(page);
	const reload = page.reload();
	reloadStarted();
	await reload;
	await page.unroute(isDiagnosticsReport);
	await expect(accountCircle(page)).toBeVisible();
	await hide(page);

	const sentEvents = (): Promise<SentEvent[]> =>
		page.evaluate(
			(traceKey) => JSON.parse(sessionStorage.getItem(traceKey) ?? '[]'),
			SENT_TRACE_KEY
		);
	const pageHides = async () =>
		new Set(
			(await sentEvents()).filter((event) => event.kind === 'page_hide').map((e) => e.session)
		);
	const hiddenAgain = async () =>
		(await sentEvents()).filter((event) => event.kind === 'visibility_change').length;
	await expect.poll(pageHides).toHaveProperty('size', 1);
	await expect.poll(hiddenAgain).toBeGreaterThanOrEqual(2);

	const sent = await sentEvents();
	const keys = sent.map((event) => `${event.session}:${event.sequence}`);
	const sentTwice = keys.filter((key, index) => keys.indexOf(key) !== index);
	expect(sentTwice).toEqual([]);

	const [reloadedSession] = await pageHides();
	const ofReloadedSession = sent.filter((event) => event.session === reloadedSession);
	const sequences = [...new Set(ofReloadedSession.map((event) => event.sequence))].sort(
		(a, b) => a - b
	);
	const hiddenAt = Math.min(
		...ofReloadedSession
			.filter((event) => event.kind === 'visibility_change')
			.map((event) => event.sequence)
	);
	const oldestKept = hiddenAt - BUFFER_CAPACITY + 1;
	const keptAndAfter = Array.from(
		{ length: Math.max(...sequences) - oldestKept + 1 },
		(_, offset) => oldestKept + offset
	);
	expect(sequences).toEqual(keptAndAfter);
});
