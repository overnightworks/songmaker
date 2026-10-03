import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContinuousDeck, TakeNotAppended } from './continuousDeck';

const MEGABYTE = 1024 * 1024;
// The size FakeNetwork hands a response body out in, unless the link is slow.
const PIECE = 256 * 1024;
// What a link barely faster than the take's bitrate delivers in a second.
const SLOW_PIECE = 12_000;
const BYTES_PER_SECOND = 16_000;
const OBJECT_URL = 'blob:continuous-deck';

function secondsOf(bytes: number): number {
	return bytes / BYTES_PER_SECOND;
}

class FakeTimeRanges {
	constructor(private readonly span: readonly [number, number] | null) {}

	get length(): number {
		return this.span ? 1 : 0;
	}

	start(): number {
		if (!this.span) throw new RangeError('no buffered range');
		return this.span[0];
	}

	end(): number {
		if (!this.span) throw new RangeError('no buffered range');
		return this.span[1];
	}
}

// Behaves like a SourceBuffer for 'audio/mpeg': generated timestamps, so
// timestampOffset always sits at the end of what has been appended.
class FakeSourceBuffer extends EventTarget {
	mode: AppendMode = 'segments';
	timestampOffset = 0;
	updating = false;
	autoSettle = true;
	quotaRefusals = 0;
	undecodable = false;
	readonly appended: Uint8Array[] = [];
	readonly removals: [number, number][] = [];
	private span: [number, number] | null = null;
	private pending: (() => void) | null = null;

	constructor(private readonly log: string[]) {
		super();
	}

	get buffered(): FakeTimeRanges {
		return new FakeTimeRanges(this.span);
	}

	appendBuffer(data: Uint8Array): void {
		this.beginUpdate();
		if (this.quotaRefusals > 0) {
			this.quotaRefusals -= 1;
			this.updating = false;
			throw new DOMException('buffer full', 'QuotaExceededError');
		}
		this.log.push('append');
		this.dispatchEvent(new Event('updatestart'));
		this.pending = () => {
			const end = this.timestampOffset + secondsOf(data.byteLength);
			this.span = [this.span?.[0] ?? this.timestampOffset, end];
			this.timestampOffset = end;
			this.appended.push(data);
		};
		this.scheduleSettle();
	}

	abort(): void {
		this.log.push('abort');
	}

	remove(start: number, end: number): void {
		this.beginUpdate();
		this.removals.push([start, end]);
		this.dispatchEvent(new Event('updatestart'));
		this.pending = () => {
			if (this.span) this.span = [Math.max(this.span[0], end), this.span[1]];
		};
		this.scheduleSettle();
	}

	settle(): void {
		const pending = this.pending;
		if (!pending) throw new Error('no update in flight');
		this.pending = null;
		pending();
		this.updating = false;
		if (this.undecodable) this.dispatchEvent(new Event('error'));
		this.dispatchEvent(new Event('updateend'));
	}

	untilUpdateStarts(): Promise<void> {
		return new Promise((resolve) =>
			this.addEventListener('updatestart', () => resolve(), { once: true })
		);
	}

	appendedBytes(): number[] {
		return this.appended.map((chunk) => chunk.byteLength);
	}

	private beginUpdate(): void {
		if (this.updating) throw new DOMException('still updating', 'InvalidStateError');
		this.updating = true;
	}

	private scheduleSettle(): void {
		if (this.autoSettle) queueMicrotask(() => this.settle());
	}
}

// Its duration stays unknown while takes are appended, so the browser lets the
// element seek from 0 to the end of what is buffered; once a live seekable
// range is set, from the earliest to the latest point of that range and the
// buffer together.
class FakeMediaSource extends EventTarget {
	readonly mimeTypes: string[] = [];
	readonly buffer: FakeSourceBuffer;
	readyState: ReadyState = 'closed';
	private liveSeekable: readonly [number, number] | null = null;

	constructor(private readonly log: string[]) {
		super();
		this.buffer = new FakeSourceBuffer(log);
	}

	addSourceBuffer(mimeType: string): FakeSourceBuffer {
		this.mimeTypes.push(mimeType);
		return this.buffer;
	}

