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

interface UploadAnswer {
	status: number;
	body: string;
	retryAfter?: string;
}

// The upload transport runs on XMLHttpRequest; this stands in for the browser's.
let sentUploads: FakeUploadRequest[] = [];

export class FakeUploadRequest {
	opened: string[] = [];
	withCredentials = false;
	sentBody: unknown = null;
	upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
	onload: (() => void) | null = null;
	onerror: (() => void) | null = null;
	onabort: (() => void) | null = null;

	constructor(private readonly answer: UploadAnswer) {}

	get status() {
		return this.answer.status;
	}
	get responseText() {
		return this.answer.body;
	}
	open(...opened: string[]) {
		this.opened = opened;
	}
	getResponseHeader(name: string) {
		return name === 'Retry-After' ? (this.answer.retryAfter ?? null) : null;
	}
	send(body: unknown) {
		this.sentBody = body;
		sentUploads.push(this);
	}
	abort() {
		this.onabort?.();
	}
}

export function uploadAnswers(answer: UploadAnswer) {
	sentUploads = [];
	vi.stubGlobal(
		'XMLHttpRequest',
		class extends FakeUploadRequest {
			constructor() {
				super(answer);
			}
		}
	);
}

export const sentUpload = () => sentUploads[sentUploads.length - 1];
