import { closeTopLayer } from '$lib/stores/layers';

const FOCUSABLE_SELECTOR = [
	'a[href]',
	'button:not(:disabled)',
	'input:not(:disabled)',
	'select:not(:disabled)',
	'textarea:not(:disabled)',
	'[tabindex]:not([tabindex="-1"])'
].join(', ');

function focusableElements(container: HTMLElement): HTMLElement[] {
	return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

// A surface that closes -- by Escape, Back or a click away -- while focus sat
// inside it leaves focus on the page itself; the control that opened it takes
// it back. Focus the person moved elsewhere stays where it is.
export function refocusIfDropped(opener: HTMLElement | undefined): void {
	const active = document.activeElement;
	if (active === null || active === document.body) opener?.focus();
}

export function focusFirstIn(container: HTMLElement): void {
	const first = focusableElements(container)[0];
	(first ?? container).focus();
}

function trapTabKey(container: HTMLElement, event: KeyboardEvent): void {
	const focusable = focusableElements(container);
	if (focusable.length === 0) {
		event.preventDefault();
		container.focus();
		return;
	}
	const first = focusable[0];
	const last = focusable.at(-1);
	if (!last) return;
	const active = document.activeElement;
	const outside = !container.contains(active);
	if (event.shiftKey && (active === first || active === container || outside)) {
		event.preventDefault();
		last.focus();
	} else if (!event.shiftKey && (active === last || outside)) {
		event.preventDefault();
		first.focus();
	}
}

/**
 * Keeps focus inside `container` while it acts as a modal-like surface
 * (drawer, dropdown menu, dialog): Escape closes the topmost open layer -- the
 * one Back closes too, which is this surface unless something opened over it
 * -- and Tab/Shift+Tab wrap at the container's edges instead of leaving it.
 */
export function handleFocusTrapKeydown(container: HTMLElement, event: KeyboardEvent): void {
	if (event.defaultPrevented) return;
	if (event.key === 'Escape') {
		if (closeTopLayer()) event.preventDefault();
		return;
	}
	if (event.key !== 'Tab') return;
	trapTabKey(container, event);
}
