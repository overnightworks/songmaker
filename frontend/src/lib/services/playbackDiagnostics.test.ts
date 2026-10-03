import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PlaybackDiagnosticsReport } from '$lib/api/types';
type Recorder = typeof import('./playbackDiagnostics');
type PlaybackNote = Parameters<Recorder['recordPlaybackEvent']>[0];

const LISTENER = 'listener-id';
const OTHER_LISTENER = 'other-listener-id';
const TAKE_ID = '6f1c2a4e-9b0d-4c3e-8a51-2f7d9e0b1c34';

let recorder: Recorder;
let stopRecording: (() => void) | null = null;
let visibility: DocumentVisibilityState = 'visible';
let answerStatus = 204;
let serverAnswers = true;
let keepaliveSendsFail = false;
const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
	if (!serverAnswers) return new Promise<Response>(() => {});
	if (keepaliveSendsFail && init.keepalive) throw new TypeError('Failed to fetch');
	return new Response(null, { status: answerStatus });
});

// A fresh module per page load: what survives is only what the recorder
// wrote to storage, as after Android killed the page. Stopping the old page's
// recorder sends nothing; it only keeps its listeners out of the next page.
async function openPage(): Promise<Recorder> {
	stopRecording?.();
	stopRecording = null;
	vi.resetModules();
	recorder = await import('./playbackDiagnostics');
	return recorder;
}

function startFor(userId: string): void {
	stopRecording?.();
	stopRecording = recorder.startPlaybackDiagnostics(userId);
}

function note(detail: string, overrides: Partial<PlaybackNote> = {}): PlaybackNote {
	return {
		kind: 'media_event',
		detail,
		take: { takeId: TAKE_ID, position: 12.5, readyState: 4, deck: 'active' },
		...overrides
	};
}

function recordMany(count: number): void {
	for (let index = 0; index < count; index += 1) recorder.recordPlaybackEvent(note(`e${index}`));
}

function recordLarge(count: number): void {
	for (let index = 0; index < count; index += 1)
		recorder.recordPlaybackEvent(note('x'.repeat(200)));
}

function hidePage(): void {
	visibility = 'hidden';
	document.dispatchEvent(new Event('visibilitychange'));
}

function showPage(): void {
	visibility = 'visible';
	document.dispatchEvent(new Event('visibilitychange'));
}

// The page starts to navigate away, as on a reload or a link to another site.
function startLeaving(): void {
	window.dispatchEvent(new Event('beforeunload'));
}

function sentReports(): PlaybackDiagnosticsReport[] {
	return fetchMock.mock.calls.map(([, init]) => JSON.parse(init.body as string));
}

function keepaliveBytesSent(): number {
	return fetchMock.mock.calls
		.filter(([, init]) => init.keepalive)
		.map(([, init]) => new Blob([init.body as string]).size)
		.reduce((sum, size) => sum + size, 0);
}

function sentDetails(): string[] {
	return sentReports().flatMap((report) => report.events.map((event) => event.detail));
}

// One heartbeat that fires `lateByMs` after it should have, as after a frozen page.
function missHeartbeat(lateByMs: number): void {
	vi.setSystemTime(Date.now() + lateByMs);
	vi.advanceTimersByTime(15_000);
}

// Runs `write` in a tab that has not yet seen what is stored now, as when two
// tabs in different processes write in the same moment: its write lands on
// top of the other tab's instead of growing from it.
function writeUnseen(storedBefore: string | null, write: () => void): void {
	const key = `playbackDiagnostics:${LISTENER}`;
	const readStorage = Storage.prototype.getItem;
	const staleRead = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (
		this: Storage,
		read: string
	) {
		return read === key ? storedBefore : readStorage.call(this, read);
	});
	try {
		write();
	} finally {
		staleRead.mockRestore();
	}
}