	endOfStream(): void {
		if (this.buffer.updating) throw new DOMException('still updating', 'InvalidStateError');
		this.readyState = 'ended';
		this.log.push('endOfStream');
	}

	open(): void {
		this.readyState = 'open';
		this.dispatchEvent(new Event('sourceopen'));
	}

	setLiveSeekableRange(start: number, end: number): void {
		if (this.readyState !== 'open') throw new DOMException('not open', 'InvalidStateError');
		if (start < 0 || start > end) throw new TypeError('invalid live seekable range');
		this.liveSeekable = [start, end];
	}

	clearLiveSeekableRange(): void {
		if (this.readyState !== 'open') throw new DOMException('not open', 'InvalidStateError');
		this.liveSeekable = null;
	}

	seekable(): readonly [number, number] {
		const buffered = this.buffer.buffered;
		const bufferedEnd = buffered.length ? buffered.end() : 0;
		if (!this.liveSeekable) return [0, bufferedEnd];
		const [liveStart, liveEnd] = this.liveSeekable;
		if (!buffered.length) return [liveStart, liveEnd];
		return [Math.min(liveStart, buffered.start()), Math.max(liveEnd, bufferedEnd)];
	}
}

class FakeAudio extends EventTarget {
	src = '';
	private position = 0;
	private readonly playbackWatchers: (() => void)[] = [];

	constructor(private readonly mediaSource: FakeMediaSource) {
		super();
	}

	get currentTime(): number {
		return this.position;
	}

	// Like a browser, a seek lands at the nearest point of the seekable range.
	set currentTime(seconds: number) {
		const [start, end] = this.mediaSource.seekable();
		this.position = Math.min(Math.max(seconds, start), end);
		this.dispatchEvent(new Event('seeking'));
	}

	override addEventListener(
		type: string,
		listener: EventListenerOrEventListenerObject | null,
		options?: AddEventListenerOptions | boolean
	): void {
		super.addEventListener(type, listener, options);
		if (type === 'timeupdate') for (const notify of this.playbackWatchers.splice(0)) notify();
	}

	untilDeckWaitsForPlayback(): Promise<void> {
		return new Promise((resolve) => this.playbackWatchers.push(resolve));
	}

	playTo(seconds: number): void {
		this.position = seconds;
		this.dispatchEvent(new Event('timeupdate'));
	}
}

interface TakeRequest {
	url: string;
	range: string | null;
}

// How a resume is answered instead of from the byte it asked for.
interface RangeAnswer {
	status: number;
	fromTheStart?: boolean;
	withoutContentRange?: boolean;
}

interface Answer {
	status: number;
	bodyCancelled: boolean;
}

// Where a response body stops: a break errors the stream, a stall stops
// sending and waits until its request is aborted.
interface Cut {
	at: number;
	stalls: boolean;
}

class FakeNetwork {
	readonly requests: TakeRequest[] = [];
	readonly signals: AbortSignal[] = [];
	readonly answers: Answer[] = [];
	private readonly files = new Map<string, Uint8Array>();
	private readonly cuts = new Map<string, Cut[]>();
	private readonly refusals = new Map<string, number>();
	private readonly refusalsWithAnErroredBody = new Set<string>();
	private readonly rangeAnswers = new Map<string, RangeAnswer>();
	private pieceBytes = PIECE;

	slowLink(): void {
		this.pieceBytes = SLOW_PIECE;
	}

	serve(url: string, bytes: number): Uint8Array {
		const file = Uint8Array.from({ length: bytes }, (_, index) => index % 251);
		this.files.set(url, file);
		return file;
	}

	breakAt(url: string, ...filePositions: number[]): void {
		this.cutAt(url, filePositions, false);
	}

	stallAt(url: string, ...filePositions: number[]): void {
		this.cutAt(url, filePositions, true);
	}

	refuse(url: string, status: number, { bodyErrored = false } = {}): void {
		this.refusals.set(url, status);
		if (bodyErrored) this.refusalsWithAnErroredBody.add(url);
	}

	answerRanges(url: string, answer: RangeAnswer): void {
		this.rangeAnswers.set(url, answer);
	}

