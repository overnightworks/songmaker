import { vi } from 'vitest';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';

const ANY_API_PATH = '/api';

export function browserReportsOnline(online: boolean): void {
	vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(online);
	window.dispatchEvent(new Event(online ? 'online' : 'offline'));
}

export function lostNetwork(): NetworkError {
	return new NetworkError(ANY_API_PATH, new TypeError('Failed to fetch'));
}

export function hangsUntilAborted(_path: string, init: RequestInit): Promise<never> {
	return new Promise((_resolve, reject) => {
		init.signal?.addEventListener('abort', () =>
			reject(new DOMException('signal is aborted without reason', 'AbortError'))
		);
	});
}

export function serverRefusal(detail: string): ApiError {
	return new ApiError(422, detail, ANY_API_PATH);
}