// Lets every answer the fake server gave reach the recorder.
async function letTheServerAnswer(): Promise<void> {
	await Promise.allSettled(fetchMock.mock.results.map((result) => result.value));
	await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(async () => {
	localStorage.clear();
	fetchMock.mockClear();
	answerStatus = 204;
	serverAnswers = true;
	keepaliveSendsFail = false;
	visibility = 'visible';
	Object.defineProperty(document, 'visibilityState', {
		configurable: true,
		get: () => visibility
	});
	document.cookie = 'csrf_token=csrf-abc';
	vi.stubGlobal('fetch', fetchMock);
	await openPage();
});

afterEach(() => {
	stopRecording?.();
	stopRecording = null;
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('playback diagnostics recorder', () => {
	it('keeps only the newest 500 events', async () => {
		startFor(LISTENER);
		recordMany(505);

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		const details = sentDetails();
		expect(details).toHaveLength(500);
		expect(details[0]).toBe('e5');
		expect(details.at(-1)).toBe('e504');
	});

	it('sends on hide with keepalive and the CSRF header, at most 100 events per report', async () => {
		startFor(LISTENER);
		recordMany(250);

		hidePage();
		await letTheServerAnswer();

		expect(sentReports().map((report) => report.events.length)).toEqual([100, 100, 51]);
		for (const [url, init] of fetchMock.mock.calls) {
			expect(url).toBe('/api/playback-diagnostics');
			expect(init.keepalive).toBe(true);
			expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-abc');
		}
	});

	it('sends on hide only the reports that fit the 64 KiB keepalive budget, the rest at the next start', async () => {
		startFor(LISTENER);
		recordLarge(400);

		hidePage();
		await letTheServerAnswer();
		const keepaliveBytes = keepaliveBytesSent();
		const sentOnHide = sentDetails().length;
		fetchMock.mockClear();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(keepaliveBytes).toBeLessThanOrEqual(64 * 1024);
		expect(sentOnHide).toBeGreaterThan(0);
		expect(sentOnHide + sentDetails().length).toBe(401);
	});

	it.each([
		['within one sign-in', () => {}],
		[
			'across a sign-in change',
			() => {
				recorder.forgetPlaybackDiagnostics(LISTENER);
				startFor(OTHER_LISTENER);
				recordLarge(400);
			}
		]
	])(
		'counts what an unanswered send on hide still has in flight against a pagehide right after, %s',
		(_case, between) => {
			serverAnswers = false;
			startFor(LISTENER);
			recordLarge(400);

			hidePage();
			between();
			window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));

			expect(keepaliveBytesSent()).toBeLessThanOrEqual(64 * 1024);
		}
	);

	it('sends on pagehide with keepalive', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('before the page went'));

		window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['before the page went', 'persisted=false']);
		expect(sentReports()[0].events[1].kind).toBe('page_hide');
		expect(fetchMock.mock.calls[0][1].keepalive).toBe(true);
	});

	it('sends what a killed page left behind when the app starts again, without keepalive', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('last words'));

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['last words']);
		expect(fetchMock.mock.calls[0][1].keepalive).toBe(false);
	});

	it('sends a delivered event only once', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('once'));
		hidePage();
		await letTheServerAnswer();

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['once', 'hidden']);
	});

	it('numbers the events of a page session in the order they happened', async () => {
		startFor(LISTENER);
		recordMany(2);
		hidePage();
		await letTheServerAnswer();

		const [report] = sentReports();
		expect(report.events.map((event) => event.sequence)).toEqual([0, 1, 2]);
	});

	it('never sends again after a reload what the page handed to the browser on hide', async () => {
		serverAnswers = false;
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('handed off'));
		hidePage();
		fetchMock.mockClear();
		serverAnswers = true;

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('sends again on pagehide nothing the hide handed to the browser, though the leaving page never saw the answer', async () => {
		keepaliveSendsFail = true;
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('handed off'));
		hidePage();
		startLeaving();
		await letTheServerAnswer();

		window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
		await letTheServerAnswer();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['handed off', 'hidden', 'persisted=false']);
	});

	it.each([
		{
			next: 'hide',
			sendAgain: () => {
				showPage();
				hidePage();
			},
			sent: ['unsent', 'hidden', 'visible', 'hidden']
		},
		{
			next: 'start',
			sendAgain: async () => {
				await openPage();
				startFor(LISTENER);
			},
			sent: ['unsent', 'hidden']
		}
	])(
		'sends on the next $next what a hidden page that stays could not send',
		async ({ sendAgain, sent }) => {
			keepaliveSendsFail = true;
			startFor(LISTENER);
			recorder.recordPlaybackEvent(note('unsent'));
			hidePage();
			await letTheServerAnswer();
			keepaliveSendsFail = false;
			fetchMock.mockClear();

			await sendAgain();
			await letTheServerAnswer();

			expect(sentDetails()).toEqual(sent);
		}
	);

	it('keeps the events for the next start when the page hides without a network', async () => {
		const offline = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('offline'));
		hidePage();
		await letTheServerAnswer();
		offline.mockRestore();

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['offline', 'hidden']);
		expect(fetchMock.mock.calls.every(([, init]) => !init.keepalive)).toBe(true);
	});

	it('keeps an event another tab wrote over in the same moment', async () => {
		const firstTab = recorder;
		const stopFirstTab = firstTab.startPlaybackDiagnostics(LISTENER);
		vi.resetModules();
		const secondTab: Recorder = await import('./playbackDiagnostics');
		const stopSecondTab = secondTab.startPlaybackDiagnostics(LISTENER);
		await letTheServerAnswer();
		firstTab.recordPlaybackEvent(note('first tab, before'));

		const storedBefore = localStorage.getItem(`playbackDiagnostics:${LISTENER}`);
		firstTab.recordPlaybackEvent(note('first tab, written over'));
		writeUnseen(storedBefore, () => secondTab.recordPlaybackEvent(note('second tab, same moment')));
		firstTab.recordPlaybackEvent(note('first tab, after'));
		stopFirstTab();
		stopSecondTab();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails().sort()).toEqual(
			[
				'first tab, before',
				'first tab, written over',
				'second tab, same moment',
				'first tab, after'
			].sort()
		);
	});

	it('sends every event of two tabs of the same user exactly once, whichever tab writes last', async () => {
		const firstTab = recorder;
		const stopFirstTab = firstTab.startPlaybackDiagnostics(LISTENER);
		firstTab.recordPlaybackEvent(note('first tab, before the second opened'));
		vi.resetModules();
		const secondTab: Recorder = await import('./playbackDiagnostics');
		const stopSecondTab = secondTab.startPlaybackDiagnostics(LISTENER);
		await letTheServerAnswer();

		secondTab.recordPlaybackEvent(note('second tab'));
		firstTab.recordPlaybackEvent(note('first tab, after the second opened'));
		stopFirstTab();
		stopSecondTab();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(sentDetails().sort()).toEqual(
			[
				'first tab, before the second opened',
				'second tab',
				'first tab, after the second opened'
			].sort()
		);
	});

	it.each([401, 403])(
		'keeps the events for a later send when the server answers %i',
		async (status) => {
			startFor(LISTENER);
			recorder.recordPlaybackEvent(note('left by an earlier page'));
			await openPage();
			answerStatus = status;
			startFor(LISTENER);
			await letTheServerAnswer();
			recorder.recordPlaybackEvent(note('kept'));
			hidePage();
			await letTheServerAnswer();
			fetchMock.mockClear();
			answerStatus = 204;

			await openPage();
			startFor(LISTENER);
			await letTheServerAnswer();

			expect(sentDetails()).toEqual(['left by an earlier page', 'kept', 'hidden']);
		}
	);

	it('never sends another user’s events', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('first listener'));

		await openPage();
		startFor(OTHER_LISTENER);
		recorder.recordPlaybackEvent(note('second listener'));
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['second listener', 'hidden']);
	});

	it('never sends the events of a user who signed out to the next user of the same page', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('first listener'));
		recorder.forgetPlaybackDiagnostics(LISTENER);

		startFor(OTHER_LISTENER);
		recorder.recordPlaybackEvent(note('second listener'));
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['second listener', 'hidden']);
	});

	it('forgets a user’s events so nothing of theirs is sent later', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('before logout'));
		recorder.forgetPlaybackDiagnostics(LISTENER);
		recorder.recordPlaybackEvent(note('after logout'));
		hidePage();
		await letTheServerAnswer();

		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('records nothing while no user is signed in', async () => {
		recorder.recordPlaybackEvent(note('nobody'));
		startFor(LISTENER);
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()).toEqual(['hidden']);
	});

	it('tells the server the boot facts and the page clock of each event', async () => {
		vi.stubGlobal('MediaSource', { isTypeSupported: (type: string) => type === 'audio/mpeg' });
		Object.defineProperty(document, 'wasDiscarded', { configurable: true, value: true });
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('take event'));
		hidePage();
		await letTheServerAnswer();
		Reflect.deleteProperty(document, 'wasDiscarded');

		const [report] = sentReports();
		expect(report).toMatchObject({ mse_mp3_supported: true, was_discarded: true });
		expect(report.session_id).not.toBe('');
		expect(report.events[0]).toMatchObject({
			kind: 'media_event',
			take_id: TAKE_ID,
			position: 12.5,
			ready_state: 4,
			deck: 'active',
			visibility: 'visible'
		});
		expect(report.events[0].at_ms).toBeGreaterThanOrEqual(0);
		expect(report.events[1]).toMatchObject({ take_id: null, visibility: 'hidden' });
	});

	it.each([
		['freeze', document, () => new Event('freeze'), 'freeze'],
		['resume', document, () => new Event('resume'), 'resume'],
		[
			'pageshow',
			window,
			() => new PageTransitionEvent('pageshow', { persisted: true }),
			'page_show'
		],
		['online', window, () => new Event('online'), 'online'],
		['offline', window, () => new Event('offline'), 'offline']
	] as const)('records the page’s %s', async (_name, target, event, kind) => {
		startFor(LISTENER);
		target.dispatchEvent(event());
		hidePage();
		await letTheServerAnswer();

		expect(sentReports()[0].events[0].kind).toBe(kind);
	});

	it.each([
		['visibilitychange', hidePage, 'visibility_change'],
		[
			'pagehide',
			() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })),
			'page_hide'
		]
	] as const)(
		'records with the page’s %s the take the player reports as playing',
		async (_name, happen, kind) => {
			startFor(LISTENER);
			recorder.readThePlayingTakeFrom(() => ({
				takeId: TAKE_ID,
				position: 93.4,
				readyState: 4,
				deck: 'active'
			}));
			happen();
			await letTheServerAnswer();

			expect(sentReports()[0].events[0]).toMatchObject({
				kind,
				take_id: TAKE_ID,
				position: 93.4,
				ready_state: 4,
				deck: 'active'
			});
		}
	);

	it('records a timer gap when much more time passed than the heartbeat asked for', async () => {
		vi.useFakeTimers();
		startFor(LISTENER);
		missHeartbeat(45_000);
		vi.useRealTimers();
		hidePage();
		await letTheServerAnswer();

		const [gap] = sentReports()[0].events;
		expect(gap.kind).toBe('timer_gap');
		expect(gap.detail).toBe('count=1 total_ms=60000');
	});

	it('merges consecutive timer gaps into one event until something else is recorded', async () => {
		vi.useFakeTimers();
		startFor(LISTENER);
		missHeartbeat(45_000);
		missHeartbeat(30_000);
		missHeartbeat(20_000);
		recorder.recordPlaybackEvent(note('woke up'));
		missHeartbeat(45_000);
		vi.useRealTimers();
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()).toEqual([
			'count=3 total_ms=140000',
			'woke up',
			'count=1 total_ms=60000',
			'hidden'
		]);
	});

	it('keeps every missed heartbeat when another tab sent the open timer gap', async () => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
		const firstTab = recorder;
		const stopFirstTab = firstTab.startPlaybackDiagnostics(LISTENER);
		missHeartbeat(45_000);
		vi.resetModules();
		const secondTab: Recorder = await import('./playbackDiagnostics');
		const stopSecondTab = secondTab.startPlaybackDiagnostics(LISTENER);
		await letTheServerAnswer();
		stopSecondTab();

		missHeartbeat(45_000);
		stopFirstTab();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		const gaps = sentReports()
			.flatMap((report) => report.events)
			.filter((event) => event.kind === 'timer_gap')
			.map((event) => event.detail);
		expect(gaps).toEqual(['count=1 total_ms=60000', 'count=1 total_ms=60000']);
	});

	it('cuts a detail to the 200 characters the server accepts', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('x'.repeat(250)));
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()[0]).toHaveLength(200);
	});
});
