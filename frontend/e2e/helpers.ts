// Shared guards and name matchers for the browser flows.

import { expect, type Locator, type Page } from '@playwright/test';

// The desktop library flow measured 26 /api requests on its first green run;
// this is that plus 20% headroom. A flow that suddenly costs more round trips
// is a regression, not a reason to raise this number.
export const LIBRARY_FLOW_API_REQUEST_BUDGET = 32;

const API_PATH_PREFIX = '/api';

// AlbumDetailView and PlaylistDetailView build their row labels inline rather
// than from a constant, so the flows mirror the wording here.
const PLAY_LABEL = 'Play';
const PAUSE_LABEL = 'Pause';

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

/** Every collection row, in screen order — labelled "Play <title>", or "Pause <title>" while playing. */
export function playableRows(page: Page): Locator {
	return workspace(page).getByRole('button', {
		name: nameStartingWith(`${PLAY_LABEL} `, `${PAUSE_LABEL} `)
	});
}

/** One collection row, whichever of the two labels it currently carries. */
export function playableRow(page: Page, title: string): Locator {
	return workspace(page).getByRole('button', {
		name: new RegExp(`^(${PLAY_LABEL}|${PAUSE_LABEL}) ${escapeForRegExp(title)}$`)
	});
}

export function playRowLabel(title: string): string {
	return `${PLAY_LABEL} ${title}`;
}

export function containing(title: string): RegExp {
	return new RegExp(escapeForRegExp(title));
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
