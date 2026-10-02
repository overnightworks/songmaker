import { addCsrfToken } from '$lib/api/fetch';
import type { PlaybackDiagnosticEvent, PlaybackDiagnosticsReport } from '$lib/api/types';

// A transient recorder for #1187: what the player and the page did on the
// listener's phone, written down per user on this device so that it survives
// Android killing the page, and told to the server whenever the page hides or
// the app starts again. Deleted together with the endpoint when #1187 closes.

export type PlaybackDiagnosticKind = PlaybackDiagnosticEvent['kind'];

/** The take an event concerns, as the deck holding it saw it. */
export interface PlaybackTakeState {
	takeId: string | null;
	position: number;
	readyState: number;
	deck: PlaybackDiagnosticEvent['deck'];
}

/** One thing that happened; `take` is null for an event of the page alone. */
export interface PlaybackNote {
	kind: PlaybackDiagnosticKind;
	detail: string;
	take: PlaybackTakeState | null;
}

interface SessionFacts {
	session_id: string;
	mse_mp3_supported: boolean;
	was_discarded: boolean;
}

interface BufferedEvent {
	session: SessionFacts;
	event: PlaybackDiagnosticEvent;
}

interface Recording {
	userId: string;
	session: SessionFacts;
	events: BufferedEvent[];
	inFlight: Set<BufferedEvent>;
}

const ENDPOINT = '/api/playback-diagnostics';
const STORAGE_KEY_PREFIX = 'playbackDiagnostics:';
const BUFFER_CAPACITY = 500;
// Browsers refuse keepalive requests once the bodies in flight pass 64 KiB
// together; a report of 100 events stays far below that.
const EVENTS_PER_REPORT = 100;
const HEARTBEAT_MS = 15_000;
const TIMER_GAP_MS = 30_000;
const DETAIL_MAX_LENGTH = 200;
const USER_AGENT_MAX_LENGTH = 512;
const MP3_MIME_TYPE = 'audio/mpeg';
// Answers that say "not now" rather than "never": a refused session, a rate
// limit or a failing server keeps the events for a later send. Any other
// refusal would refuse the same report again.
const STATUSES_KEEPING_THE_EVENTS: ReadonlySet<number> = new Set([401, 403, 429]);

const NO_TAKE: PlaybackTakeState = { takeId: null, position: 0, readyState: 0, deck: 'active' };

let recording: Recording | null = null;

/**
 * Records for `userId` until the returned stop is called, and sends what an
 * earlier page of the same user left behind. Another user's events stay
 * where they are: they are only ever sent under their own sign-in.
 */
export function startPlaybackDiagnostics(userId: string): () => void {
	const started: Recording = {
		userId,
		session: bootFacts(),
		events: readEvents(userId),
		inFlight: new Set()
	};
	recording = started;
	const stopWatching = watchThePage();
	sendWaitingEvents(started, { keepalive: false });
	return () => {
		stopWatching();
		if (recording === started) recording = null;
	};
}

export function recordPlaybackEvent(note: PlaybackNote): void {
	if (recording === null) return;
	recording.events.push({ session: recording.session, event: eventOf(note) });
	if (recording.events.length > BUFFER_CAPACITY)
		recording.events.splice(0, recording.events.length - BUFFER_CAPACITY);
	writeEvents(recording);
}

/** Drops what was recorded for `userId` and records nothing more for them. */
export function forgetPlaybackDiagnostics(userId: string): void {
	removeStorage(storageKey(userId));
	if (recording?.userId === userId) recording = null;
}

function bootFacts(): SessionFacts {
	return {
		session_id: crypto.randomUUID(),
		mse_mp3_supported:
			typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(MP3_MIME_TYPE),
		was_discarded: (document as Document & { wasDiscarded?: boolean }).wasDiscarded === true
	};
}

function eventOf(note: PlaybackNote): PlaybackDiagnosticEvent {
	const take = note.take ?? NO_TAKE;
	return {
		at_ms: Math.round(performance.now()),
		kind: note.kind,
		take_id: take.takeId,
		position: Number.isFinite(take.position) && take.position > 0 ? take.position : 0,
		ready_state: take.readyState,
		deck: take.deck,
		visibility: document.visibilityState === 'hidden' ? 'hidden' : 'visible',
		detail: note.detail.slice(0, DETAIL_MAX_LENGTH)
	};
}

function recordPageEvent(kind: PlaybackDiagnosticKind, detail = ''): void {
	recordPlaybackEvent({ kind, detail, take: null });
}

// A hidden page may be frozen or killed before an ordinary request answers,
// so only these last sends ask the browser to finish them on its own.
function sendBeforeThePageGoes(): void {
	if (recording !== null) sendWaitingEvents(recording, { keepalive: true });
}

