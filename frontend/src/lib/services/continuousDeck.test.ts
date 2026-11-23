import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContinuousDeck, TakeNotAppended } from './continuousDeck';
import {
	MEGABYTE,
	OBJECT_URL,
	PIECE,
	type Rig,
	SLOW_PIECE,
	concatenated,
	firstDifferingByte,
	openDeck,
	quiet,
	secondsOf,
	settlement
} from './continuousDeck-test-fixtures';

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

	describe('a take put next behind the take under the playhead', () => {
		const firstEnd = secondsOf(MEGABYTE / 4);
		const repickBytes = MEGABYTE / 4;

		it.each([
			{
				ahead: 'appended whole',
				bytes: MEGABYTE / 4,
				stallsAt: null,
				arrived: (_rig: Rig, stale: Promise<void>) => stale,
				stale: 'appended'
			},
			{
				ahead: 'cut off by a request that stopped sending',
				bytes: MEGABYTE / 2,
				stallsAt: PIECE,
				arrived: () => quiet(),
				stale: 'replaced'
			},
			{
				ahead: 'waiting for room ahead',
				bytes: 2 * MEGABYTE,
				stallsAt: null,
				arrived: ({ audio }: Rig) => audio.untilDeckWaitsForPlayback(),
				stale: 'replaced'
			}
		])(
			'replaces the take held ahead when it is $ahead, from where the playing take ends',
			async ({ bytes, stallsAt, arrived, stale }) => {
				const rig = openDeck();
				const { deck, audio, buffer, network } = rig;
				network.serve('/audio/first.mp3', MEGABYTE / 4);
				network.serve('/audio/second.mp3', bytes);
				network.serve('/audio/repick.mp3', repickBytes);
				if (stallsAt !== null) network.stallAt('/audio/second.mp3', stallsAt);
				await deck.appendTake('first', '/audio/first.mp3');
				audio.playTo(5);
				const ahead = deck.appendTake('second', '/audio/second.mp3');
				const aheadOutcome = ahead.then(
					() => 'appended',
					(error: TakeNotAppended<string>) => error.reason
				);
				await arrived(rig, ahead);

				await deck.appendNext('repick', '/audio/repick.mp3');

				expect(await aheadOutcome).toBe(stale);
				expect(deck.manifest).toEqual([
					{ take: 'first', start_offset: 0, duration: firstEnd },
					{ take: 'repick', start_offset: firstEnd, duration: secondsOf(repickBytes) }
				]);
				expect(buffer.removals).toEqual([[firstEnd, Infinity]]);
				expect(buffer.buffered.end()).toBe(firstEnd + secondsOf(repickBytes));
				expect(network.requests.map((request) => request.url)).toEqual([
					'/audio/first.mp3',
					'/audio/second.mp3',
					'/audio/repick.mp3'
				]);
				expect(audio.currentTime).toBe(5);
			}
		);

		it('gives up the take held ahead when none is to follow, so the playing take ends the stream', async () => {
			const { deck, audio, buffer, network } = openDeck();
			network.serve('/audio/first.mp3', MEGABYTE / 4);
			network.serve('/audio/second.mp3', MEGABYTE / 4);
			await deck.appendTake('first', '/audio/first.mp3');
			await deck.appendTake('second', '/audio/second.mp3');
			audio.playTo(5);

			await deck.dropAhead();

			expect(deck.manifest.map((entry) => entry.take)).toEqual(['first']);
			expect(buffer.removals).toEqual([[firstEnd, Infinity]]);
		});

		it('keeps what a stream already ended holds when none is to follow', async () => {
			const { deck, audio, buffer, network } = openDeck();
			network.serve('/audio/first.mp3', MEGABYTE / 4);
			network.serve('/audio/second.mp3', MEGABYTE / 4);
			await deck.appendTake('first', '/audio/first.mp3');
			await deck.appendTake('second', '/audio/second.mp3');
			audio.playTo(5);
			await deck.endStream();

			await deck.dropAhead();

			expect(deck.manifest.map((entry) => entry.take)).toEqual(['first', 'second']);
			expect(buffer.removals).toEqual([]);
		});

		it('gives up a take still waiting behind the playing one without asking for it', async () => {
			const { deck, audio, buffer, network } = openDeck();
			network.serve('/audio/first.mp3', 2 * MEGABYTE);
			network.serve('/audio/second.mp3', MEGABYTE / 4);
			network.serve('/audio/repick.mp3', repickBytes);
			const first = deck.appendTake('first', '/audio/first.mp3');
			const ahead = deck.appendTake('second', '/audio/second.mp3');
			await audio.untilDeckWaitsForPlayback();

			const repick = deck.appendNext('repick', '/audio/repick.mp3');
			audio.playTo(100);

			await expect(ahead).rejects.toMatchObject({ take: 'second', reason: 'replaced' });
			await Promise.all([first, repick]);
			expect(network.requests.map((request) => request.url)).toEqual([
				'/audio/first.mp3',
				'/audio/repick.mp3'
			]);
			expect(deck.manifest.map((entry) => entry.take)).toEqual(['first', 'repick']);
			expect(buffer.removals).toEqual([]);
		});

		it.each([
			{
				when: 'right after the deck opened',
				arrange: async () => {}
			},
			{
				when: 'once the playhead crossed into the last take',
				arrange: async ({ deck, audio }: Rig) => {
					await deck.appendTake('second', '/audio/second.mp3');
					audio.playTo(firstEnd + 1);
				}
			}
		])('appends behind the last take as before $when', async ({ arrange }) => {
			const rig = openDeck();
			const { deck, buffer, network } = rig;
			network.serve('/audio/first.mp3', MEGABYTE / 4);
			network.serve('/audio/second.mp3', MEGABYTE / 4);
			network.serve('/audio/next.mp3', MEGABYTE / 4);
			const first = deck.appendTake('first', '/audio/first.mp3');
			await arrange(rig);

			await Promise.all([first, deck.appendNext('next', '/audio/next.mp3')]);

			const held = deck.manifest.map((entry) => entry.take);
			expect(held.at(-1)).toBe('next');
			expect(deck.manifest.at(-1)?.start_offset).toBe(
				secondsOf(((held.length - 1) * MEGABYTE) / 4)
			);
			expect(buffer.removals.filter(([, end]) => end === Infinity)).toEqual([]);
			expect(network.requests.map((request) => request.url).at(-1)).toBe('/audio/next.mp3');
		});
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