	readonly fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
		const url = String(input);
		const range = new Headers(init?.headers).get('Range');
		this.requests.push({ url, range });
		if (init?.signal) this.signals.push(init.signal);
		const refusal = this.refusals.get(url);
		if (refusal)
			return new Response(this.refusalsWithAnErroredBody.has(url) ? erroredBody() : null, {
				status: refusal
			});
		const file = this.files.get(url);
		if (!file) throw new TypeError(`no file served at ${url}`);
		const rangeAnswer = range ? this.rangeAnswers.get(url) : undefined;
		const from =
			range && !rangeAnswer?.fromTheStart ? Number(/^bytes=(\d+)-$/.exec(range)?.[1]) : 0;
		const status = rangeAnswer?.status ?? (range ? 206 : 200);
		const cut = this.cuts.get(url)?.shift();
		const headers: Record<string, string> =
			status === 206 && !rangeAnswer?.withoutContentRange
				? { 'Content-Range': `bytes ${from}-${file.byteLength - 1}/${file.byteLength}` }
				: {};
		const answer: Answer = { status, bodyCancelled: false };
		this.answers.push(answer);
		return new Response(
			piecewise(file.subarray(from, cut?.at), {
				pieceBytes: this.pieceBytes,
				end: cut === undefined ? 'closes' : cut.stalls ? 'stalls' : 'breaks',
				signal: init?.signal,
				cancelled: () => {
					answer.bodyCancelled = true;
				}
			}),
			{ status, headers }
		);
	};

	private cutAt(url: string, filePositions: number[], stalls: boolean): void {
		this.cuts.set(url, [
			...(this.cuts.get(url) ?? []),
			...filePositions.map((at) => ({ at, stalls }))
		]);
	}
}

function erroredBody(): ReadableStream<Uint8Array> {
	return new ReadableStream({
		start(controller) {
			controller.error(new TypeError('connection reset'));
		}
	});
}

interface PiecewiseOptions {
	pieceBytes: number;
	end: 'closes' | 'breaks' | 'stalls';
	signal: AbortSignal | null | undefined;
	cancelled: () => void;
}

// Like a fetch body, the stream errors with the abort reason once its request is aborted.
function piecewise(
	bytes: Uint8Array,
	{ pieceBytes, end, signal, cancelled }: PiecewiseOptions
): ReadableStream<Uint8Array> {
	let offset = 0;
	return new ReadableStream({
		cancel: cancelled,
		pull(controller) {
			if (signal?.aborted) {
				controller.error(signal.reason);
				return;
			}
			if (offset >= bytes.byteLength) {
				if (end === 'stalls')
					return untilAborted(signal).then(() => controller.error(signal?.reason));
				if (end === 'breaks') controller.error(new TypeError('network connection lost'));
				else controller.close();
				return;
			}
			controller.enqueue(bytes.slice(offset, offset + pieceBytes));
			offset += pieceBytes;
		}
	});
}

function untilAborted(signal: AbortSignal | null | undefined): Promise<void> {
	return new Promise((resolve) =>
		signal?.addEventListener('abort', () => resolve(), { once: true })
	);
}

interface Rig {
	deck: ContinuousDeck<string>;
	audio: FakeAudio;
	mediaSource: FakeMediaSource;
	buffer: FakeSourceBuffer;
	network: FakeNetwork;
	log: string[];
	revoked: string[];
}

function openDeck(): Rig {
	const log: string[] = [];
	const mediaSource = new FakeMediaSource(log);
	const audio = new FakeAudio(mediaSource);
	const network = new FakeNetwork();
	const revoked: string[] = [];
	const urls = {
		createObjectURL: () => {
			queueMicrotask(() => mediaSource.open());
			return OBJECT_URL;
		},
		revokeObjectURL: (url: string) => {
			revoked.push(url);
		}
	};
	const deck = ContinuousDeck.attach<string>({
		element: audio as unknown as HTMLMediaElement,
		mediaSource: mediaSource as unknown as MediaSource,
		urls,
		fetch: network.fetch
	});
	return { deck, audio, mediaSource, buffer: mediaSource.buffer, network, log, revoked };
}

