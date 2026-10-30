import { pageBelowStandingPage } from '#lib/history/historyController.ts';

// The address history stands on now. `page.state` follows every entry history
// stands on -- shallow routing included, which leaves `page.url` where the
// router last navigated -- so a reader of where history stands passes it in as
// the one thing it re-reads on, and takes the address from `location`.
export function standingPathname(_stateOfStandingEntry: unknown): string {
	return location.pathname;
}

export interface StandingPage {
	readonly pathname: string;
	readonly below: string | null;
}

export function standingPage(stateOfStandingEntry: unknown): StandingPage {
	return {
		pathname: standingPathname(stateOfStandingEntry),
		below: pageBelowStandingPage()
	};
}
