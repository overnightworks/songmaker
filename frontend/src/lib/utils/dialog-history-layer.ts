import type { Attachment } from 'svelte/attachments';
import { holdLayer } from '$lib/stores/layers';

interface DialogHistoryLayer {
	hold: Attachment;
	answer: <Args extends unknown[]>(action: (...args: Args) => void) => (...args: Args) => void;
}

// Escape and Back close a dialog through `close` and never run one of its
// answers (issue #1125): the dialog holds one layer while shown, and each of
// its own answers leaves that layer -- stepping back off its history entry --
// before acting, so a navigation the answer starts lands after it.
export function dialogHistoryLayer(id: string, close: () => void): DialogHistoryLayer {
	let leave: (() => void) | undefined;

	return {
		hold: () => {
			leave = holdLayer(id, close);
			return leave;
		},
		answer:
			(action) =>
			(...args) => {
				leave?.();
				action(...args);
			}
	};
}
