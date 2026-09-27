/**
 * A failure a module of this app worded for the musician itself, such as
 * "Service worker not active — cannot save for offline". Only this type's
 * message may reach the screen as it is (through `describeFailure` in
 * `fetch.ts`); any other error's text may be a browser's. It lives apart from
 * `fetch.ts` so the service worker can throw it without bundling the app's
 * stores.
 */
export class UserFacingError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'UserFacingError';
	}
}
