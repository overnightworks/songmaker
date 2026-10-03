import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContinuousDeck, TakeNotAppended } from './continuousDeck';

const MEGABYTE = 1024 * 1024;
// The size FakeNetwork hands a response body out in.
const PIECE = 256 * 1024;
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

class FakeMediaSource extends EventTarget {
	readonly mimeTypes: string[] = [];
	readonly buffer: FakeSourceBuffer;

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
		this.log.push('endOfStream');
	}
}

class FakeAudio extends EventTarget {
	src = '';
	currentTime = 0;
	private readonly playbackWatchers: (() => void)[] = [];

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
		this.currentTime = seconds;
		this.dispatchEvent(new Event('timeupdate'));
	}
}

interface TakeRequest {
	url: string;
	range: string | null;
}

class FakeNetwork {
	readonly requests: TakeRequest[] = [];
	readonly signals: AbortSignal[] = [];
	private readonly files = new Map<string, Uint8Array>();
	private readonly breaks = new Map<string, number[]>();
	private readonly refusals = new Map<string, number>();
	private readonly rangesAnsweredFromTheStart = new Map<string, 200 | 206>();

	serve(url: string, bytes: number): Uint8Array {
		const file = Uint8Array.from({ length: bytes }, (_, index) => index % 251);
		this.files.set(url, file);
		return file;
	}

	breakAt(url: string, ...filePositions: number[]): void {
		this.breaks.set(url, filePositions);
	}

	refuse(url: string, status: number): void {
		this.refusals.set(url, status);
	}

	answerRangesFromTheStart(url: string, status: 200 | 206): void {
		this.rangesAnsweredFromTheStart.set(url, status);
	}

	readonly fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
		const url = String(input);
		const range = new Headers(init?.headers).get('Range');
		this.requests.push({ url, range });
		if (init?.signal) this.signals.push(init.signal);
		const refusal = this.refusals.get(url);
		if (refusal) return new Response(null, { status: refusal });
		const file = this.files.get(url);
		if (!file) throw new TypeError(`no file served at ${url}`);
		const startAnswer = range ? this.rangesAnsweredFromTheStart.get(url) : undefined;
		const from = range && !startAnswer ? Number(/^bytes=(\d+)-$/.exec(range)?.[1]) : 0;
		const status = startAnswer ?? (range ? 206 : 200);
		const breakPosition = this.breaks.get(url)?.shift();
		const headers: Record<string, string> =
			status === 206
				? { 'Content-Range': `bytes ${from}-${file.byteLength - 1}/${file.byteLength}` }
				: {};
		return new Response(
			piecewise(file.subarray(from, breakPosition), breakPosition !== undefined, init?.signal),
			{ status, headers }
		);
	};
}

