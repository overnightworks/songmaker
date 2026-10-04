import type { QueueStreamTrackItem } from '$lib/api/types';

const MP3_MIME_TYPE = 'audio/mpeg';
const CHUNK_BYTES = 1024 * 1024;
const SECONDS_BUFFERED_AHEAD = 60;
const SECONDS_AHEAD_BEFORE_GATHERING = 20;
// Removing right up to the playhead can take the frame the decoder is playing.
const SECONDS_KEPT_BEHIND_WHEN_FULL = 10;
// Attempts in a row before a download parks until the player retries it.
const DOWNLOAD_ATTEMPTS = 3;
const QUOTA_EXCEEDED = 'QuotaExceededError';

export type DeckEntry<Take> = Pick<QueueStreamTrackItem, 'start_offset' | 'duration'> & {
	take: Take;
};

interface ContinuousDeckPorts {
	element: HTMLMediaElement;
	mediaSource: MediaSource;
	urls: Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'>;
	fetch: typeof fetch;
}

// The server answered, but not with the bytes asked for: asking again would
// get the same answer. A body that could not be cancelled is named with it.
class TakeRefused extends Error {
	constructor(url: string, refusal: string, cancelFailure?: Error) {
		super(
			cancelFailure
				? `${url} ${refusal}; cancelling its body failed: ${cancelFailure.message}`
				: `${url} ${refusal}`,
			{ cause: cancelFailure }
		);
		this.name = 'TakeRefused';
	}
}

type TakeNotAppendedReason = 'refused' | 'stream-ended' | 'replaced';

/**
 * A take the deck could not append, or not to its end. The deck itself plays
 * on: what was appended before it stays, and the next take still follows.
 */
export class TakeNotAppended<Take> extends Error {
	constructor(
		readonly take: Take,
		readonly reason: TakeNotAppendedReason,
		message: string,
		options?: ErrorOptions
	) {
		super(message, options);
		this.name = 'TakeNotAppended';
	}
}

/**
 * The player left the deck: whatever it still had to fetch, wait for or
 * append is given up, and the buffer is not touched again.
 */
class DeckClosed extends Error {
	constructor() {
		super('The deck was closed');
		this.name = 'DeckClosed';
	}
}

// A take the deck was asked for and has not finished appending. Its entry
// exists once its append has begun; withdrawing it gives the take up, whether
// it still waits its turn or is being fetched.
interface PendingTake<Take> {
	take: Take;
	entry: DeckEntry<Take> | null;
	readonly withdrawal: AbortController;
}

/**
 * Plays a queue of takes as one continuous stream: each take's MP3 bytes are
 * appended behind the previous one into a single SourceBuffer, so a track
 * change is only the playhead crossing an offset in {@link manifest}.
 *
 * A download the network keeps failing parks with what it appended, and the
 * takes after it wait behind it; the deck sets no timer of its own, so only
 * {@link retryDownload} sends it on.
 */
export class ContinuousDeck<Take> {
	private readonly entries: DeckEntry<Take>[] = [];
	private readonly pending: PendingTake<Take>[] = [];
	private steps: Promise<void> = Promise.resolve();
	private stepsInFlight = 0;
	private brokenBy: Error | null = null;
	private ending: Promise<void> | null = null;
	private playableFrom = 0;
	private readonly closing = new AbortController();
	private requestInFlight: AbortController | null = null;
	private wakeParkedDownload: (() => void) | null = null;

	private constructor(
		private readonly ports: ContinuousDeckPorts,
		private readonly opened: Promise<SourceBuffer>
	) {}

	// Without a live seekable range a seek could never reach past what has arrived.
	static isSupported(): boolean {
		return (
			typeof MediaSource !== 'undefined' &&
			MediaSource.isTypeSupported(MP3_MIME_TYPE) &&
			'setLiveSeekableRange' in MediaSource.prototype
		);
	}

