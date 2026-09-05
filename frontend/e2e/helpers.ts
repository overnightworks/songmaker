// Shared guards, shell facts and name matchers for the browser flows.

import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';
import { RESOURCE_EVENT_STREAM_PATH } from '../src/lib/constants';

/** The two shells the same flow drives — also the Playwright project names. */
export type Shell = 'desktop' | 'mobile';

// Above 1099px Now Playing keeps its three columns and docks beside the
// workspace rather than covering it, and above 768px the shell keeps its rail;
// the mobile viewport is a phone in portrait, and the narrow one is the
// smallest screen the album header still has to read on.
export const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
export const MOBILE_VIEWPORT = { width: 390, height: 844 };
export const NARROW_VIEWPORT = { width: 320, height: 844 };

/**
 * What the library flow costs the API per shell, measured on a green full-suite
 * run against `library.spec.ts`'s own first test: 40 requests on desktop and
 * 30 on mobile against a clean stack, budgeted at 40 for both. Both projects
 * share one IP rate-limit window, so a flow that suddenly needs more round
 * trips is a regression — find the extra requests instead of raising this
 * number. Every other mention of this budget (the `e2e/README.md` table,
 * `docs/testing.md`)
 * points back here rather than restating it, which is exactly how those
 * three numbers drifted apart before: #312 and #325 each added a request per
 * page load (`ensureAllAlbumsLoaded`, `ensurePlaylistsLoaded`) without this
 * constant, or its callers, ever being re-measured.
 */
export const LIBRARY_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 40,
	mobile: 40
};

/**
 * What the rail's own disclosure/pin flow (`library.spec.ts`'s second test)
 * costs the API per shell, measured on a green run against a clean stack: 32
 * on desktop, 29 on mobile. One shared ceiling for both, matching
 * LIBRARY_FLOW_API_REQUEST_BUDGET's own convention -- a separate budget from
 * it, for a different flow, sharing only the one IP rate-limit window both
 * tests already share.
 */
export const RAIL_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 34,
	mobile: 34
};

const API_PATH_PREFIX = '/api';

/** Which shell a test drives: the mobile project is the emulated phone. */
export function shellOf(testInfo: TestInfo): Shell {
	return testInfo.project.use.isMobile ? 'mobile' : 'desktop';
}

function escapeForRegExp(literal: string): string {
	return literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Matches an accessible name that starts with one of the given labels. */
export function nameStartingWith(...labels: string[]): RegExp {
	return new RegExp(`^(${labels.map(escapeForRegExp).join('|')})`);
}

/**
 * The open surface — wall, album, song editor or playlist. Scoping to it keeps
 * the flows off the rail, which mirrors the same titles in its context list.
 */
export function workspace(page: Page): Locator {
	return page.getByRole('main');
}

/**
 * The open playlist's entries, in screen order — the rows themselves, since a
 * row now carries two controls (▶ plays, the row body plays and judges) and
 * neither of them alone is the entry.
 */
export function playlistEntryRows(page: Page): Locator {
	return workspace(page).getByRole('listitem');
}

export function containing(title: string): RegExp {
	return new RegExp(escapeForRegExp(title));
}

export interface RenderedBox {
	x: number;
	y: number;
	width: number;
	height: number;
}

/** Rendered boxes, in the order given — how a flow measures a layout promise. */
export async function boundingBoxes(...locators: Locator[]): Promise<RenderedBox[]> {
	return Promise.all(
		locators.map(async (locator) => {
			const box = await locator.boundingBox();
			if (!box) throw new Error('Expected a rendered box to measure');
			return box;
		})
	);
}

/**
 * Fails the flow on a rate-limited or failed response, on a browser console
 * error, and on an uncaught page exception — and counts what the flow costs
 * the API.
 */
export class FlowGuard {
	private readonly failures: string[] = [];
	private apiRequests = 0;

	constructor(page: Page) {
		page.on('request', (request) => {
			if (new URL(request.url()).pathname.startsWith(API_PATH_PREFIX)) this.apiRequests += 1;
		});
		page.on('requestfailed', (request) => {
			const errorText = request.failure()?.errorText ?? 'unknown';
			// Leaving the library route (Settings, sign-out) intentionally closes
			// the live resource-event stream (`ResourceSyncController.stop()`);
			// Chromium reports the cancelled in-flight GET as a failed request
			// with exactly this error, indistinguishable from any other
			// intentional client-side abort. Every other reason still fails the
			// flow, including a 429 or 5xx on the same path (handled below).
			if (errorText === 'net::ERR_ABORTED' && request.url().endsWith(RESOURCE_EVENT_STREAM_PATH)) {
				return;
			}
			this.failures.push(`request failed: ${request.url()} (${errorText})`);
		});
		page.on('response', (response) => {
			const status = response.status();
			if (status === 429 || status >= 500) {
				this.failures.push(`${status} from ${response.url()}`);
			}
		});
		page.on('console', (message) => {
			if (message.type() === 'error') this.failures.push(`console error: ${message.text()}`);
		});
		page.on('pageerror', (error) => {
			this.failures.push(`uncaught page error: ${error.message}`);
		});
	}

	get apiRequestCount(): number {
		return this.apiRequests;
	}

	assertClean(): void {
		expect(this.failures).toEqual([]);
	}

	assertWithinBudget(budget: number): void {
		expect(this.apiRequestCount).toBeLessThanOrEqual(budget);
	}
}
