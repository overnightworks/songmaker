import { addCsrfToken } from '$lib/api/fetch';
import type { PlaybackDiagnosticEvent, PlaybackDiagnosticsReport } from '$lib/api/types';
import { PLAYBACK_DIAGNOSTICS_PATH } from '$lib/constants';

// A transient recorder for #1187: what the player and the page did on the
// listener's phone, written down per user on this device so that it survives
// Android killing the page, and told to the server whenever the page hides or
// the app starts again. Deleted together with the endpoint when #1187 closes.

export type PlaybackDiagnosticKind = PlaybackDiagnosticEvent['kind'];

/** The take an event concerns, as the deck holding it saw it. */
interface PlaybackTakeState {
	takeId: string | null;
	position: number;
	readyState: number;
	deck: PlaybackDiagnosticEvent['deck'];
}

/** One thing that happened; `take` is null for an event of the page alone. */
interface PlaybackNote {
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

// The page sleeping through one stretch: consecutive missed heartbeats.
interface TimerGap {
	recorded: BufferedEvent;
	count: number;
	totalMs: number;
}

// Session and sequence name one event across tabs, reloads and the log.
type EventKey = string;

interface Recording {
	userId: string;
	session: SessionFacts;
	nextSequence: number;
	events: BufferedEvent[];
	inFlight: Set<EventKey>;
	taken: Set<EventKey>;
	openGap: TimerGap | null;
}

const STORAGE_KEY_PREFIX = 'playbackDiagnostics:';
const BUFFER_CAPACITY = 500;
const EVENTS_PER_REPORT = 100;
// Browsers refuse a keepalive request once the keepalive bodies in flight pass
// 64 KiB together, so a send before the page goes counts what earlier ones
// still have in flight, stops at that budget and leaves the rest for the next
// start.
const KEEPALIVE_BODY_BUDGET_BYTES = 64 * 1024;
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
let keepaliveBytesInFlight = 0;

/**
 * Records for `userId` until the returned stop is called, and sends what an
 * earlier page of the same user left behind. Another user's events stay
 * where they are: they are only ever sent under their own sign-in.
 */
export function startPlaybackDiagnostics(userId: string): () => void {
	const started: Recording = {
		userId,
		session: bootFacts(),
		nextSequence: 0,
		events: readEvents(userId),
		inFlight: new Set(),
		taken: new Set(),
		openGap: null
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
	const sequence = recording.nextSequence++;
	recording.events.push({ session: recording.session, event: eventOf(note, sequence) });
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

function eventOf(note: PlaybackNote, sequence: number): PlaybackDiagnosticEvent {
	const take = note.take ?? NO_TAKE;
	return {
		sequence,
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
		if (elapsed > TIMER_GAP_MS) recordTimerGap(elapsed);
	}, HEARTBEAT_MS);
	return () => clearInterval(heartbeat);
}

// Chrome's intensive throttling misses a heartbeat every minute of a night, so
// gaps with nothing recorded between them grow one event instead of filling the
// ring and pushing the media evidence out of it.
function recordTimerGap(elapsedMs: number): void {
	if (recording === null) return;
	const gap = recording.openGap;
	if (gap !== null && continuesTheGap(recording, gap)) {
		gap.count += 1;
		gap.totalMs += elapsedMs;
		gap.recorded.event.detail = timerGapDetail(gap);
		writeEvents(recording);
		return;
	}
	recordPageEvent('timer_gap', timerGapDetail({ count: 1, totalMs: elapsedMs }));
	const recorded = recording.events.at(-1);
	if (recorded !== undefined) recording.openGap = { recorded, count: 1, totalMs: elapsedMs };
}

function continuesTheGap(from: Recording, gap: TimerGap): boolean {
	return from.events.at(-1) === gap.recorded && !from.inFlight.has(keyOf(gap.recorded));
}

function timerGapDetail(gap: Pick<TimerGap, 'count' | 'totalMs'>): string {
	return `count=${gap.count} total_ms=${gap.totalMs}`;
}

function sendWaitingEvents(from: Recording, opts: { keepalive: boolean }): void {
	const waiting = from.events.filter((buffered) => !from.inFlight.has(keyOf(buffered)));
	const batches = reportBatches(waiting);
	if (opts.keepalive) handOff(from, batches);
	else for (const batch of batches) void deliver(from, batch);
}

// The page may be gone before the answer comes, so what the browser takes
// over leaves the buffer at once: a reload must not send it a second time.
// Only an answer that reaches a living page puts a refused report back.
function handOff(from: Recording, batches: BufferedEvent[][]): void {
	const handedOff: BufferedEvent[][] = [];
	for (const batch of batches) {
		const body = JSON.stringify(reportOf(batch));
		const bodyBytes = new Blob([body]).size;
		if (keepaliveBytesInFlight + bodyBytes > KEEPALIVE_BODY_BUDGET_BYTES) break;
		keepaliveBytesInFlight += bodyBytes;
		handedOff.push(batch);
		void post(body, true)
			.finally(() => {
				keepaliveBytesInFlight -= bodyBytes;
			})
			.then((done) => {
				if (!done && recording === from) putBack(from, batch);
			});
	}
	if (handedOff.length > 0) takeOut(from, handedOff.flat());
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

async function deliver(from: Recording, batch: BufferedEvent[]): Promise<void> {
	const keys = batch.map(keyOf);
	for (const key of keys) from.inFlight.add(key);
	const done = await post(JSON.stringify(reportOf(batch)), false);
	for (const key of keys) from.inFlight.delete(key);
	if (done && recording === from) takeOut(from, batch);
}

function takeOut(from: Recording, sent: BufferedEvent[]): void {
	const leaving = new Set(sent.map(keyOf));
	from.events = from.events.filter((buffered) => !leaving.has(keyOf(buffered)));
	for (const buffered of sent) if (!isOwn(from, buffered)) from.taken.add(keyOf(buffered));
	writeEvents(from);
}

function putBack(from: Recording, refused: BufferedEvent[]): void {
	for (const buffered of refused) from.taken.delete(keyOf(buffered));
	from.events = [...refused.filter((buffered) => isOwn(from, buffered)), ...from.events];
	writeEvents(from, refused);
}

function isOwn(from: Recording, buffered: BufferedEvent): boolean {
	return buffered.session.session_id === from.session.session_id;
}

function keyOf(buffered: BufferedEvent): EventKey {
	return `${buffered.session.session_id}:${buffered.event.sequence}`;
}

function reportOf(batch: BufferedEvent[]): PlaybackDiagnosticsReport {
	return {
		...batch[0].session,
		user_agent: navigator.userAgent.slice(0, USER_AGENT_MAX_LENGTH),
		events: batch.map((buffered) => buffered.event)
	};
}

async function post(body: string, keepalive: boolean): Promise<boolean> {
	const init = addCsrfToken(
		{
			method: 'POST',
			credentials: 'include',
			keepalive,
			headers: { 'Content-Type': 'application/json' },
			body
		},
		'POST'
	);
	try {
		const response = await fetch(PLAYBACK_DIAGNOSTICS_PATH, init);
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
	return (
		typeof session?.session_id === 'string' &&
		typeof event === 'object' &&
		event !== null &&
		typeof event.sequence === 'number'
	);
}

function writeEvents(from: Recording, reinstated: BufferedEvent[] = []): void {
	from.events = mergedWithStored(from, reinstated).slice(-BUFFER_CAPACITY);
	writeStorage(storageKey(from.userId), JSON.stringify(from.events));
}

// Another tab of the same user writes the same key, so a write starts from
// what is stored now: this page owns its own session's events, storage owns
// everyone else's, minus what this page already sent of them.
function mergedWithStored(from: Recording, reinstated: BufferedEvent[]): BufferedEvent[] {
	const stored = readEvents(from.userId);
	const storedKeys = new Set(stored.map(keyOf));
	for (const key of from.taken) if (!storedKeys.has(key)) from.taken.delete(key);
	const others = [
		...stored.filter((buffered) => !isOwn(from, buffered) && !from.taken.has(keyOf(buffered))),
		...reinstated.filter((buffered) => !isOwn(from, buffered) && !storedKeys.has(keyOf(buffered)))
	];
	const own = from.events.filter((buffered) => isOwn(from, buffered));
	return inSessionOrder([...others, ...own]);
}

function inSessionOrder(events: BufferedEvent[]): BufferedEvent[] {
	const sessions = new Map<string, BufferedEvent[]>();
	for (const buffered of events) {
		const session = sessions.get(buffered.session.session_id);
		if (session === undefined) sessions.set(buffered.session.session_id, [buffered]);
		else session.push(buffered);
	}
	return [...sessions.values()].flatMap((session) =>
		session.sort((a, b) => a.event.sequence - b.event.sequence)
	);
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