function watchThePage(): () => void {
	const onVisibilityChange = () => {
		recordPageEvent('visibility_change', document.visibilityState);
		if (document.visibilityState === 'hidden') sendBeforeThePageGoes();
	};
	const onPageHide = (event: PageTransitionEvent) => {
		recordPageEvent('page_hide', `persisted=${event.persisted}`);
		sendBeforeThePageGoes();
	};
	const onPageShow = (event: PageTransitionEvent) =>
		recordPageEvent('page_show', `persisted=${event.persisted}`);
	const onFreeze = () => recordPageEvent('freeze');
	const onResume = () => recordPageEvent('resume');
	const onOnline = () => recordPageEvent('online');
	const onOffline = () => recordPageEvent('offline');

	document.addEventListener('visibilitychange', onVisibilityChange);
	document.addEventListener('freeze', onFreeze);
	document.addEventListener('resume', onResume);
	window.addEventListener('pagehide', onPageHide);
	window.addEventListener('pageshow', onPageShow);
	window.addEventListener('online', onOnline);
	window.addEventListener('offline', onOffline);
	const stopHeartbeat = startHeartbeat();
	return () => {
		stopHeartbeat();
		document.removeEventListener('visibilitychange', onVisibilityChange);
		document.removeEventListener('freeze', onFreeze);
		document.removeEventListener('resume', onResume);
		window.removeEventListener('pagehide', onPageHide);
		window.removeEventListener('pageshow', onPageShow);
		window.removeEventListener('online', onOnline);
		window.removeEventListener('offline', onOffline);
	};
}

// A timer that fires far later than it asked for means the page did not run
// in between: frozen, throttled, or the device slept.
function startHeartbeat(): () => void {
	let lastBeat = Date.now();
	const heartbeat = setInterval(() => {
		const now = Date.now();
		const elapsed = now - lastBeat;
		lastBeat = now;
		if (elapsed > TIMER_GAP_MS) recordPageEvent('timer_gap', `elapsed_ms=${elapsed}`);
	}, HEARTBEAT_MS);
	return () => clearInterval(heartbeat);
}

function sendWaitingEvents(from: Recording, opts: { keepalive: boolean }): void {
	const waiting = from.events.filter((buffered) => !from.inFlight.has(buffered));
	for (const batch of reportBatches(waiting)) void deliver(from, batch, opts.keepalive);
}

// One report speaks for one page session, so a batch never mixes sessions.
function reportBatches(events: BufferedEvent[]): BufferedEvent[][] {
	const batches: BufferedEvent[][] = [];
	for (const buffered of events) {
		const batch = batches.at(-1);
		const joins =
			batch !== undefined &&
			batch.length < EVENTS_PER_REPORT &&
			batch[0].session.session_id === buffered.session.session_id;
		if (joins) batch.push(buffered);
		else batches.push([buffered]);
	}
	return batches;
}

async function deliver(from: Recording, batch: BufferedEvent[], keepalive: boolean): Promise<void> {
	for (const buffered of batch) from.inFlight.add(buffered);
	const done = await post(reportOf(batch), keepalive);
	for (const buffered of batch) from.inFlight.delete(buffered);
	if (!done) return;
	const sent = new Set(batch);
	from.events = from.events.filter((buffered) => !sent.has(buffered));
	if (recording === from) writeEvents(from);
}

function reportOf(batch: BufferedEvent[]): PlaybackDiagnosticsReport {
	return {
		...batch[0].session,
		user_agent: navigator.userAgent.slice(0, USER_AGENT_MAX_LENGTH),
		events: batch.map((buffered) => buffered.event)
	};
}

async function post(report: PlaybackDiagnosticsReport, keepalive: boolean): Promise<boolean> {
	const init = addCsrfToken(
		{
			method: 'POST',
			credentials: 'include',
			keepalive,
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(report)
		},
		'POST'
	);
	try {
		const response = await fetch(ENDPOINT, init);
		return response.status < 500 && !STATUSES_KEEPING_THE_EVENTS.has(response.status);
	} catch {
		return false;
	}
}

function storageKey(userId: string): string {
	return `${STORAGE_KEY_PREFIX}${userId}`;
}

function readEvents(userId: string): BufferedEvent[] {
	const stored = readStorage(storageKey(userId));
	if (stored === null) return [];
	try {
		const parsed: unknown = JSON.parse(stored);
		return Array.isArray(parsed) ? parsed.filter(isBufferedEvent).slice(-BUFFER_CAPACITY) : [];
	} catch {
		return [];
	}
}

function isBufferedEvent(value: unknown): value is BufferedEvent {
	if (typeof value !== 'object' || value === null) return false;
	const { session, event } = value as Partial<BufferedEvent>;
	return typeof session?.session_id === 'string' && typeof event === 'object' && event !== null;
}

function writeEvents(from: Recording): void {
	writeStorage(storageKey(from.userId), JSON.stringify(from.events));
}

// Storage a private window or a full quota refuses keeps the events in
// memory only: the recorder must never break the player it watches.
function readStorage(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function writeStorage(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		// Kept in memory; see readStorage.
	}
}

function removeStorage(key: string): void {
	try {
		localStorage.removeItem(key);
	} catch {
		// Storage that cannot be reached holds nothing to forget.
	}
}