function concatenated(chunks: Uint8Array[]): Uint8Array {
	const whole = new Uint8Array(chunks.reduce((size, chunk) => size + chunk.byteLength, 0));
	let offset = 0;
	for (const chunk of chunks) {
		whole.set(chunk, offset);
		offset += chunk.byteLength;
	}
	return whole;
}

// A deep toEqual walks a typed array one element at a time, which takes
// seconds for a take-sized file under coverage instrumentation.
function firstDifferingByte(actual: Uint8Array, expected: Uint8Array): number | null {
	const shorter = Math.min(actual.byteLength, expected.byteLength);
	for (let index = 0; index < shorter; index += 1) {
		if (actual[index] !== expected[index]) return index;
	}
	return actual.byteLength === expected.byteLength ? null : shorter;
}

// Lets every request, body piece and append already on its way run to where it waits.
function quiet(): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, 0));
}

function settlement(step: Promise<void>): { settled: boolean } {
	const state = { settled: false };
	step.then(
		() => (state.settled = true),
		() => (state.settled = true)
	);
	return state;
}

describe('ContinuousDeck', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('attaches one audio/mpeg buffer in sequence mode to the element', async () => {
		const { deck, audio, mediaSource, buffer, revoked } = openDeck();
		await deck.endStream();

		expect(audio.src).toBe(OBJECT_URL);
		expect(revoked).toEqual([OBJECT_URL]);
		expect(mediaSource.mimeTypes).toEqual(['audio/mpeg']);
		expect(buffer.mode).toBe('sequence');
	});

	const withLiveSeekableRange = { setLiveSeekableRange: () => undefined };
	it.each([
		{ browser: 'no media source', mediaSource: undefined, supported: false },
		{
			browser: 'no MP3',
			mediaSource: { isTypeSupported: () => false, prototype: withLiveSeekableRange },
			supported: false
		},
		{
			browser: 'MP3 without a live seekable range',
			mediaSource: { isTypeSupported: (type: string) => type === 'audio/mpeg', prototype: {} },
			supported: false
		},
		{
			browser: 'MP3 with a live seekable range',
			mediaSource: {
				isTypeSupported: (type: string) => type === 'audio/mpeg',
				prototype: withLiveSeekableRange
			},
			supported: true
		}
	])('reports support as $supported for $browser', ({ mediaSource, supported }) => {
		vi.stubGlobal('MediaSource', mediaSource);

		expect(ContinuousDeck.isSupported()).toBe(supported);
	});

	it('appends two takes back to back, each starting where the previous ended', async () => {
		const { deck, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);

		await Promise.all([
			deck.appendTake('first', '/audio/first.mp3'),
			deck.appendTake('second', '/audio/second.mp3')
		]);

		expect(deck.manifest).toEqual([
			{ take: 'first', start_offset: 0, duration: secondsOf(MEGABYTE / 2) },
			{
				take: 'second',
				start_offset: secondsOf(MEGABYTE / 2),
				duration: secondsOf(MEGABYTE / 4)
			}
		]);
	});

	it('appends each piece as it arrives while little is buffered ahead, so a slow link keeps the buffer growing', async () => {
		const { deck, buffer, network } = openDeck();
		network.slowLink();
		network.serve('/audio/take.mp3', 20 * SLOW_PIECE);

		await deck.appendTake('take', '/audio/take.mp3');

		expect(buffer.appendedBytes()).toEqual(Array(20).fill(SLOW_PIECE));
	});

	it('gathers one-megabyte chunks once plenty is buffered ahead, and waits while a minute is', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 2.5 * MEGABYTE);

		const appending = deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, MEGABYTE]);

		audio.playTo(50);
		await appending;
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, MEGABYTE, MEGABYTE]);
	});

	it('waits for room ahead without leaving a listener on the close signal per timeupdate', async () => {
		const { deck, audio, network } = openDeck();
		network.serve('/audio/long.mp3', 2.5 * MEGABYTE);
		void deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		await quiet();
		let abortListeners = 0;
		const added = vi.spyOn(AbortSignal.prototype, 'addEventListener');
		const removed = vi.spyOn(AbortSignal.prototype, 'removeEventListener');

		for (let second = 1; second <= 20; second += 1) {
			const waitsAgain = audio.untilDeckWaitsForPlayback();
			audio.playTo(second);
			await waitsAgain;
		}
		await quiet();

		for (const [type] of added.mock.calls) if (type === 'abort') abortListeners += 1;
		for (const [type] of removed.mock.calls) if (type === 'abort') abortListeners -= 1;
		expect(added.mock.calls.length).toBeGreaterThan(0);
		expect(abortListeners).toBe(0);
	});

	it('appends the first piece before the rest of the take has arrived', async () => {
		const { deck, buffer, network } = openDeck();
		network.serve('/audio/take.mp3', MEGABYTE / 2);
		buffer.autoSettle = false;

		const appending = deck.appendTake('take', '/audio/take.mp3');
		await buffer.untilUpdateStarts();

		expect(network.requests).toHaveLength(1);
		const rest = buffer.untilUpdateStarts();
		buffer.settle();
		await rest;
		expect(buffer.appendedBytes()).toEqual([PIECE]);
		buffer.settle();
		await appending;
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE]);
	});

	it('lets a seek past what has arrived wait there, appending the take up to a minute beyond it', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 5 * MEGABYTE);
		void deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.buffered.end()).toBeLessThan(200);

		deck.seekTo(200);
		await audio.untilDeckWaitsForPlayback();

		expect(audio.currentTime).toBe(200);
		expect(buffer.buffered.end()).toBeGreaterThanOrEqual(260);
		expect(buffer.buffered.end()).toBeLessThan(secondsOf(5 * MEGABYTE));
	});

	it('starts the next append only after the previous one fired updateend', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 3 * PIECE);
		audio.playTo(1000);
		buffer.autoSettle = false;

		const appending = deck.appendTake('long', '/audio/long.mp3');
		await buffer.untilUpdateStarts();
		expect(buffer.updating).toBe(true);
		expect(buffer.appendedBytes()).toEqual([]);

		const nextAppend = buffer.untilUpdateStarts();
		buffer.settle();
		await nextAppend;
		expect(buffer.updating).toBe(true);
		expect(buffer.appendedBytes()).toEqual([PIECE]);

		const lastAppend = buffer.untilUpdateStarts();
		buffer.settle();
		await lastAppend;
		buffer.settle();
		await appending;
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, PIECE]);
	});

	it('removes takes that have played and keeps the take under the playhead', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', 2 * MEGABYTE);

		void deck.appendTake('first', '/audio/first.mp3');
		const second = deck.appendTake('second', '/audio/second.mp3');
		await audio.untilDeckWaitsForPlayback();
		audio.playTo(20);
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.removals).toEqual([]);

		audio.playTo(60);
		await second;
		expect(buffer.removals).toEqual([[0, secondsOf(MEGABYTE / 2)]]);
		expect(buffer.buffered.start()).toBe(secondsOf(MEGABYTE / 2));
	});

	it('frees what has played of the current take when the buffer is full, then appends', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.playTo(25);
		buffer.quotaRefusals = 1;

		await deck.appendTake('second', '/audio/second.mp3');

		expect(buffer.removals).toEqual([[0, 15]]);
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, PIECE]);
	});

	it('stops a scrub where the arrived audio ends, even while a seek waits further on', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 5 * MEGABYTE);
		void deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		deck.seekTo(200);

		deck.scrubTo(250);

		expect(audio.currentTime).toBe(buffer.buffered.end());
		expect(audio.currentTime).toBeLessThan(200);
	});

	it('lets a seek back before what a full buffer freed land where the kept audio starts', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.playTo(25);
		buffer.quotaRefusals = 1;
		await deck.appendTake('second', '/audio/second.mp3');
		expect(buffer.buffered.start()).toBe(15);

		deck.seekTo(5);

		expect(audio.currentTime).toBe(15);
	});

	it('reports a full buffer that freeing played audio could not cure', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.playTo(25);
		buffer.quotaRefusals = 2;

		await expect(deck.appendTake('second', '/audio/second.mp3')).rejects.toMatchObject({
			name: 'QuotaExceededError'
		});
	});

	it('resumes a broken download from the byte already received', async () => {
		const { deck, audio, buffer, network } = openDeck();
		const file = network.serve('/audio/take.mp3', 0.75 * MEGABYTE);
		network.breakAt('/audio/take.mp3', 300_000);

		await deck.appendTake('take', '/audio/take.mp3');

		expect(network.requests).toEqual([
			{ url: '/audio/take.mp3', range: null },
			{ url: '/audio/take.mp3', range: 'bytes=300000-' }
		]);
		expect(firstDifferingByte(concatenated(buffer.appended), file)).toBeNull();
		expect(audio.src).toBe(OBJECT_URL);
	});

	it.each([
		{
			answer: { status: 206, fromTheStart: true },
			refusal: 'Content-Range mismatch: asked from byte 300000'
		},
		{ answer: { status: 200 }, refusal: 'ignored Range' },
		{ answer: { status: 503 }, refusal: 'answered 503' },
		{ answer: { status: 206, withoutContentRange: true }, refusal: 'missing Content-Range' }
	])(
		'refuses a resume answered $answer as $refusal, stops its download and appends nothing twice',
		async ({ answer, refusal }) => {
			const { deck, buffer, network } = openDeck();
			const file = network.serve('/audio/take.mp3', 0.75 * MEGABYTE);
			network.breakAt('/audio/take.mp3', 300_000);
			network.answerRanges('/audio/take.mp3', answer);

			const step = deck.appendTake('take', '/audio/take.mp3');

			await expect(step).rejects.toMatchObject({ reason: 'refused' });
			await expect(step).rejects.toThrow(refusal);
			expect(network.requests.map((request) => request.range)).toEqual([null, 'bytes=300000-']);
			expect(network.answers.at(-1)).toEqual({ status: answer.status, bodyCancelled: true });
			const appended = concatenated(buffer.appended);
			expect(appended.byteLength).toBeLessThanOrEqual(300_000);
			expect(firstDifferingByte(appended, file.subarray(0, appended.byteLength))).toBeNull();
		}
	);

	it('parks a take whose download fails on the network and resumes it from the bytes received, the next take waiting behind it', async () => {
		const { deck, buffer, network } = openDeck();
		const file = network.serve('/audio/take.mp3', MEGABYTE / 2);
		network.serve('/audio/next.mp3', MEGABYTE / 4);
		network.breakAt('/audio/take.mp3', 100_000, 200_000, 300_000);

		const take = deck.appendTake('take', '/audio/take.mp3');
		const next = deck.appendTake('next', '/audio/next.mp3');
		const taken = settlement(take);
		await quiet();

		expect(taken.settled).toBe(false);
		expect(deck.appending).toBe(true);
		expect(network.requests.map((request) => request.range)).toEqual([
			null,
			'bytes=100000-',
			'bytes=200000-'
		]);
		expect(concatenated(buffer.appended).byteLength).toBe(300_000);

		deck.retryDownload();
		await Promise.all([take, next]);

		expect(network.requests.map(({ url, range }) => `${url} ${range}`)).toEqual([
			'/audio/take.mp3 null',
			'/audio/take.mp3 bytes=100000-',
			'/audio/take.mp3 bytes=200000-',
			'/audio/take.mp3 bytes=300000-',
			'/audio/next.mp3 null'
		]);
		const appended = concatenated(buffer.appended);
		expect(firstDifferingByte(appended.subarray(0, file.byteLength), file)).toBeNull();
		expect(deck.manifest.map((entry) => entry.take)).toEqual(['take', 'next']);
	});

	it('a retry aborts a request that stopped sending and resumes from the bytes received', async () => {
		const { deck, audio, buffer, network } = openDeck();
		const file = network.serve('/audio/take.mp3', MEGABYTE / 2);
		network.stallAt('/audio/take.mp3', PIECE);

		const take = deck.appendTake('take', '/audio/take.mp3');
		await quiet();
		expect(buffer.appendedBytes()).toEqual([PIECE]);

		deck.retryDownload();
		await take;

		expect(network.signals[0].aborted).toBe(true);
		expect(network.requests.map((request) => request.range)).toEqual([null, `bytes=${PIECE}-`]);
		expect(firstDifferingByte(concatenated(buffer.appended), file)).toBeNull();
		expect(audio.src).toBe(OBJECT_URL);
	});

	it('still drops a refused take without retrying it, names it, and appends the next take where it would have started', async () => {
		const { deck, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 4);
		network.serve('/audio/third.mp3', MEGABYTE / 4);
		network.refuse('/audio/gone.mp3', 404);

		void deck.appendTake('first', '/audio/first.mp3');
		const dropped = deck.appendTake('gone', '/audio/gone.mp3');
		const third = deck.appendTake('third', '/audio/third.mp3');

		await expect(dropped).rejects.toMatchObject({ take: 'gone', reason: 'refused' });
		await expect(dropped).rejects.toThrow('404');
		await third;
		expect(network.requests.filter((request) => request.url === '/audio/gone.mp3')).toHaveLength(1);
		expect(deck.manifest).toEqual([
			{ take: 'first', start_offset: 0, duration: secondsOf(MEGABYTE / 4) },
			{
				take: 'third',
				start_offset: secondsOf(MEGABYTE / 4),
				duration: secondsOf(MEGABYTE / 4)
			}
		]);
	});

	it('drops a refused take whose body cannot be cancelled, naming both the refusal and the failed cancel', async () => {
		const { deck, network } = openDeck();
		network.refuse('/audio/gone.mp3', 404, { bodyErrored: true });

		const dropped = deck.appendTake('gone', '/audio/gone.mp3');

		await expect(dropped).rejects.toMatchObject({ take: 'gone', reason: 'refused' });
		await expect(dropped).rejects.toThrow(/answered 404.*connection reset/);
		expect(network.requests).toHaveLength(1);
	});

	it('keeps what a take cut off part-way appended and starts the next take on a fresh frame', async () => {
		const { deck, log, network } = openDeck();
		network.serve('/audio/cut.mp3', MEGABYTE / 2);
		network.breakAt('/audio/cut.mp3', PIECE);
		network.answerRanges('/audio/cut.mp3', { status: 200 });
		network.serve('/audio/next.mp3', MEGABYTE / 4);

		const cut = deck.appendTake('cut', '/audio/cut.mp3');
		const next = deck.appendTake('next', '/audio/next.mp3');

		await expect(cut).rejects.toBeInstanceOf(TakeNotAppended);
		await next;
		expect(log).toEqual(['append', 'abort', 'append']);
		expect(deck.manifest).toEqual([
			{ take: 'cut', start_offset: 0, duration: secondsOf(PIECE) },
			{ take: 'next', start_offset: secondsOf(PIECE), duration: secondsOf(MEGABYTE / 4) }
		]);
	});

	it('fails every later step once the buffer refused audio', async () => {
		const { deck, buffer, network } = openDeck();
		network.serve('/audio/broken.mp3', MEGABYTE / 4);
		network.serve('/audio/next.mp3', MEGABYTE / 4);
		buffer.undecodable = true;

		const broken = deck.appendTake('broken', '/audio/broken.mp3');
		const next = deck.appendTake('next', '/audio/next.mp3');

		await expect(broken).rejects.toThrow('refused the appended audio');
		await expect(next).rejects.toThrow('refused the appended audio');
	});

	it('refuses a take asked for after the end of the stream', async () => {
		const { deck, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 4);
		network.serve('/audio/late.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		void deck.endStream();

		await expect(deck.appendTake('late', '/audio/late.mp3')).rejects.toMatchObject({
			take: 'late',
			reason: 'stream-ended'
		});
		expect(network.requests.map((request) => request.url)).toEqual(['/audio/first.mp3']);
	});

	it('reports itself appending until every take it was given is in the buffer', async () => {
		const { deck, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 4);
		network.serve('/audio/second.mp3', MEGABYTE / 4);

		void deck.appendTake('first', '/audio/first.mp3');
		const second = deck.appendTake('second', '/audio/second.mp3');
		expect(deck.appending).toBe(true);

		await second;
		expect(deck.appending).toBe(false);
	});

	it('finds the take under the playhead and the takes still playable from their start', async () => {
		const { deck, audio, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		const secondStart = secondsOf(MEGABYTE / 2);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.playTo(secondStart + 1);

		await deck.appendTake('second', '/audio/second.mp3');

		expect(deck.entryAt(secondStart - 1)?.take).toBe('first');
		expect(deck.entryAt(secondStart)?.take).toBe('second');
		const [firstEntry, secondEntry] = deck.manifest;
		expect(deck.isPlayableFromStart(secondEntry)).toBe(true);
		expect(deck.isPlayableFromStart(firstEntry)).toBe(false);
	});

	describe('once closed', () => {
		async function expectClosed(step: Promise<void>): Promise<void> {
			const outcome = await step.then(
				() => 'settled',
				(error: unknown) => error
			);
			expect(outcome).toBeInstanceOf(Error);
			expect((outcome as Error).name).toBe('DeckClosed');
			expect(outcome).not.toBeInstanceOf(TakeNotAppended);
		}

		it('aborts the request of the take being fetched and does not report it as dropped', async () => {
			const { deck, buffer, network } = openDeck();
			network.serve('/audio/take.mp3', MEGABYTE / 2);
			buffer.autoSettle = false;
			const appending = deck.appendTake('take', '/audio/take.mp3');
			await buffer.untilUpdateStarts();

			deck.close();
			buffer.settle();

			expect(network.signals.map((signal) => signal.aborted)).toEqual([true]);
			await expectClosed(appending);
			expect(buffer.appendedBytes()).toEqual([PIECE]);
		});

		it('wakes a parked wait and appends nothing more when playback moves on', async () => {
			const { deck, audio, buffer, network } = openDeck();
			network.serve('/audio/long.mp3', 2.5 * MEGABYTE);
			const appending = deck.appendTake('long', '/audio/long.mp3');
			await audio.untilDeckWaitsForPlayback();

			deck.close();
			await expectClosed(appending);
			audio.playTo(100);
			await Promise.resolve();

			expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, MEGABYTE]);
			expect(buffer.removals).toEqual([]);
		});

		it('settles every step queued before it without touching the buffer', async () => {
			const { deck, buffer, log, network } = openDeck();
			network.serve('/audio/first.mp3', MEGABYTE / 2);
			network.serve('/audio/second.mp3', MEGABYTE / 4);
			buffer.autoSettle = false;
			const first = deck.appendTake('first', '/audio/first.mp3');
			const second = deck.appendTake('second', '/audio/second.mp3');
			const ending = deck.endStream();
			await buffer.untilUpdateStarts();

			deck.close();
			buffer.settle();

			await Promise.all([first, second, ending].map(expectClosed));
			expect(log).toEqual(['append']);
			expect(network.requests.map((request) => request.url)).toEqual(['/audio/first.mp3']);
		});

		it('settles a parked download and asks for nothing more', async () => {
			const { deck, network } = openDeck();
			network.serve('/audio/take.mp3', MEGABYTE / 2);
			network.breakAt('/audio/take.mp3', 0, 0, 0);
			const appending = deck.appendTake('take', '/audio/take.mp3');
			await quiet();

			deck.close();
			deck.retryDownload();

			await expectClosed(appending);
			expect(network.requests).toHaveLength(3);
		});

		it('settles a step still waiting for the media source to open', async () => {
			const { deck, network } = openDeck();
			network.serve('/audio/take.mp3', MEGABYTE / 4);
			const appending = deck.appendTake('take', '/audio/take.mp3');

			deck.close();

			await expectClosed(appending);
			expect(network.requests).toEqual([]);
		});
	});

	it('ends the stream only after the last take has been appended', async () => {
		const { deck, log, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 4);
		network.serve('/audio/second.mp3', MEGABYTE / 4);

		void deck.appendTake('first', '/audio/first.mp3');
		void deck.appendTake('second', '/audio/second.mp3');
		await deck.endStream();

		expect(log).toEqual(['append', 'append', 'endOfStream']);
	});
});
