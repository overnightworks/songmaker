// Shared guards and name matchers for the browser flows.

import { expect, type Locator, type Page } from '@playwright/test';
import { COLLECTION_ROW_PAUSE_ACTION, COLLECTION_ROW_PLAY_ACTION } from '../src/lib/constants';

// The desktop library flow measured 26 /api requests on its first green run;
// this is that plus 20% headroom. A flow that suddenly costs more round trips
// is a regression, not a reason to raise this number.
export const LIBRARY_FLOW_API_REQUEST_BUDGET = 32;

const API_PATH_PREFIX = '/api';

// The transport's play button renames itself after the state it will leave:
// "Pause" only while audio is really playing, "Retry" once it errored (see
// TransportBarFrame.svelte). Asserting it is how a flow proves a click
// produced sound rather than a dead take.
export const TRANSPORT_PAUSE_LABEL = 'Pause';

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

/** Every collection row, in screen order. */
export function playableRows(page: Page): Locator {
	return workspace(page).getByRole('button', {
		name: nameStartingWith(`${COLLECTION_ROW_PLAY_ACTION} `, `${COLLECTION_ROW_PAUSE_ACTION} `)
	});
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
		page.on('requestfailed', (request) => {
			this.failures.push(
				`request failed: ${request.url()} (${request.failure()?.errorText ?? 'unknown'})`
			);
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
