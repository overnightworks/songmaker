import { ContinuousDeck } from './continuousDeck';

export const MEGABYTE = 1024 * 1024;
// The size FakeNetwork hands a response body out in, unless the link is slow.
export const PIECE = 256 * 1024;
// What a link barely faster than the take's bitrate delivers in a second.
export const SLOW_PIECE = 12_000;
const BYTES_PER_SECOND = 16_000;
export const OBJECT_URL = 'blob:continuous-deck';

export function secondsOf(bytes: number): number {
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
			if (!this.span) return;
			this.span =
				start <= this.span[0]
					? [Math.max(this.span[0], end), this.span[1]]
					: [this.span[0], Math.min(this.span[1], start)];
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

	readonly fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
		try {
			return Promise.resolve(this.respond(requestedUrl(input), init));
		} catch (error) {
			return Promise.reject(error);
		}
	};

	private respond(url: string, init?: RequestInit): Response {
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
				end: bodyEnd(cut),
				signal: init?.signal,
				cancelled: () => {
					answer.bodyCancelled = true;
				}
			}),
			{ status, headers }
		);
	}

	private cutAt(url: string, filePositions: number[], stalls: boolean): void {
		this.cuts.set(url, [
			...(this.cuts.get(url) ?? []),
			...filePositions.map((at) => ({ at, stalls }))
		]);
	}
}

function requestedUrl(input: RequestInfo | URL): string {
	if (typeof input === 'string') return input;
	return input instanceof URL ? input.href : input.url;
}

function bodyEnd(cut: { stalls: boolean } | undefined): PiecewiseOptions['end'] {
	if (cut === undefined) return 'closes';
	return cut.stalls ? 'stalls' : 'breaks';
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

export interface Rig {
	deck: ContinuousDeck<string>;
	audio: FakeAudio;
	mediaSource: FakeMediaSource;
	buffer: FakeSourceBuffer;
	network: FakeNetwork;
	log: string[];
	revoked: string[];
}

export function openDeck(): Rig {
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

export function concatenated(chunks: Uint8Array[]): Uint8Array {
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
export function firstDifferingByte(actual: Uint8Array, expected: Uint8Array): number | null {
	const shorter = Math.min(actual.byteLength, expected.byteLength);
	for (let index = 0; index < shorter; index += 1) {
		if (actual[index] !== expected[index]) return index;
	}
	return actual.byteLength === expected.byteLength ? null : shorter;
}

// Lets every request, body piece and append already on its way run to where it waits.
export function quiet(): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, 0));
}

export function settlement(step: Promise<void>): { settled: boolean } {
	const state = { settled: false };
	step.then(
		() => (state.settled = true),
		() => (state.settled = true)
	);
	return state;
}
