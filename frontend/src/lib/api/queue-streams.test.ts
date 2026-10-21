import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

import { createQueueStreamSnapshot, pinQueueStream, unpinQueueStream } from './queue-streams';

function acceptRequests(): void {
	mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ snapshot_id: 'snap-1' }) });
}

function request(): [string, RequestInit] {
	return mockFetch.mock.calls[0] as [string, RequestInit];
}

beforeEach(() => {
	mockFetch.mockReset();
	acceptRequests();
});

describe('queue stream API contract', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('builds an explicit snapshot', async () => {
		await createQueueStreamSnapshot([{ generation_id: 'g-1' }]);
		const [url, init] = request();
		expect(url).toBe('/api/queue-streams');
		expect(init.method).toBe('POST');
	});

	it('keeps a cold snapshot build alive for its 120 second timeout budget', () => {
		vi.useFakeTimers();
		mockFetch.mockImplementationOnce(() => new Promise(() => {}));

		void createQueueStreamSnapshot([{ generation_id: 'g-1' }]).catch(() => {});
		const signal = request()[1].signal as AbortSignal;
		vi.advanceTimersByTime(119_999);
		expect(signal.aborted).toBe(false);
		vi.advanceTimersByTime(1);
		expect(signal.aborted).toBe(true);
	});

	it.each([
		['pins', () => pinQueueStream('snap-1'), 'POST'],
		['unpins', () => unpinQueueStream('snap-1'), 'DELETE']
	])('%s a snapshot through its pin endpoint', async (_name, send, method) => {
		await send();
		const [url, init] = request();
		expect(url).toBe('/api/queue-streams/snap-1/pin');
		expect(init.method).toBe(method);
	});
});
