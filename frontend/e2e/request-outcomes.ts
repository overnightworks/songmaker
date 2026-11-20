// How the flow guard reads what became of a request.

import type { Page, Request, Response } from '@playwright/test';

const BYTE_RANGE_SERVED = /^bytes (\d+)-(\d+)\/(\d+)$/;
const BYTE_RANGE_TO_THE_END = /^bytes=\d+-$/;

// The deck resumes a cancelled take with a range request from where the cancel
// cut it (`continuousDeck.ts`), and the browser reads a playing element with
// open-ended ranges too. Only a GET that asked for the take to its end and was
// answered with the whole take, or with the part from the cut to its last byte,
// completes it: the player's HEAD probe of the take, the one-byte reads seen
// beside it, and an answer that names no known end deliver nothing.
export function completesTheTake(response: Response): boolean {
	const request = response.request();
	if (request.method() !== 'GET') return false;
	const asked = request.headers()['range'];
	if (asked !== undefined && !BYTE_RANGE_TO_THE_END.test(asked)) return false;
	if (response.status() === 200) return true;
	if (response.status() !== 206) return false;
	const served = BYTE_RANGE_SERVED.exec(response.headers()['content-range'] ?? '');
	return served !== null && Number(served[2]) + 1 === Number(served[3]);
}

/**
 * Chromium reports a request the old document still has in flight, or starts while the main
 * frame's document navigation is pending, as cancelled once that document goes: its module
 * preloads and a fetch the next goto cuts off. A request that aborts with no navigation in
 * between is not one of these.
 */
export class NavigationCutoffs {
	private readonly inFlight = new Set<Request>();
	private readonly cutOff = new WeakSet<Request>();
	private navigationPending = false;

	constructor(private readonly page: Page) {
		page.on('request', (request) => this.started(request));
		page.on('requestfinished', (request) => this.inFlight.delete(request));
		page.on('requestfailed', (request) => {
			this.inFlight.delete(request);
			if (request.isNavigationRequest()) this.navigationPending = false;
		});
		page.on('framenavigated', (frame) => {
			if (frame === page.mainFrame()) this.navigationPending = false;
		});
	}

	cuts(request: Request): boolean {
		return this.cutOff.has(request);
	}

	private started(request: Request): void {
		if (this.navigationPending) this.cutOff.add(request);
		else this.inFlight.add(request);
		if (request.isNavigationRequest() && request.frame() === this.page.mainFrame()) {
			this.navigationPending = true;
			this.inFlight.delete(request);
			for (const pending of this.inFlight) this.cutOff.add(pending);
			this.inFlight.clear();
		}
	}
}