	// Usable at once: every append waits for the media source to open, so the
	// first take is asked for in the same moment the element gets its source.
	static attach<Take>(ports: ContinuousDeckPorts): ContinuousDeck<Take> {
		return new ContinuousDeck<Take>(ports, attachSourceBuffer(ports));
	}

	get manifest(): readonly Readonly<DeckEntry<Take>>[] {
		return this.entries;
	}

	get appending(): boolean {
		return this.stepsInFlight > 0;
	}

	entryAt(seconds: number): Readonly<DeckEntry<Take>> | undefined {
		return this.entries.findLast((entry) => entry.start_offset <= seconds);
	}

	// Whether the entry's start is still buffered, so that a seek to its offset
	// plays it from the beginning.
	isPlayableFromStart(entry: Readonly<DeckEntry<Take>>): boolean {
		return entry.start_offset >= this.playableFrom;
	}

	/**
	 * Moves the playhead to `seconds`, even past what has arrived: the element
	 * waits there, and the download appends on until it reaches it. The stream
	 * has no known length, so without the live seekable range the browser would
	 * stop the seek where the buffer ends (#1270). The range opens only forward
	 * from the earliest audio still kept: freed audio is never appended again,
	 * so a seek before it lands where the kept audio starts. An ended stream
	 * holds all it will ever hold, so a seek there stays within it.
	 */
	seekTo(seconds: number): void {
		const { element, mediaSource } = this.ports;
		if (mediaSource.readyState === 'open')
			mediaSource.setLiveSeekableRange(this.playableFrom, Math.max(seconds, this.playableFrom));
		element.currentTime = seconds;
	}

	/**
	 * Moves the playhead as a live scrub does: no further than what has
	 * arrived, so the position the listener sees is the one that plays. A
	 * range a waiting seek opened is dropped first; scrubbing past the buffer
	 * is #1187's to decide.
	 */
	scrubTo(seconds: number): void {
		const { element, mediaSource } = this.ports;
		if (mediaSource.readyState === 'open') mediaSource.clearLiveSeekableRange();
		element.currentTime = seconds;
	}

	appendTake(take: Take, url: string): Promise<void> {
		return this.queueTake(take, url, () => undefined);
	}

	/**
	 * Makes `take` the one that plays after the take under the playhead (#1299):
	 * whatever the deck holds or still waits to append after that take is given
	 * up, its fetch cancelled and its audio removed, and `take` is appended
	 * where the playing take ends. With nothing ahead it is appended behind the
	 * last take, as {@link appendTake} does. Before the first take has an entry,
	 * that take is the one that plays.
	 */
	appendNext(take: Take, url: string): Promise<void> {
		if (this.ending === null) this.withdrawAhead();
		return this.queueTake(take, url, (buffer) => this.removeAhead(buffer));
	}

	endStream(): Promise<void> {
		this.ending ??= this.queueStep(() => this.ports.mediaSource.endOfStream());
		return this.ending;
	}

	close(): void {
		this.closing.abort(new DeckClosed());
	}

	// Cuts a request that may have stopped sending, or wakes a parked one: either
	// way the download resumes from the bytes received, with its attempts fresh.
	retryDownload(): void {
		this.requestInFlight?.abort(new Error('The player retried the download'));
		this.wakeParkedDownload?.();
	}

	// A failed step fails every later one: a take appended behind audio the
	// buffer refused would start at the wrong offset. Only a refused take leaves
	// the buffer as it was, so the next one still follows.
	private queueStep(step: (buffer: SourceBuffer) => Promise<void> | void): Promise<void> {
		this.stepsInFlight += 1;
		const result = this.steps
			.then(async () => {
				if (this.brokenBy) throw this.brokenBy;
				await step(await this.unlessAborted(this.closing.signal, this.opened));
			})
			.finally(() => {
				this.stepsInFlight -= 1;
			});
		this.steps = result.catch((error: unknown) => {
			if (!(error instanceof TakeNotAppended)) this.brokenBy ??= asError(error);
		});
		return result;
	}

