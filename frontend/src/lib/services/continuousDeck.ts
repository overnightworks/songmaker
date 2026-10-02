import type { QueueStreamTrackItem } from '$lib/api/types';

const MP3_MIME_TYPE = 'audio/mpeg';
const CHUNK_BYTES = 1024 * 1024;
const SECONDS_BUFFERED_AHEAD = 60;
// Removing right up to the playhead can take the frame the decoder is playing.
const SECONDS_KEPT_BEHIND_WHEN_FULL = 10;
const DOWNLOAD_ATTEMPTS = 3;
const QUOTA_EXCEEDED = 'QuotaExceededError';

type DeckEntry<Take> = Pick<QueueStreamTrackItem, 'start_offset' | 'duration'> & { take: Take };

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

/**
 * Plays a queue of takes as one continuous stream: each take's MP3 bytes are
 * appended behind the previous one into a single SourceBuffer, so a track
 * change is only the playhead crossing an offset in {@link manifest}.
 */
export class ContinuousDeck<Take> {
	private readonly entries: DeckEntry<Take>[] = [];
	private steps: Promise<void> = Promise.resolve();

	private constructor(
		private readonly ports: ContinuousDeckPorts,
		private readonly buffer: SourceBuffer
	) {}

	static isSupported(): boolean {
		return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(MP3_MIME_TYPE);
	}

	static async open<Take>(ports: ContinuousDeckPorts): Promise<ContinuousDeck<Take>> {
		const { element, mediaSource, urls } = ports;
		const opened = nextEvent(mediaSource, 'sourceopen');
		const objectUrl = urls.createObjectURL(mediaSource);
		element.src = objectUrl;
		await opened;
		urls.revokeObjectURL(objectUrl);
		const buffer = mediaSource.addSourceBuffer(MP3_MIME_TYPE);
		buffer.mode = 'sequence';
		return new ContinuousDeck<Take>(ports, buffer);
	}

	get manifest(): readonly Readonly<DeckEntry<Take>>[] {
		return this.entries;
	}

	appendTake(take: Take, url: string): Promise<void> {
		return this.queueStep(() => this.appendWholeTake(take, url));
	}

	endStream(): Promise<void> {
		return this.queueStep(async () => this.ports.mediaSource.endOfStream());
	}

	// A failed step fails every later one: a take appended behind a partial
	// take would start at the wrong offset.
	private queueStep(step: () => Promise<void>): Promise<void> {
		this.steps = this.steps.then(step);
		return this.steps;
	}

	private async appendWholeTake(take: Take, url: string): Promise<void> {
		const entry: DeckEntry<Take> = { take, start_offset: this.buffer.timestampOffset, duration: 0 };
		this.entries.push(entry);
		for await (const chunk of chunked(this.download(url))) {
			await this.roomAhead();
			await this.evictPlayedTakes();
			await this.appendChunk(chunk);
			entry.duration = this.buffer.timestampOffset - entry.start_offset;
		}
	}

	private async *download(url: string): AsyncGenerator<Uint8Array> {
		let received = 0;
		for (let attempt = 1; ; attempt += 1) {
			try {
				for await (const piece of piecesOf(await this.request(url, received))) {
					received += piece.byteLength;
					yield piece;
				}
				return;
			} catch (error) {
				if (error instanceof TakeRefused || attempt === DOWNLOAD_ATTEMPTS) throw error;
			}
		}
	}

	private async request(url: string, fromByte: number): Promise<ReadableStream<Uint8Array>> {
		const resuming = fromByte > 0;
		const response = await this.ports.fetch(url, {
			headers: resuming ? { Range: `bytes=${fromByte}-` } : {}
		});
		const expectedStatus = resuming ? 206 : 200;
		if (response.status !== expectedStatus || !response.body)
			throw new TakeRefused(url, response.status);
		return response.body;
	}

	private async roomAhead(): Promise<void> {
		const { element } = this.ports;
		while (this.buffer.timestampOffset - element.currentTime >= SECONDS_BUFFERED_AHEAD)
			await nextEvent(element, 'timeupdate');
	}

	private async evictPlayedTakes(): Promise<void> {
		const playhead = this.ports.element.currentTime;
		const current = this.entries.findLast((entry) => entry.start_offset <= playhead);
		if (current) await this.removeBefore(current.start_offset);
	}

	private async appendChunk(chunk: Uint8Array<ArrayBuffer>): Promise<void> {
		try {
			await this.update(() => this.buffer.appendBuffer(chunk));
		} catch (error) {
			if (!isQuotaExceeded(error)) throw error;
			const playhead = this.ports.element.currentTime;
			const freed = await this.removeBefore(playhead - SECONDS_KEPT_BEHIND_WHEN_FULL);
			if (!freed) throw error;
			await this.update(() => this.buffer.appendBuffer(chunk));
		}
	}

	private async removeBefore(seconds: number): Promise<boolean> {
		const buffered = this.buffer.buffered;
		if (buffered.length === 0 || buffered.start(0) >= seconds) return false;
		await this.update(() => this.buffer.remove(buffered.start(0), seconds));
		return true;
	}

	private async update(start: () => void): Promise<void> {
		start();
		await updateEnded(this.buffer);
	}
}

function nextEvent(target: EventTarget, type: string): Promise<void> {
	return new Promise((resolve) => target.addEventListener(type, () => resolve(), { once: true }));
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

async function* chunked(
	pieces: AsyncIterable<Uint8Array>
): AsyncGenerator<Uint8Array<ArrayBuffer>> {
	let gathered: Uint8Array[] = [];
	let gatheredBytes = 0;
	for await (const piece of pieces) {
		gathered.push(piece);
		gatheredBytes += piece.byteLength;
		if (gatheredBytes >= CHUNK_BYTES) {
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