// Like a fetch body, the stream errors with the abort reason once its request is aborted.
function piecewise(
	bytes: Uint8Array,
	breaks: boolean,
	signal: AbortSignal | null | undefined
): ReadableStream<Uint8Array> {
	let offset = 0;
	return new ReadableStream({
		pull(controller) {
			if (signal?.aborted) {
				controller.error(signal.reason);
				return;
			}
			if (offset >= bytes.byteLength) {
				if (breaks) controller.error(new TypeError('network connection lost'));
				else controller.close();
				return;
			}
			controller.enqueue(bytes.slice(offset, offset + PIECE));
			offset += PIECE;
		}
	});
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
	const audio = new FakeAudio();
	const mediaSource = new FakeMediaSource(log);
	const network = new FakeNetwork();
	const revoked: string[] = [];
	const urls = {
		createObjectURL: () => {
			queueMicrotask(() => mediaSource.dispatchEvent(new Event('sourceopen')));
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

describe('ContinuousDeck', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('attaches one audio/mpeg buffer in sequence mode to the element', async () => {
		const { deck, audio, mediaSource, buffer, revoked } = openDeck();
		await deck.endStream();

		expect(audio.src).toBe(OBJECT_URL);
		expect(revoked).toEqual([OBJECT_URL]);
		expect(mediaSource.mimeTypes).toEqual(['audio/mpeg']);
		expect(buffer.mode).toBe('sequence');
	});

	it.each([
		{ mediaSource: undefined, supported: false },
		{ mediaSource: { isTypeSupported: () => false }, supported: false },
		{ mediaSource: { isTypeSupported: (type: string) => type === 'audio/mpeg' }, supported: true }
	])('reports MP3 support as $supported', ({ mediaSource, supported }) => {
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

	it('appends the first piece at once, then one-megabyte chunks while less than a minute is buffered ahead', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 2.5 * MEGABYTE);

		const appending = deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.appendedBytes()).toEqual([PIECE, MEGABYTE]);

		audio.playTo(25);
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.appendedBytes()).toEqual([PIECE, MEGABYTE, MEGABYTE]);

		audio.playTo(100);
		await appending;
		expect(buffer.appendedBytes()).toEqual([PIECE, MEGABYTE, MEGABYTE, PIECE]);
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

	it('starts the next append only after the previous one fired updateend', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/long.mp3', 1.5 * MEGABYTE);
		audio.currentTime = 1000;
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
		expect(buffer.appendedBytes()).toEqual([PIECE, MEGABYTE, PIECE]);
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
		audio.currentTime = 25;
		buffer.quotaRefusals = 1;

		await deck.appendTake('second', '/audio/second.mp3');

		expect(buffer.removals).toEqual([[0, 15]]);
		expect(buffer.appendedBytes()).toEqual([PIECE, PIECE, PIECE]);
	});

	it('reports a full buffer that freeing played audio could not cure', async () => {
		const { deck, audio, buffer, network } = openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.currentTime = 25;
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
		{ answer: 206 as const, refusal: 'Content-Range mismatch' },
		{ answer: 200 as const, refusal: 'ignored Range' }
	])(
		'refuses a resume answered $answer from the first byte as $refusal and appends nothing twice',
		async ({ answer, refusal }) => {
			const { deck, buffer, network } = openDeck();
			const file = network.serve('/audio/take.mp3', 0.75 * MEGABYTE);
			network.breakAt('/audio/take.mp3', 300_000);
			network.answerRangesFromTheStart('/audio/take.mp3', answer);

			const step = deck.appendTake('take', '/audio/take.mp3');

			await expect(step).rejects.toMatchObject({ reason: 'not-fetched' });
			await expect(step).rejects.toThrow(refusal);
			expect(network.requests.map((request) => request.range)).toEqual([null, 'bytes=300000-']);
			const appended = concatenated(buffer.appended);
			expect(appended.byteLength).toBeLessThanOrEqual(300_000);
			expect(firstDifferingByte(appended, file.subarray(0, appended.byteLength))).toBeNull();
		}
	);

	it('gives up on a download that keeps breaking after three attempts', async () => {
		const { deck, network } = openDeck();
		network.serve('/audio/take.mp3', MEGABYTE / 2);
		network.breakAt('/audio/take.mp3', 100_000, 200_000, 300_000);

		await expect(deck.appendTake('take', '/audio/take.mp3')).rejects.toThrow(
			'network connection lost'
		);
		expect(network.requests.map((request) => request.range)).toEqual([
			null,
			'bytes=100000-',
			'bytes=200000-'
		]);
	});

	it('gives up on a refused take without retrying it', async () => {
		const { deck, network } = openDeck();
		network.refuse('/audio/gone.mp3', 404);

		await expect(deck.appendTake('gone', '/audio/gone.mp3')).rejects.toThrow('404');
		expect(network.requests).toHaveLength(1);
	});

	it.each([
		{
			failure: 'refused',
			arrange: (network: FakeNetwork) => network.refuse('/audio/gone.mp3', 404)
		},
		{
			failure: 'never arriving',
			arrange: (network: FakeNetwork) => {
				network.serve('/audio/gone.mp3', MEGABYTE / 2);
				network.breakAt('/audio/gone.mp3', 0, 0, 0);
			}
		}
	])(
		'drops a $failure take, names it, and appends the next take where it would have started',
		async ({ arrange }) => {
			const { deck, network } = openDeck();
			network.serve('/audio/first.mp3', MEGABYTE / 4);
			network.serve('/audio/third.mp3', MEGABYTE / 4);
			arrange(network);

			void deck.appendTake('first', '/audio/first.mp3');
			const dropped = deck.appendTake('gone', '/audio/gone.mp3');
			const third = deck.appendTake('third', '/audio/third.mp3');

			await expect(dropped).rejects.toMatchObject({ take: 'gone', reason: 'not-fetched' });
			await third;
			expect(deck.manifest).toEqual([
				{ take: 'first', start_offset: 0, duration: secondsOf(MEGABYTE / 4) },
				{
					take: 'third',
					start_offset: secondsOf(MEGABYTE / 4),
					duration: secondsOf(MEGABYTE / 4)
				}
			]);
		}
	);

	it('keeps what a take cut off part-way appended and starts the next take on a fresh frame', async () => {
		const { deck, log, network } = openDeck();
		network.serve('/audio/cut.mp3', MEGABYTE / 2);
		network.breakAt('/audio/cut.mp3', PIECE, PIECE, PIECE);
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
		audio.currentTime = secondStart + 1;

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

			expect(buffer.appendedBytes()).toEqual([PIECE, MEGABYTE]);
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