	private queueTake(
		take: Take,
		url: string,
		beforeAppending: (buffer: SourceBuffer) => Promise<void> | void
	): Promise<void> {
		if (this.ending !== null)
			return Promise.reject(
				new TakeNotAppended(take, 'stream-ended', `${url} came after the end of the stream`)
			);
		const pending: PendingTake<Take> = { take, entry: null, withdrawal: new AbortController() };
		this.pending.push(pending);
		return this.queueStep(async (buffer) => {
			await beforeAppending(buffer);
			await this.appendWholeTake(buffer, pending, url);
		}).finally(() => this.pending.splice(this.pending.indexOf(pending), 1));
	}

	private withdrawAhead(): void {
		const playing = this.entryAt(this.ports.element.currentTime);
		const firstAhead = playing ? this.pending.findIndex(({ entry }) => entry === playing) + 1 : 1;
		for (const { take, withdrawal } of this.pending.slice(firstAhead))
			withdrawal.abort(new TakeNotAppended(take, 'replaced', 'Another take was put next'));
	}

	// Sequence mode appends wherever timestampOffset points, so pointing it back
	// at the playing take's end is what makes the next take follow that one.
	private async removeAhead(buffer: SourceBuffer): Promise<void> {
		const playing = this.entryAt(this.ports.element.currentTime);
		if (!playing) return;
		const ahead = this.entries.indexOf(playing) + 1;
		const firstAhead = this.entries.at(ahead);
		if (!firstAhead) return;
		const playingEnd = firstAhead.start_offset;
		await this.update(buffer, () => buffer.remove(playingEnd, Infinity));
		buffer.timestampOffset = playingEnd;
		this.entries.splice(ahead);
	}

	private async appendWholeTake(
		buffer: SourceBuffer,
		pending: PendingTake<Take>,
		url: string
	): Promise<void> {
		const { take } = pending;
		const wanted = AbortSignal.any([this.closing.signal, pending.withdrawal.signal]);
		wanted.throwIfAborted();
		const entry: DeckEntry<Take> = { take, start_offset: buffer.timestampOffset, duration: 0 };
		pending.entry = entry;
		this.entries.push(entry);
		try {
			const runningLow = () => this.secondsAhead(buffer) < SECONDS_AHEAD_BEFORE_GATHERING;
			for await (const chunk of chunked(this.download(take, url, wanted), runningLow)) {
				await this.roomAhead(buffer, wanted);
				await this.evictPlayedTakes(buffer);
				await this.appendChunk(buffer, chunk);
				entry.duration = buffer.timestampOffset - entry.start_offset;
			}
		} catch (error) {
			if (error instanceof TakeNotAppended) this.endTakeEarly(buffer, entry);
			throw error;
		}
	}

	// A take with nothing appended leaves no trace in the manifest; one cut off
	// part-way keeps what it has, and the parser drops its unfinished frame so
	// the next take's first frame is read from its own start.
	private endTakeEarly(buffer: SourceBuffer, entry: DeckEntry<Take>): void {
		if (entry.duration === 0) this.entries.splice(this.entries.indexOf(entry), 1);
		else buffer.abort();
	}

	private async *download(
		take: Take,
		url: string,
		wanted: AbortSignal
	): AsyncGenerator<Uint8Array> {
		let received = 0;
		let failedInARow = 0;
		for (;;) {
			const attempt = new AbortController();
			this.requestInFlight = attempt;
			try {
				const body = await this.request(url, received, AbortSignal.any([wanted, attempt.signal]));
				for await (const piece of piecesOf(body)) {
					received += piece.byteLength;
					yield piece;
				}
				return;
			} catch (error) {
				wanted.throwIfAborted();
				if (error instanceof TakeRefused)
					throw new TakeNotAppended(take, 'refused', error.message, { cause: error });
				failedInARow = attempt.signal.aborted ? 0 : failedInARow + 1;
			} finally {
				this.requestInFlight = null;
			}
			if (failedInARow === DOWNLOAD_ATTEMPTS) {
				await this.parkDownload(wanted);
				failedInARow = 0;
			}
		}
	}

