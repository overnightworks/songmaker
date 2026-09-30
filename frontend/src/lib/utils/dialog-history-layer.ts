import type { Attachment } from 'svelte/attachments';
import { registerHistoryLayer } from '$lib/stores/navigation';

interface DialogHistoryLayer {
	hold: Attachment;
	answer: <Args extends unknown[]>(action: (...args: Args) => void) => (...args: Args) => void;
}

// Back closes a dialog through `close` and never runs one of its answers
// (issue #1125): the dialog holds one history entry while shown, and each of
// its own answers steps back off that entry before acting, so a navigation the
// answer starts lands after it.
export function dialogHistoryLayer(id: string, close: () => void): DialogHistoryLayer {
	let registration: ReturnType<typeof registerHistoryLayer> | undefined;

	function leave(): void {
		if (registration?.layered) registration.leave();
	}

	return {
		hold: () => {
			registration = registerHistoryLayer(id, close);
			return leave;
		},
		answer:
			(action) =>
			(...args) => {
				leave();
				action(...args);
			}
	};
}
