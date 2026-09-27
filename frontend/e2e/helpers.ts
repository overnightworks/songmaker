// Shared guards, shell facts and name matchers for the browser flows.

import {
	expect,
	type BrowserContext,
	type Locator,
	type Page,
	type TestInfo
} from '@playwright/test';
import {
	COWRITER_TURN_PATH,
	RAIL_DRAWER_LABEL,
	RAIL_DRAWER_OPEN_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_NAV_LABEL,
	RESOURCE_EVENT_STREAM_PATH
} from '../src/lib/constants';
import { BASE_URL } from './seed';

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
 * run against `library.spec.ts`'s own first test: 41 requests on desktop and
 * 30 on mobile against a clean stack, budgeted at 41 and 40 respectively. The
 * desktop increase is caused by Continue fetching fresh on the return to the
 * wall (measured 41 on 05.09.2026); mobile is unchanged. Both projects
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
	desktop: 41,
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

/**
 * What `song-phone.spec.ts` costs the API, measured on a green run against a
 * clean stack: opening the album, selecting the song, the Takes tab, playing
 * a take, a second cold open of the same song for the seeded running job,
 * then its Takes-tab and Write-tab views once that job is failed live over
 * its own open SSE stream — measured 49 requests. The running-job and
 * failed-job seeding themselves never touch this budget at all, since both
 * run directly against the database (`seedRunningGenerationJob`,
 * `failGenerationJob` in `seed.ts`), the same way the rail's filler albums
 * and the kinetic-strip takes do. Mobile-only, matching the spec's own
 * project restriction — no desktop number to carry.
 */
export const SONG_PHONE_FLOW_API_REQUEST_BUDGET = 55;

/**
 * What `take-arrives.spec.ts` costs the API, measured on a green run against a
 * clean stack: opening the album, selecting the song with its seeded running
 * job, the Takes tab, then the job's terminal song refresh once the job ends
 * over its own open SSE stream — measured 23 requests. The job seeding and its
 * completion run directly against the database, the same way
 * `SONG_PHONE_FLOW_API_REQUEST_BUDGET`'s do. Mobile-only.
 */
export const TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET = 30;

/**
 * What `take-arrives.spec.ts`'s offline flow costs the API: the same open,
 * song and Takes tab as `TAKE_ARRIVES_FLOW_API_REQUEST_BUDGET` (23 measured),
 * plus one job-stream attempt per backoff step while the stream is cut off
 * (at most five in the flow's cut-off window) and the stream that reopens when
 * the network returns.
 */
export const TAKE_AFTER_RETURN_FLOW_API_REQUEST_BUDGET = 36;

/**
 * What `offline.spec.ts` costs the API: opening a seeded song on the phone,
 * then losing the network and getting it back, with the live stream that
 * reopens on the return — measured 23. Mobile-only.
 */
export const OFFLINE_FLOW_API_REQUEST_BUDGET = 30;

const API_PATH_PREFIX = '/api';
// How Chromium fails a request while `loseNetwork` holds the network away.
const NETWORK_LOST_ERROR = 'net::ERR_INTERNET_DISCONNECTED';
const JOB_STREAM_PATH = /^\/api\/jobs\/[^/]+\/stream$/;

// Streams the client closes on purpose: leaving the library route (Settings,
// sign-out) stops the live resource-event stream
// (`ResourceSyncController.stop()`), a co-writer turn's reader stops on the
// last event it needs, including a named failure, and a job's stream closes
// on the job's terminal status (`completeTrackedJob` in `stores/jobs.ts`) —
// racing the server's own end-of-stream right behind it, which a loaded
// machine loses often enough to fail a flow (#1020). Matched on the path
// alone: a resumed resource stream carries a `last_event_id` query.
function isClosedOnPurpose(url: string): boolean {
	const path = new URL(url).pathname;
	return (
		path === RESOURCE_EVENT_STREAM_PATH || path === COWRITER_TURN_PATH || JOB_STREAM_PATH.test(path)
	);
}

const isResourceEventStream = (url: URL): boolean => url.pathname === RESOURCE_EVENT_STREAM_PATH;

/**
 * Takes the page's network away the way a phone loses it. `setOffline` alone
 * leaves a live event stream the page already holds running (see
 * docs/testing.md), so the page's open loads are stopped the way a dropped
 * network ends them, and every reopen of the library's resource stream is
 * refused until `regainNetwork`.
 */
export async function loseNetwork(page: Page, context: BrowserContext): Promise<void> {
	await page.route(isResourceEventStream, (route) => route.abort('internetdisconnected'));
	await context.setOffline(true);
	await page.evaluate(() => window.stop());
}

/** Gives the page its network back: the browser reports online and the stream may reopen. */
export async function regainNetwork(page: Page, context: BrowserContext): Promise<void> {
	await page.unroute(isResourceEventStream);
	await context.setOffline(false);
}

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
 * The phone app bar landmark (`PhoneAppBar.svelte`, mounted by
 * `+layout.svelte` outside `<main>`). On the song route at compact widths it
 * carries the song title, share, and menu; `workspace()` no longer sees them
 * there, so a mobile flow asserting on the song heading reads this landmark
 * instead.
 */