	private parkDownload(wanted: AbortSignal): Promise<void> {
		const woken = new Promise<void>((wake) => {
			this.wakeParkedDownload = wake;
		});
		return this.unlessAborted(wanted, woken).finally(() => {
			this.wakeParkedDownload = null;
		});
	}

	private async request(
		url: string,
		fromByte: number,
		signal: AbortSignal
	): Promise<ReadableStream<Uint8Array>> {
		const resuming = fromByte > 0;
		const response = await this.ports.fetch(url, {
			headers: resuming ? { Range: `bytes=${fromByte}-` } : {},
			signal
		});
		const refusal = refusalOf(response, fromByte);
		if (refusal) throw new TakeRefused(url, refusal, await cancelFailureOf(response));
		if (!response.body) throw new TakeRefused(url, `answered ${response.status} without a body`);
		return response.body;
	}

	private secondsAhead(buffer: SourceBuffer): number {
		return buffer.timestampOffset - this.ports.element.currentTime;
	}

	// A seek wakes the wait as well: the element announces a seek past the
	// buffer at once, but its first timeupdate there only once audio arrived.
	// unlessAborted wakes a parked wait on close or withdrawal; tying each
	// listener to the signal as well would leave an abort step on it per
	// timeupdate.
	private async roomAhead(buffer: SourceBuffer, wanted: AbortSignal): Promise<void> {
		while (this.secondsAhead(buffer) >= SECONDS_BUFFERED_AHEAD)
			await this.unlessAborted(wanted, firstEventOf(this.ports.element, ['timeupdate', 'seeking']));
	}

	private async evictPlayedTakes(buffer: SourceBuffer): Promise<void> {
		const current = this.entryAt(this.ports.element.currentTime);
		if (current) await this.removeBefore(buffer, current.start_offset);
	}

	private async appendChunk(buffer: SourceBuffer, chunk: Uint8Array<ArrayBuffer>): Promise<void> {
		try {
			await this.update(buffer, () => buffer.appendBuffer(chunk));
		} catch (error) {
			if (!isQuotaExceeded(error)) throw error;
			const playhead = this.ports.element.currentTime;
			const freed = await this.removeBefore(buffer, playhead - SECONDS_KEPT_BEHIND_WHEN_FULL);
			if (!freed) throw error;
			await this.update(buffer, () => buffer.appendBuffer(chunk));
		}
	}

	private async removeBefore(buffer: SourceBuffer, seconds: number): Promise<boolean> {
		const buffered = buffer.buffered;
		if (buffered.length === 0 || buffered.start(0) >= seconds) return false;
		await this.update(buffer, () => buffer.remove(buffered.start(0), seconds));
		this.playableFrom = seconds;
		return true;
	}

	private async update(buffer: SourceBuffer, start: () => void): Promise<void> {
		this.closing.signal.throwIfAborted();
		start();
		await updateEnded(buffer);
	}

	private unlessAborted<Value>(signal: AbortSignal, pending: Promise<Value>): Promise<Value> {
		return new Promise((resolve, reject) => {
			const closed = () => reject(signal.reason);
			if (signal.aborted) {
				closed();
				return;
			}
			signal.addEventListener('abort', closed, { once: true });
			pending.then(resolve, reject).finally(() => signal.removeEventListener('abort', closed));
		});
	}
}

async function attachSourceBuffer(ports: ContinuousDeckPorts): Promise<SourceBuffer> {
	const { element, mediaSource, urls } = ports;
	const opened = nextEvent(mediaSource, 'sourceopen');
	const objectUrl = urls.createObjectURL(mediaSource);
	element.src = objectUrl;
	await opened;
	urls.revokeObjectURL(objectUrl);
	const buffer = mediaSource.addSourceBuffer(MP3_MIME_TYPE);
	buffer.mode = 'sequence';
	return buffer;
}

