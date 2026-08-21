import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { ApiError } from './fetch';
import {
	consumeSseFrames,
	openResourceEventStream,
	parseResourceStreamEvent,
	parseSseFrame
} from './resourceEvents';
import { RESOURCE_EVENTS_PATH } from '$lib/constants';

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	return new ReadableStream({
		start(controller) {
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
			controller.close();
		}
	});
}

describe('SSE frame parsing', () => {
	it('parses id, event, and data', () => {
		const { frames, rest } = consumeSseFrames(
			'id: 3\nevent: generation.created\ndata: {"type":"generation.created"}\n\npartial'
		);
		expect(rest).toBe('partial');
		expect(frames).toEqual([
			{
				id: '3',
				event: 'generation.created',
				data: '{"type":"generation.created"}'
			}
		]);
	});

	it('skips comments and nameless heartbeats without data', () => {
		expect(parseSseFrame(': ping')).toBeNull();
		expect(parseSseFrame('event: heartbeat')).toBeNull();
		expect(parseSseFrame('event: heartbeat\ndata: {}')).toEqual({
			id: null,
			event: 'heartbeat',
			data: '{}'
		});
	});
});

describe('parseResourceStreamEvent', () => {
	it('parses hello, resync, heartbeat, and generation.created', () => {
		expect(
			parseResourceStreamEvent({
				id: null,
				event: 'hello',
				data: '{"type":"hello","high_water_mark":4}'
			})
		).toEqual({ type: 'hello', high_water_mark: 4 });
		expect(
			parseResourceStreamEvent({
				id: '4',
				event: 'resync',
				data: '{"type":"resync","high_water_mark":4}'
			})
		).toEqual({ type: 'resync', high_water_mark: 4 });
		expect(
			parseResourceStreamEvent({
				id: null,
				event: 'heartbeat',
				data: '{"type":"heartbeat"}'
			})
		).toEqual({ type: 'heartbeat' });
		expect(
			parseResourceStreamEvent({
				id: '5',
				event: 'generation.created',
				data: JSON.stringify({
					type: 'generation.created',
					kind: 'generation.created',
					sequence: 5,
					user_id: 'u1',
					resource_type: 'song',
					resource_id: 's1',
					song_id: 's1',
					generation_id: 'g1',
					created_at: '2026-01-01T00:00:00+00:00'
				})
			})
		).toMatchObject({ type: 'generation.created', sequence: 5, generation_id: 'g1' });
	});

	it('rejects malformed payloads instead of skipping them', () => {
		expect(() =>
			parseResourceStreamEvent({ id: null, event: 'hello', data: 'not-json' })
		).toThrow(/Malformed resource event/);
		expect(() =>
			parseResourceStreamEvent({
				id: null,
				event: 'generation.created',
				data: '{"type":"generation.created"}'
			})
		).toThrow(/Malformed resource event field/);
	});
});

describe('openResourceEventStream', () => {
	beforeEach(() => {
		mockFetch.mockReset();
	});

	it('sends Last-Event-ID and yields typed events', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			body: streamFrom([
				'event: hello\ndata: {"type":"hello","high_water_mark":1}\n\n',
				'id: 2\nevent: generation.created\ndata: {"type":"generation.created","kind":"generation.created","sequence":2,"user_id":"u1","resource_type":"song","resource_id":"s1","song_id":"s1","generation_id":"g2","created_at":"t"}\n\n'
			])
		});
		const events = [];
		for await (const event of openResourceEventStream(1, new AbortController().signal)) {
			events.push(event);
		}
		expect(mockFetch).toHaveBeenCalledWith(
			RESOURCE_EVENTS_PATH,
			expect.objectContaining({
				credentials: 'include',
				headers: expect.objectContaining({ 'Last-Event-ID': '1' })
			})
		);
		expect(events[0]).toEqual({ type: 'hello', high_water_mark: 1 });
		expect(events[1]).toMatchObject({ type: 'generation.created', sequence: 2 });
	});

	it('omits Last-Event-ID on first connect', async () => {
		mockFetch.mockResolvedValueOnce({ ok: true, body: streamFrom([]) });
		const gen = openResourceEventStream(null, new AbortController().signal);
		await gen.next();
		const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
		expect(headers['Last-Event-ID']).toBeUndefined();
	});

	it('throws ApiError on non-2xx', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 401,
			json: () => Promise.resolve({ detail: 'Authentication required' })
		});
		const gen = openResourceEventStream(null, new AbortController().signal);
		await expect(gen.next()).rejects.toBeInstanceOf(ApiError);
	});
});
