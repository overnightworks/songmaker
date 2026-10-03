import type { QueueStreamTrackItem } from '$lib/api/types';

const MP3_MIME_TYPE = 'audio/mpeg';
const CHUNK_BYTES = 1024 * 1024;
const SECONDS_BUFFERED_AHEAD = 60;
// Removing right up to the playhead can take the frame the decoder is playing.
const SECONDS_KEPT_BEHIND_WHEN_FULL = 10;
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

class TakeRefused extends Error {
	constructor(url: string, status: number) {
		super(`${url} answered ${status}`);
		this.name = 'TakeRefused';
	}
}

type TakeNotAppendedReason = 'not-fetched' | 'stream-ended';

/**
 * A take the deck could not append, or not to its end. The deck itself plays
 * on: what was appended before it stays, and the next take still follows.
 */
export class TakeNotAppended<Take> extends Error {
	constructor(
		readonly take: Take,
		readonly reason: TakeNotAppendedReason,
		message: string
	) {
		super(message);
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

/**
 * Plays a queue of takes as one continuous stream: each take's MP3 bytes are
 * appended behind the previous one into a single SourceBuffer, so a track
 * change is only the playhead crossing an offset in {@link manifest}.
 */
export class ContinuousDeck<Take> {
	private readonly entries: DeckEntry<Take>[] = [];
	private steps: Promise<void> = Promise.resolve();
	private stepsInFlight = 0;
	private brokenBy: Error | null = null;
	private ending: Promise<void> | null = null;
	private playableFrom = 0;
	private readonly closing = new AbortController();

	private constructor(
		private readonly ports: ContinuousDeckPorts,
		private readonly opened: Promise<SourceBuffer>
	) {}

	static isSupported(): boolean {
		return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(MP3_MIME_TYPE);
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

	// The latest entry of a take whose start is still buffered, so that a seek
	// to its offset plays it from the beginning.
	playableEntryOf(isTake: (take: Take) => boolean): Readonly<DeckEntry<Take>> | undefined {
		return this.entries.findLast(
			(entry) => isTake(entry.take) && entry.start_offset >= this.playableFrom
		);
	}

	appendTake(take: Take, url: string): Promise<void> {
		if (this.ending !== null)
			return Promise.reject(
				new TakeNotAppended(take, 'stream-ended', `${url} came after the end of the stream`)
			);
		return this.queueStep((buffer) => this.appendWholeTake(buffer, take, url));
	}

	endStream(): Promise<void> {
		this.ending ??= this.queueStep(() => this.ports.mediaSource.endOfStream());
		return this.ending;
	}

	close(): void {
		this.closing.abort(new DeckClosed());
	}

	// A failed step fails every later one: a take appended behind audio the
	// buffer refused would start at the wrong offset. Only a take that could
	// not be fetched leaves the buffer as it was, so the next one still follows.
	private queueStep(step: (buffer: SourceBuffer) => Promise<void> | void): Promise<void> {
		this.stepsInFlight += 1;
		const result = this.steps
			.then(async () => {
				if (this.brokenBy) throw this.brokenBy;
				await step(await this.whileOpen(this.opened));
			})
			.finally(() => {
				this.stepsInFlight -= 1;
			});
		this.steps = result.catch((error: unknown) => {
			if (!(error instanceof TakeNotAppended)) this.brokenBy ??= asError(error);
		});
		return result;
	}

	private async appendWholeTake(buffer: SourceBuffer, take: Take, url: string): Promise<void> {
		const entry: DeckEntry<Take> = { take, start_offset: buffer.timestampOffset, duration: 0 };
		this.entries.push(entry);
		try {
			for await (const chunk of chunked(this.download(take, url))) {
				await this.roomAhead(buffer);
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

	private async *download(take: Take, url: string): AsyncGenerator<Uint8Array> {
		let received = 0;
		for (let attempt = 1; ; attempt += 1) {
			try {
				for await (const piece of piecesOf(await this.request(url, received))) {
					received += piece.byteLength;
					yield piece;
				}
				return;
			} catch (error) {
				this.closing.signal.throwIfAborted();
				if (error instanceof TakeRefused || attempt === DOWNLOAD_ATTEMPTS)
					throw new TakeNotAppended(take, 'not-fetched', asError(error).message);
			}
		}
	}

	private async request(url: string, fromByte: number): Promise<ReadableStream<Uint8Array>> {
		const resuming = fromByte > 0;
		const response = await this.ports.fetch(url, {
			headers: resuming ? { Range: `bytes=${fromByte}-` } : {},
			signal: this.closing.signal
		});
		const expectedStatus = resuming ? 206 : 200;
		if (response.status !== expectedStatus || !response.body)
			throw new TakeRefused(url, response.status);
		return response.body;
	}

	private async roomAhead(buffer: SourceBuffer): Promise<void> {
		const { element } = this.ports;
		while (buffer.timestampOffset - element.currentTime >= SECONDS_BUFFERED_AHEAD)
			await this.whileOpen(nextEvent(element, 'timeupdate', this.closing.signal));
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

	private whileOpen<Value>(pending: Promise<Value>): Promise<Value> {
		const { signal } = this.closing;
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

function asError(error: unknown): Error {
	return error instanceof Error
		? error
		: new Error('A deck step failed without an error', { cause: error });
}

// An aborted signal only removes the listener; the promise then never settles.
function nextEvent(target: EventTarget, type: string, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve) =>
		target.addEventListener(type, () => resolve(), { once: true, signal })
	);
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

// A take's first piece goes in at once, so playback starts on the first bytes
// that arrive instead of after a megabyte (#1187 P5).
async function* chunked(
	pieces: AsyncIterable<Uint8Array>
): AsyncGenerator<Uint8Array<ArrayBuffer>> {
	let gathered: Uint8Array[] = [];
	let gatheredBytes = 0;
	let firstPiece = true;
	for await (const piece of pieces) {
		gathered.push(piece);
		gatheredBytes += piece.byteLength;
		if (firstPiece || gatheredBytes >= CHUNK_BYTES) {
			firstPiece = false;
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
