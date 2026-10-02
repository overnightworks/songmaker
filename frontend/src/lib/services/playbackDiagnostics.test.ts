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
const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => {
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

function hidePage(): void {
	visibility = 'hidden';
	document.dispatchEvent(new Event('visibilitychange'));
}

function sentReports(): PlaybackDiagnosticsReport[] {
	return fetchMock.mock.calls.map(([, init]) => JSON.parse(init.body as string));
}

function sentDetails(): string[] {
	return sentReports().flatMap((report) => report.events.map((event) => event.detail));
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
		for (let index = 0; index < 400; index += 1)
			recorder.recordPlaybackEvent(note('x'.repeat(200)));

		hidePage();
		await letTheServerAnswer();
		const keepaliveBytes = fetchMock.mock.calls
			.map(([, init]) => new Blob([init.body as string]).size)
			.reduce((sum, size) => sum + size, 0);
		const sentOnHide = sentDetails().length;
		fetchMock.mockClear();
		await openPage();
		startFor(LISTENER);
		await letTheServerAnswer();

		expect(keepaliveBytes).toBeLessThanOrEqual(64 * 1024);
		expect(sentOnHide).toBeGreaterThan(0);
		expect(sentOnHide + sentDetails().length).toBe(401);
	});

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

	it.each([401, 403])(
		'keeps the events for a later send when the server answers %i',
		async (status) => {
			startFor(LISTENER);
			recorder.recordPlaybackEvent(note('kept'));
			answerStatus = status;
			hidePage();
			await letTheServerAnswer();
			fetchMock.mockClear();
			answerStatus = 204;

			await openPage();
			startFor(LISTENER);
			await letTheServerAnswer();

			expect(sentDetails()).toEqual(['kept', 'hidden']);
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

	it('records a timer gap when much more time passed than the heartbeat asked for', async () => {
		vi.useFakeTimers();
		startFor(LISTENER);
		vi.advanceTimersByTime(15_000);
		vi.setSystemTime(Date.now() + 45_000);
		vi.advanceTimersByTime(15_000);
		vi.useRealTimers();
		hidePage();
		await letTheServerAnswer();

		const [gap] = sentReports()[0].events;
		expect(gap.kind).toBe('timer_gap');
		expect(gap.detail).toBe('elapsed_ms=60000');
	});

	it('cuts a detail to the 200 characters the server accepts', async () => {
		startFor(LISTENER);
		recorder.recordPlaybackEvent(note('x'.repeat(250)));
		hidePage();
		await letTheServerAnswer();

		expect(sentDetails()[0]).toHaveLength(200);
	});
});
