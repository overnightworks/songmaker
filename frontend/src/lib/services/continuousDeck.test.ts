import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContinuousDeck } from './continuousDeck';

const MEGABYTE = 1024 * 1024;
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
	private readonly files = new Map<string, Uint8Array>();
	private readonly breaks = new Map<string, number[]>();
	private readonly refusals = new Map<string, number>();

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

	readonly fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
		const url = String(input);
		const range = new Headers(init?.headers).get('Range');
		this.requests.push({ url, range });
		const refusal = this.refusals.get(url);
		if (refusal) return new Response(null, { status: refusal });
		const file = this.files.get(url);
		if (!file) throw new TypeError(`no file served at ${url}`);
		const from = range ? Number(/^bytes=(\d+)-$/.exec(range)?.[1]) : 0;
		const breakPosition = this.breaks.get(url)?.shift();
		return new Response(
			piecewise(file.subarray(from, breakPosition), breakPosition !== undefined),
			{
				status: range ? 206 : 200
			}
		);
	};
}

function piecewise(bytes: Uint8Array, breaks: boolean): ReadableStream<Uint8Array> {
	const pieceBytes = 256 * 1024;
	let offset = 0;
	return new ReadableStream({
		pull(controller) {
			if (offset >= bytes.byteLength) {
				if (breaks) controller.error(new TypeError('network connection lost'));
				else controller.close();
				return;
			}
			controller.enqueue(bytes.slice(offset, offset + pieceBytes));
			offset += pieceBytes;
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

async function openDeck(): Promise<Rig> {
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
	const deck = await ContinuousDeck.open<string>({
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
		const { audio, mediaSource, buffer, revoked } = await openDeck();

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
		const { deck, network } = await openDeck();
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

	it('appends in one-megabyte chunks while less than a minute is buffered ahead', async () => {
		const { deck, audio, buffer, network } = await openDeck();
		network.serve('/audio/long.mp3', 2.5 * MEGABYTE);

		const appending = deck.appendTake('long', '/audio/long.mp3');
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.appendedBytes()).toEqual([MEGABYTE]);

		audio.playTo(10);
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.appendedBytes()).toEqual([MEGABYTE, MEGABYTE]);

		audio.playTo(75);
		await appending;
		expect(buffer.appendedBytes()).toEqual([MEGABYTE, MEGABYTE, MEGABYTE / 2]);
	});

	it('starts the next append only after the previous one fired updateend', async () => {
		const { deck, audio, buffer, network } = await openDeck();
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
		expect(buffer.appendedBytes()).toEqual([MEGABYTE]);

		buffer.settle();
		await appending;
		expect(buffer.appendedBytes()).toEqual([MEGABYTE, MEGABYTE / 2]);
	});

	it('removes takes that have played and keeps the take under the playhead', async () => {
		const { deck, audio, buffer, network } = await openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', 2 * MEGABYTE);

		void deck.appendTake('first', '/audio/first.mp3');
		const second = deck.appendTake('second', '/audio/second.mp3');
		await audio.untilDeckWaitsForPlayback();
		audio.playTo(20);
		await audio.untilDeckWaitsForPlayback();
		expect(buffer.removals).toEqual([]);

		audio.playTo(40);
		await second;
		expect(buffer.removals).toEqual([[0, secondsOf(MEGABYTE / 2)]]);
		expect(buffer.buffered.start()).toBe(secondsOf(MEGABYTE / 2));
	});

	it('frees what has played of the current take when the buffer is full, then appends', async () => {
		const { deck, audio, buffer, network } = await openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.currentTime = 25;
		buffer.quotaRefusals = 1;

		await deck.appendTake('second', '/audio/second.mp3');

		expect(buffer.removals).toEqual([[0, 15]]);
		expect(buffer.appendedBytes()).toEqual([MEGABYTE / 2, MEGABYTE / 4]);
	});

	it('reports a full buffer that freeing played audio could not cure', async () => {
		const { deck, audio, buffer, network } = await openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 2);
		network.serve('/audio/second.mp3', MEGABYTE / 4);
		await deck.appendTake('first', '/audio/first.mp3');
		audio.currentTime = 25;
		buffer.quotaRefusals = 2;

		await expect(deck.appendTake('second', '/audio/second.mp3')).rejects.toMatchObject({
			name: 'QuotaExceededError'
		});
	});

	it('reports audio the source buffer cannot decode', async () => {
		const { deck, buffer, network } = await openDeck();
		network.serve('/audio/broken.mp3', MEGABYTE / 4);
		buffer.undecodable = true;

		await expect(deck.appendTake('broken', '/audio/broken.mp3')).rejects.toThrow(
			'refused the appended audio'
		);
	});

	it('resumes a broken download from the byte already received', async () => {
		const { deck, audio, buffer, network } = await openDeck();
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

	it('reports a download that keeps breaking after three attempts', async () => {
		const { deck, network } = await openDeck();
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

	it('reports a refused take without retrying it', async () => {
		const { deck, network } = await openDeck();
		network.refuse('/audio/gone.mp3', 404);

		await expect(deck.appendTake('gone', '/audio/gone.mp3')).rejects.toThrow('404');
		expect(network.requests).toHaveLength(1);
	});

	it('ends the stream only after the last take has been appended', async () => {
		const { deck, log, network } = await openDeck();
		network.serve('/audio/first.mp3', MEGABYTE / 4);
		network.serve('/audio/second.mp3', MEGABYTE / 4);

		void deck.appendTake('first', '/audio/first.mp3');
		void deck.appendTake('second', '/audio/second.mp3');
		await deck.endStream();

		expect(log).toEqual(['append', 'append', 'endOfStream']);
	});
});