export function appBar(page: Page): Locator {
	return page.getByRole('banner');
}

/** Back to the wall through LIBRARY's first child, in the same SPA document. */
export async function openLibraryWall(page: Page, shell: Shell): Promise<void> {
	const rail = await openRailNav(page, shell);
	const libraryGroup = rail.getByRole('button', { name: nameStartingWith(RAIL_LIBRARY_LABEL) });
	if ((await libraryGroup.getAttribute('aria-expanded')) === 'false') await libraryGroup.click();
	await rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('button', { name: nameStartingWith('All albums') })
		.click();
	if (shell === 'mobile')
		await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeHidden();
}

/** Headers a browser session's own out-of-page API write needs past the CSRF guard. */
export async function csrfHeaders(page: Page): Promise<Record<string, string>> {
	const csrf = (await page.context().cookies(BASE_URL)).find(
		(cookie) => cookie.name === 'csrf_token'
	);
	if (!csrf) throw new Error('The E2E session has no CSRF token');
	return { 'x-csrf-token': csrf.value, origin: BASE_URL };
}

/** The rail's own navigation — behind the drawer on the compact shell. */
export async function openRailNav(page: Page, shell: Shell): Promise<Locator> {
	if (shell === 'mobile') {
		const drawer = page.getByRole('dialog', { name: RAIL_DRAWER_LABEL });
		if (!(await drawer.isVisible())) {
			await page.getByRole('button', { name: RAIL_DRAWER_OPEN_LABEL }).click();
		}
	}
	return page.getByRole('navigation', { name: RAIL_NAV_LABEL });
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
 * Paths whose refusal is the behaviour a flow is there to prove rather than a
 * guard-rail failure. `auth-flows.spec.ts` drives real ones — a locked account,
 * a session the server no longer honours, an admin page a non-admin asks for —
 * and Chromium reports every refused fetch as a console error of its own, on
 * top of the response itself. Both are forgiven on exactly these paths and
 * nowhere else; a 5xx never is.
 */
export interface FlowGuardOptions {
	refusalsExpectedOn?: readonly string[];
	// A flow that calls `loseNetwork` drives that loss on purpose, so neither
	// the failed request nor the console line Chromium adds for it is a guard
	// failure there — and stays one in every other flow.
	losesNetworkOnPurpose?: boolean;
}

const REFUSED_STATUSES: readonly number[] = [401, 403, 429];
const REFUSED_RESOURCE_CONSOLE_MESSAGE =
	/^Failed to load resource: the server responded with a status of (401|403|429)\b/;

/**
 * Fails the flow on a rate-limited or failed response, on a browser console
 * error, and on an uncaught page exception — and counts what the flow costs
 * the API.
 */
export class FlowGuard {
	private readonly failures: string[] = [];
	private apiRequests = 0;

	constructor(page: Page, options: FlowGuardOptions = {}) {
		const refusalsExpectedOn = options.refusalsExpectedOn ?? [];
		const losesNetworkOnPurpose = options.losesNetworkOnPurpose ?? false;
		const refusalIsExpectedOn = (url: string): boolean =>
			refusalsExpectedOn.includes(new URL(url).pathname);
		page.on('request', (request) => {
			if (new URL(request.url()).pathname.startsWith(API_PATH_PREFIX)) this.apiRequests += 1;
		});
		page.on('requestfailed', (request) => {
			const errorText = request.failure()?.errorText ?? 'unknown';
			// Chromium reports a stream the client cancelled in flight as a failed
			// request with exactly this error, indistinguishable from any other
			// intentional client-side abort. Every other reason still fails the
			// flow, including a 429 or 5xx on the same path (handled below).
			if (errorText === 'net::ERR_ABORTED' && isClosedOnPurpose(request.url())) {
				return;
			}
			if (losesNetworkOnPurpose && errorText === NETWORK_LOST_ERROR) return;
			this.failures.push(`request failed: ${request.url()} (${errorText})`);
		});
		page.on('response', (response) => {
			const status = response.status();
			if (REFUSED_STATUSES.includes(status) && refusalIsExpectedOn(response.url())) return;
			if (status === 429 || status >= 500) {
				this.failures.push(`${status} from ${response.url()}`);
			}
		});
		page.on('console', (message) => {
			if (message.type() !== 'error') return;
			if (losesNetworkOnPurpose && message.text().includes(NETWORK_LOST_ERROR)) return;
			const reportsAnExpectedRefusal =
				REFUSED_RESOURCE_CONSOLE_MESSAGE.test(message.text()) &&
				refusalIsExpectedOn(message.location().url);
			if (reportsAnExpectedRefusal) return;
			this.failures.push(`console error: ${message.text()}`);
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