// A resume appends behind the bytes already received, so an answer starting
// anywhere else would duplicate or skip audio inside the take.
function refusalOf(response: Response, fromByte: number): string | null {
	const resuming = fromByte > 0;
	if (resuming && response.status === 200) return 'ignored Range';
	if (response.status !== (resuming ? 206 : 200)) return `answered ${response.status}`;
	if (!resuming) return null;
	const contentRange = response.headers.get('Content-Range');
	if (contentRange === null) return 'missing Content-Range';
	const answeredFrom = Number(/^bytes (\d+)-/.exec(contentRange)?.[1]);
	if (answeredFrom === fromByte) return null;
	return `Content-Range mismatch: asked from byte ${fromByte}, answered ${contentRange}`;
}

// A body that has already errored cannot be cancelled; that failure is
// handed back, so it neither hides the refusal nor goes unseen.
async function cancelFailureOf(response: Response): Promise<Error | undefined> {
	try {
		await response.body?.cancel();
		return undefined;
	} catch (error) {
		return asError(error);
	}
}

function asError(error: unknown): Error {
	return error instanceof Error
		? error
		: new Error('A deck step failed without an error', { cause: error });
}

function nextEvent(target: EventTarget, type: string): Promise<void> {
	return new Promise((resolve) => target.addEventListener(type, () => resolve(), { once: true }));
}

function firstEventOf(target: EventTarget, types: readonly string[]): Promise<void> {
	return new Promise((resolve) => {
		const fired = () => {
			for (const type of types) target.removeEventListener(type, fired);
			resolve();
		};
		for (const type of types) target.addEventListener(type, fired);
	});
}

function updateEnded(buffer: SourceBuffer): Promise<void> {
	return new Promise((resolve, reject) => {
		const ended = () => {
			buffer.removeEventListener('error', failed);
			resolve();
		};
		const failed = () => {
			buffer.removeEventListener('updateend', ended);
			reject(new Error('The source buffer refused the appended audio'));
		};
		buffer.addEventListener('updateend', ended, { once: true });
		buffer.addEventListener('error', failed, { once: true });
	});
}

function isQuotaExceeded(error: unknown): boolean {
	return error instanceof DOMException && error.name === QUOTA_EXCEEDED;
}

async function* piecesOf(body: ReadableStream<Uint8Array>): AsyncGenerator<Uint8Array> {
	const reader = body.getReader();
	let handedOut = false;
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) return;
			handedOut = true;
			yield value;
			handedOut = false;
		}
	} finally {
		if (handedOut) await reader.cancel();
	}
}

// While the playhead is close to the end of the buffer every piece goes in as
// it arrives: playback starts on the first bytes, and a link barely faster
// than the take's bitrate still keeps the buffer growing (#1280). Only with
// plenty buffered are pieces gathered into fewer, larger appends.
async function* chunked(
	pieces: AsyncIterable<Uint8Array>,
	runningLow: () => boolean
): AsyncGenerator<Uint8Array<ArrayBuffer>> {
	let gathered: Uint8Array[] = [];
	let gatheredBytes = 0;
	for await (const piece of pieces) {
		gathered.push(piece);
		gatheredBytes += piece.byteLength;
		if (runningLow() || gatheredBytes >= CHUNK_BYTES) {
			yield joined(gathered, gatheredBytes);
			gathered = [];
			gatheredBytes = 0;
		}
	}
	if (gatheredBytes > 0) yield joined(gathered, gatheredBytes);
}

function joined(pieces: Uint8Array[], totalBytes: number): Uint8Array<ArrayBuffer> {
	const whole = new Uint8Array(totalBytes);
	let offset = 0;
	for (const piece of pieces) {
		whole.set(piece, offset);
		offset += piece.byteLength;
	}
	return whole;
}
