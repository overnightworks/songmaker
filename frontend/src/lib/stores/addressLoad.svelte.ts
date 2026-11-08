import { describeFailure } from '#lib/api/fetch.ts';
import { reloadWhileUnreachable } from './connectivity.ts';
import { libraryAddressOverlayActive } from './libraryAddressOverlay.ts';
import { reloadWhenLibraryReturns, retryLibraryOr } from './libraryRecovery.ts';

interface AddressLoadSource<Verdict extends string> {
	/** Reads the page's derived params before its first `await`, so the owner's effect tracks them. */
	load: () => Promise<'found' | Verdict>;
	fallbackMessage: string;
}

/**
 * The one address load of an address page, called once at component init:
 * resolves the address whenever the params `load` reads change, drops an
 * answer a newer load superseded, reads a failed address again once the
 * network or the library returns, and runs the Try again press. It also
 * keeps the workspace behind the page inert while the page shows no open
 * address.
 */
export function createAddressLoad<Verdict extends string>(source: AddressLoadSource<Verdict>) {
	let state = $state<'resolving' | 'open' | 'unreachable' | Verdict>('resolving');
	let failure = $state<string | null>(null);
	let pressing = $state(false);
	let openRequests = 0;

	// An address that could not be read shows its one line with Retry, and
	// reads again by itself once the network lets it.
	const addressReloads = reloadWhileUnreachable(() => void openAddress());
	// A failed address also reads again once the library is ready, and its Try again
	// retries the library first while that load failed.
	const libraryReturns = reloadWhenLibraryReturns(() => void openAddress());

	async function openAddress(): Promise<void> {
		const request = ++openRequests;
		state = 'resolving';
		failure = null;
		libraryReturns.loadStarted();
		try {
			const address = await source.load();
			if (request !== openRequests) return;
			addressReloads.stop();
			libraryReturns.loadSucceeded();
			state = address === 'found' ? 'open' : address;
		} catch (err) {
			if (request !== openRequests) return;
			addressReloads.afterLoadFailure(err);
			libraryReturns.loadFailed();
			failure = describeFailure(err, source.fallbackMessage);
			state = 'unreachable';
		}
	}

	async function tryAgain(): Promise<void> {
		pressing = true;
		try {
			await retryLibraryOr(openAddress);
		} finally {
			pressing = false;
		}
	}

	$effect(() => () => addressReloads.stop());
	$effect(() => () => libraryReturns.dispose());

	$effect(() => {
		void openAddress();
	});

	// The overlay above hides a stale workspace visually (`position: absolute`)
	// but not from the accessibility tree or the tab order -- `inert` on the
	// workspace wrapper is what actually does that, and it lives one level up
	// in `(library)/+layout.svelte`, so this bridges the address state across
	// with a store. Active whenever the page isn't showing the open workspace,
	// including the (route-change-only) unmount: leaving the page for
	// `/` or another address must not leave the workspace inert behind it.
	$effect(() => {
		libraryAddressOverlayActive.set(state !== 'open');
		return () => libraryAddressOverlayActive.set(false);
	});

	return {
		get state() {
			return state;
		},
		get failure() {
			return failure;
		},
		get pressing() {
			return pressing;
		},
		tryAgain
	};
}
